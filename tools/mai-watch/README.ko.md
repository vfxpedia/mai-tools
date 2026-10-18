상태: 초안 (M2). 시험 72 + 7개가 Windows, Linux (WSL과 CI), macOS (CI)에서 통과. Windows 와 WSL 에서 실제 `nvidia-smi` 를 읽었다. 재지 않은 것: 실제 학습 · 렌더 중 장시간 운영 (M3), 알림, GPU 있는 macOS.

[English](README.md)

# mai-watch

읽기 전용 감시 도구다. 세 가지를 한눈에 답한다: GPU 마다 얼마나 쓰고 있나, 내 작업 중 살아 있는 것은 무엇인가, GPU 가 언제부터 놀고 있나.

- 작업은 가끔 작은 상태 파일 (`status/*.json`) 을 쓴다. 연결은 이것 하나뿐이다.
- 수집기가 `nvidia-smi` 와 그 파일들을 읽어 `snapshot.json`, `events.jsonl`, 심장박동 파일을 쓴다.
- `check` 는 손봐야 할 것이 있으면 종료 코드 1 을 낸다 (작업이 갱신을 멈춤, 원천이 깨짐, 수집기 자체가 멈춤). 로컬 웹 화면도 같은 것을 보여 준다.

아무것도 시작 · 중지 · 변경하지 않는다.

## 5분 실습

`tools/mai-watch` 에서 실행한다. 아래는 PowerShell 이고, Linux · macOS 에서는 `/` 경로로 같은 명령을 쓴다.

```powershell
# 1. 설정 파일이 든 폴더
python -m mai_watch init "$HOME\mai-watch-demo"

# 2. 지금 "running" 이라고 보고하는 가짜 작업
mkdir "$HOME\mai-watch-demo\status" -Force | Out-Null
$now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$job = '{"schema_version":1,"id":"my-first-job","kind":"job","state":"running","updated_at":"' + $now + '","heartbeat_interval_s":60,"device_uuids":[]}'
[IO.File]::WriteAllText("$HOME\mai-watch-demo\status\my-first-job.json", $job)

# 3. 한 번 수집하고, 잘못된 것이 있는지 묻는다
$cfg = "$HOME\mai-watch-demo\mai-watch.toml"
python -m mai_watch collect --config $cfg --once
python -m mai_watch check --config $cfg

# 4. 화면: 브라우저로 http://127.0.0.1:28765/ 를 연다. 끝낼 때는 Ctrl+C
python -m mai_watch serve --config $cfg
```

보여야 하는 것 (2026-10-18 GPU 두 장인 Windows 에서 위 명령을 그대로 실행해 확인): `check` 가 `"ok": true`, `"alerts": []` 를 찍고 종료 코드 0. 화면에는 GPU 마다 사용률 · 메모리 · 온도 · 전력, 그리고 작업 `my-first-job` 이 `running`, `alive` 로 나온다.

경보가 실제로 울리는지 보는 법: 같은 파일의 `updated_at` 을 한 시간 전으로 써서 `collect --once` 를 다시 돌리면, `check` 가 `my-first-job` 의 `workload_stale` 을 찍고 종료 코드 1 을 낸다.

실제로 쓸 때는 `collect` 를 `--once` 없이 돌리고 (기본 10초마다) `serve` 를 켜 둔다. NVIDIA GPU 가 없으면 GPU 목록은 0 이 아니라 「읽을 수 없음」 으로 보고된다. 끝나면 `$HOME\mai-watch-demo` 를 지운다.

## 상태 파일 (작업이 쓰는 것)

| 칸 | 뜻 |
|---|---|
| `schema_version` | `1` |
| `id`, `kind` | 작업 이름. `job` 또는 `service` |
| `state` | `running`, `waiting`, `blocked`, `done`, `failed`. `waiting` 과 `blocked` 는 `hold_reason` 이 필요 |
| `updated_at` | 이번에 쓴 UTC 시각. `heartbeat_interval_s` 를 세 번 놓치면 멈춘 것으로 본다 |
| `device_uuids` | 쓰는 GPU (`nvidia-smi -L` 에서). 비워도 된다 |
| 선택 | `started_at`, `progress {done, total}`, `deadline`, `artifacts` (바뀐 시각이 실제 진척을 보여 주는 파일), `labels` |

전체 계약: `schema/status.v1.schema.json`. 파일 하나 검사: `python -m mai_watch validate <파일>`.

## 명령

`init <폴더>` · `collect [--once]` · `check` (경보가 있으면 종료 코드 1) · `show` (스냅샷 전체를 JSON 으로) · `serve` (127.0.0.1:28765, 이 PC 에서만) · `validate <파일>`.

설계 · 놀고 있음 판정 규칙 · 검토 기록: [DESIGN.md](DESIGN.md). 시험: `python -I tests/test_mai_watch.py`, `tests/test_schema_contract.py` (`jsonschema` 필요, 화면 시험은 Node.js 필요).
