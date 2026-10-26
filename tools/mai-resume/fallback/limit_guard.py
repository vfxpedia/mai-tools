"""mai-resume 의 뒷받침 지킴이 (Claude 한도만 · 첫 시제품 10/20 · 뒷받침 10/26).

한도가 차기 직전에 Claude 세션들에 「안전한 지점에서 마무리 · 인계 기록」 을 보내고,
한도가 풀리면 같은 세션들에 「인계를 읽고 이어 가기」 를 보낸다.
Claude 세션 밖에서 도는 프로세스라 세션이 한도로 멈춰도 깨우는 쪽은 살아 있다.

입력: ~/.mai/limits.json (mai-gauge 상태 표시줄이 갱신, 계정 default 의 five_hour · seven_day)
설정: ~/.mai/limit-guard/config.json (예시 config.example.json) · 상태: state.json · 로그: guard.log

뒷받침: 주 지킴이는 mai-resume 다. mai-resume 는 기기마다 하나만 돌려고 127.0.0.1:28766 을
bind · listen 하고 연결은 받지 않는다. 그래서 그 포트를 **이쪽이 bind 해 보아** 이미 쓰는 중이면
(EADDRINUSE) mai-resume 가 살아 있는 것이고, 이 지킴이는 아무것도 보내지 않는다 (경고 · 재개 · 캐시 유지 전부).
비었을 때만 보낸다. 포트는 config 의 primary_lock_port (기본 28766), 0 이면 검사하지 않음.
붙어 보는 (connect) 방식은 쓰지 않는다: mai-resume 가 연결을 받지 않아 대기열 (listen(1)) 이 차면
살아 있어도 시간 초과가 나 「죽음」 으로 읽힌다 (10/26 실측, tests/test_fallback.py 가 재현).
"""
import argparse
import datetime as dt
import errno
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
BASE = HOME / ".mai" / "limit-guard"
LIMITS = HOME / ".mai" / "limits.json"
CONFIG = BASE / "config.json"
STATE = BASE / "state.json"
LOG = BASE / "guard.log"
CREATE_NO_WINDOW = 0x08000000
# cmd 를 거치면 줄바꿈에서 인자가 잘린다(10/20 실측) → orca.exe 를 직접 부른다
# Linux 의 맨 `orca` 는 GNOME 화면 낭독기라 Orca 실행 파일은 ORCA_CLI_COMMAND 또는 orca-ide 를 쓴다
ORCA = os.environ.get("ORCA_CLI_COMMAND") or (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "orca", "resources", "bin", "orca.exe")
    if os.name == "nt" else "orca-ide")

WARN_MSG = (
    "[한도 지킴이 {now}] Claude {window} 한도 {pct}% (풀림 {reset}). "
    "새 큰 작업은 시작하지 말고, 지금 하던 일을 안전한 지점(파일 저장 · 커밋 가능한 단위)까지만 마무리한 뒤 "
    "자기 HANDOFF(무엇을 했고 · 어디서 멈췄고 · 다음 한 걸음 · 미커밋 파일)를 적고 멈추세요. "
    "돌고 있는 GPU 작업은 건드리지 마세요. 한도가 풀리면 이 지킴이가 재개 신호를 보냅니다."
)
RESUME_MSG = (
    "[한도 지킴이 {now}] Claude {window} 한도가 풀렸습니다. "
    "자기 HANDOFF 와 마지막 지시를 다시 읽고, 멈춘 일을 이어 가세요. 끝난 일이면 다음 일을 진행하세요."
)


def now_local():
    return dt.datetime.now().strftime("%m/%d %H:%M")


def log(msg):
    BASE.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}\n")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def latest(limits, window):
    arr = limits.get("default", {}).get(window) or []
    if not arr:
        return None
    e = max(arr, key=lambda x: x.get("at", 0))
    reset = dt.datetime.fromisoformat(e["reset"].replace("Z", "+00:00"))
    return {"pct": e.get("pct", 0), "reset": reset, "at": e.get("at", 0)}


def send(handle, text, dry):
    if dry:
        log(f"DRY send {handle}: {text[:80]}")
        return True
    try:
        r = subprocess.run(
            [ORCA, "terminal", "send", "--terminal", handle, "--text", " ".join(text.split()), "--enter", "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        ok = r.returncode == 0
        log(f"send {handle} rc={r.returncode} {(r.stdout or r.stderr)[:200].strip()}")
        return ok
    except Exception as ex:
        log(f"send {handle} error {ex!r}")
        return False


PRIMARY_LOCK_PORT = 28766


IN_USE = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}


def primary_alive(port):
    """mai-resume 의 잠금 포트를 누가 잡고 있으면 살아 있다. 0 이면 검사하지 않는다 (늘 없음으로 본다).

    bind 해 보고 바로 놓는다 (SO_REUSEADDR 없이, 그래야 남이 잡은 포트에서 실패한다). 잡고 있는
    시간은 마이크로초라 그 순간 mai-resume 가 새로 뜨면 그 한 번은 실패하고 다음 반복에서 뜬다.
    「이미 쓰는 중」 밖의 오류 (권한 · 예약된 범위 등) 는 mai-resume 도 그 포트를 못 잡으니 없음으로 본다."""
    if not port:
        return False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError as e:
        return e.errno in IN_USE
    finally:
        s.close()


def tick(cfg, state, limits, now_utc, dry):
    port = cfg.get("primary_lock_port", PRIMARY_LOCK_PORT)
    if primary_alive(port):
        # 주 지킴이가 맡고 있다. 아무것도 보내지 않고, 경고 · 재개 기록도 남기지 않는다
        # (mai-resume 가 도중에 죽으면 이 지킴이가 그 창에서 처음부터 맡는다. 같은 경고가 한 번 더 갈 수는 있다)
        if not state.get("standby"):
            log(f"STANDBY mai-resume 가 127.0.0.1:{port} 에 살아 있음 · 보내지 않음")
        state["standby"] = True
        state["heartbeat"] = now_utc.isoformat()
        return state
    if state.get("standby"):
        log(f"ACTIVE 127.0.0.1:{port} 가 비었음 · 이 지킴이가 맡음")
    state["standby"] = False
    sessions = cfg["sessions"]
    for window, warn_at in (("five_hour", cfg["warn_pct_five_hour"]), ("seven_day", cfg["warn_pct_seven_day"])):
        cur = latest(limits, window)
        if cur is None:
            continue
        key = f"{window}:{cur['reset'].isoformat()}"
        st = state.setdefault(window, {})
        local_reset = cur["reset"].astimezone().strftime("%m/%d %H:%M")
        # 1) 경고: 이 창(reset 시각)에서 처음으로 문턱을 넘을 때 한 번
        if cur["pct"] >= warn_at and st.get("warned_key") != key and now_utc < cur["reset"]:
            msg = WARN_MSG.format(now=now_local(), window=window, pct=cur["pct"], reset=local_reset)
            for name, h in sessions.items():
                send(h, msg, dry)
                state.setdefault("keepalive", {})[name] = now_utc.isoformat()
            st["warned_key"] = key
            st["pending_resume_at"] = cur["reset"].isoformat()
            log(f"WARN {window} pct={cur['pct']} reset={local_reset}")
        # 2) 재개: 경고했던 창의 reset 시각 + 여유가 지나면 한 번
        pr = st.get("pending_resume_at")
        if pr:
            due = dt.datetime.fromisoformat(pr) + dt.timedelta(seconds=cfg["resume_grace_s"])
            if now_utc >= due:
                msg = RESUME_MSG.format(now=now_local(), window=window)
                for name, h in sessions.items():
                    send(h, msg, dry)
                    state.setdefault("keepalive", {})[name] = now_utc.isoformat()
                st["pending_resume_at"] = None
                st["resumed_at"] = now_utc.isoformat()
                log(f"RESUME {window}")
    keepalive(cfg, state, limits, now_utc, dry)
    state["heartbeat"] = now_utc.isoformat()
    return state


KEEP_MSG = "[캐시 유지 {now}] 맥락 캐시를 잇기 위한 신호입니다. 하던 일이 있으면 계속하고, 없으면 「대기」 한 단어로만 답하세요."
BUSY_MARKS = ("esc to interrupt", "tokens · thinking", "tokens)", "Compacting")


def is_busy(handle):
    """창 끝 화면에 진행 중 표시가 있으면 바쁨(바쁜 세션은 스스로 캐시를 잇는다)."""
    try:
        r = subprocess.run([ORCA, "terminal", "read", "--terminal", handle, "--json"],
                           capture_output=True, text=True, encoding="utf-8", timeout=60,
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        tail = "\n".join(json.loads(r.stdout)["result"]["terminal"]["tail"][-12:])
        # 턴이 끝난 창에는 「· done 오전/오후 hh:mm」 줄이 남는다(10/20 실측). 없으면 일하는 중으로 본다.
        return " · done " not in tail and "· done " not in tail
    except Exception:
        return True  # 모르면 건드리지 않는다


def keepalive(cfg, state, limits, now_utc, dry):
    """캐시 수명 1 시간 안에 한 번씩 깨워 맥락 캐시를 잇는다.
    한도에 걸린 창(경고 뒤 reset 전)에는 보내지 않는다(요청이 막혀 캐시도 못 잇고 한도만 쓴다)."""
    period = cfg.get("keepalive_s", 0)
    if not period:
        return
    cur = latest(limits, "five_hour")
    if cur and cur["pct"] >= cfg["warn_pct_five_hour"] and now_utc < cur["reset"]:
        return
    ka = state.setdefault("keepalive", {})
    for name, h in cfg["sessions"].items():
        last = ka.get(name)
        if last and (now_utc - dt.datetime.fromisoformat(last)).total_seconds() < period:
            continue
        if not last:  # 처음 본 세션은 시계만 건다
            ka[name] = now_utc.isoformat()
            continue
        if not dry and is_busy(h):
            ka[name] = now_utc.isoformat()  # 바쁘면 스스로 캐시를 잇는다 → 시계만 다시
            continue
        send(h, KEEP_MSG.format(now=now_local()), dry)
        ka[name] = now_utc.isoformat()
        log(f"KEEPALIVE {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limits", default=str(LIMITS))
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--now", help="UTC ISO 시각 (시험용)")
    ap.add_argument("--config", default=str(CONFIG), help="시험용")
    a = ap.parse_args()
    cfg = load_json(a.config, None)
    if not cfg:
        print("config.json 없음", file=sys.stderr)
        return 2
    log(f"start pid={os.getpid()} once={a.once} dry={a.dry}")
    while True:
        state = load_json(a.state, {})
        now_utc = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
        state = tick(cfg, state, load_json(a.limits, {}), now_utc, a.dry)
        Path(a.state).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        if a.once:
            return 0
        time.sleep(cfg["poll_s"])


if __name__ == "__main__":
    sys.exit(main())
