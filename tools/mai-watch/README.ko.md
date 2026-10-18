상태: 초안 (M2 · 실시간 화면 · 자원 확장). Windows 에서 시험 142개 통과 (72 + 12 + 25 + 16 + 10 + 7). 앞선 72 + 7개는 Linux (WSL 과 CI), macOS (CI) 에서도 통과. 실제 `nvidia-smi` · 디스크 · 네트워크 · 사용량은 Windows 11 한 대에서 읽었다. 재지 않은 것: 실제 학습 · 렌더 중 장시간 운영 (M3), 알림, GPU 있는 macOS, Linux · macOS 에서 세션 사용량 파일의 경로.

[English](README.md)

# mai-watch

기기 한 대를 보는 읽기 전용 감시 도구다. 화면 맨 위에 「확인할 것」 이 나온다 (예: 거의 찬 드라이브, 느린 네트워크 연결, 메모리만 잡고 일하지 않는 GPU). 줄마다 잰 숫자로 판정한다. 그 아래에 실시간으로 보여 준다.

- CPU (코어마다), RAM 과 스왑
- GPU 마다: 사용률, VRAM, 온도, 전력과 한도, SM 클럭과 최대 클럭, 클럭이 제한되고 있는지와 그 이유
- 지켜볼 폴더: 남은 공간, 찬 정도, 응답 여부 (로컬 드라이브, NAS 공유 폴더)
- 네트워크 카드와 디스크: 지금 데이터가 얼마나 빨리 오가는지
- AI 코딩 세션: Claude Code · Codex 요금제 한도, 세션마다 오늘의 턴 · 비용 · 토큰

같은 「확인할 것」 목록을 http://127.0.0.1:28765/status.json 에서 판정 근거 숫자와 함께 준다. 스크립트와 AI 에이전트가 읽는 자리다.

작업 기록도 남긴다: 살아 있는 작업은 무엇이고, GPU 가 언제부터 놀고 있나. 아무것도 시작 · 중지 · 변경하지 않는다.

## 시작

```
pip install ./tools/mai-watch      # mai-tools 폴더에서. psutil 도 함께 설치된다
mai-watch
```

브라우저에 http://127.0.0.1:28765/ 가 열린다. Ctrl+C 로 끈다. 설치하지 않고 `tools/mai-watch` 에서 `python -m mai_watch` 로 실행해도 같다 (이때 CPU · RAM · 디스크 · 네트워크는 `pip install psutil` 이 필요하다).

자주 쓰는 옵션: `--path //nas/share` (지켜볼 폴더, 여러 번 가능), `--port 28766`, `--interval 2` (2초마다), `--history 1800` (30분 보관), `--no-browser`, `--no-usage`.

읽는 법:

- 원천이 주지 못한 값은 0 이 아니라 `unknown` 이다. 속도는 두 번 재야 나오므로 켠 직후 첫 값은 unknown 이다.
- `clocks low: no work` 는 할 일이 없어 클럭이 낮다는 뜻이다. `clock limited by sw_power_cap` (또는 온도 사유) 는 일하는 중인데 붙잡혀 있다는 뜻이다.
- 남은 공간은 GiB 를 먼저 보여 준다. 99.9% 사용이어도 7 GiB 일 수도, 7 TiB 일 수도 있다.
- 네트워크 카드는 하나씩 보여 주고 더하지 않는다. VPN 카드를 지나는 트래픽은 실제 카드도 지나므로 더하면 두 번 센다.
- 표본이 빈 구간에서는 그래프 선을 끊는다. 재지 않은 시간이 일정한 값처럼 보이지 않게 하려는 것이다.
- 요금제 한도 % 는 실시간 측정이 아니다. 세션이 턴을 주고받을 때 계기판이 기록한 마지막 값이고, 화면에 그 기록의 나이를 적는다.
- 디스크는 모델명과 드라이브 문자로 보여 준다. 아무것도 보여 줄 게 없는 줄 (쉬는 디스크, 가상 네트워크 카드, 조용한 세션) 은 접어 둔다.

RTX 5080 두 장의 Windows 11 에서 잰 것: 화면 값이 `nvidia-smi` 와 맞았다. `nvidia-smi` 한 번에 약 0.08초. 응답하지 않는 NAS 주소는 Windows 가 실패를 알리기까지 21초가 걸렸고, 화면은 3초 만에 `no answer` 로 표시하면서 나머지는 계속 갱신했다.

## AI 에이전트와 스크립트용

```
mai-watch status          # 지금 확인할 것을 한 줄씩. 종료 코드 0 경고 없음, 1 경고 있음, 2 mai-watch 에 닿지 못함
mai-watch status --json   # 줄마다 판정 근거 숫자가 붙은 전체 목록
```

긴 작업을 주기적으로 점검하는 에이전트는 nvidia-smi · df 등을 따로 부르는 대신 이것 하나를 묻고, 화면과 같은 판정을 받는다. 종료 코드 2 는 mai-watch 가 꺼져 있다는 뜻이지 「모두 정상」 이 아니다.

## 알림

```
mai-watch --notify-cmd "python send.py" [--notify-file outbox.txt] [--notify-level warn] [--notify-hold 60]
```

mai-watch 는 메시지용 토큰을 갖지 않는다. 메시지를 지정한 명령에 넘길 뿐이다: 표준 입력으로 주고, `--notify-file` 을 주면 먼저 그 파일에도 쓴다. 판정은 `--notify-hold` 초(기본 60) 동안 이어져야 알린다 (한 번 튄 값은 소식이 아니다). 더 나빠지면 다시 알리고, 그만큼 사라져 있으면 「풀림」 으로 알린다. 한 번 점검에서 바뀐 것은 메시지 하나로 묶고, 그대로 머무는 동안은 되풀이하지 않는다. 마지막 발송 결과는 `/status.json` 의 `notify` 에 남아, 발송이 계속 실패하면 보인다. 설정 파일에서는 `notify_cmd` · `notify_file` · `notify_level` · `notify_hold_s` 로 같은 것을 정한다.

기준 기기에서 기존 텔레그램 발송기로 잰 것 (`--notify-file` 은 그 발송기의 outbox, `--notify-cmd` 는 그 PowerShell 스크립트): 지금 판정 넷을 담은 메시지 하나, 발송기 결과 `exit 0: sent ok=True`.

## AI 세션 사용량

이 저장소의 세션 계기판 ([mai-gauge](../../mods/mai-gauge), [mai-codex-gauge](../../mods/mai-codex-gauge)) 이 `~/.mai` (또는 `$MAI_HOME`, `--mai-home`) 에 기록하는 것을 읽는다. 계기판은 이미 로그인한 CLI 에서 한도 정보를 받으므로 따로 넣을 키가 없다.

mai-watch 는 그 폴더의 `limits.json`, `sessions/`, `costlog/` 만, 그리고 실제 경로가 그 폴더 안에 있는 파일만 읽는다. 다른 곳(예: `~/.codex/auth.json`)으로 이어지는 링크나 정션, 하드 링크된 파일은 거부하고 화면에 이름을 적는다. 보여 주는 것은 칸마다 다시 만든 값이다: 세션 이름과 그 세션이 스스로 적은 「하는 일」 한 줄, 숫자, 개수와 합계. 프롬프트 글과 형식이 맞지 않는 값은 버린다. 토큰이나 비용 값이 없으면 0 이 아니라 unknown 이고, 일부 턴만으로 낸 합계는 몇 턴을 덮는지 적는다. 비용은 계기판이 계산한 API 가격 추정이지 청구액이 아니다. 계기판이 없으면 화면에 「사용량 원천 없음」 으로 나온다.

## 작업과 놀고 있음 기록

작업은 가끔 작은 상태 파일 (`status/*.json`) 을 쓴다. 연결은 이것 하나뿐이다. 수집기가 `nvidia-smi` 와 그 파일들을 읽어 `snapshot.json`, `events.jsonl`, 심장박동 파일을 쓴다. `check` 는 손봐야 할 것이 있으면 종료 코드 1 을 낸다 (작업이 갱신을 멈춤, 원천이 깨짐, 수집기 자체가 멈춤).

해 보기:

```
mai-watch demo
```

`~/mai-watch-demo` (또는 지정한 폴더) 에 설정과 `running` 이라고 보고하는 예시 작업 하나를 만들고, 실시간 화면 아래에 작업 표가 붙은 화면을 연다. 예시 작업은 스스로 갱신하지 않으므로 심장박동을 세 번 놓치면 (3분) `stale` 로 바뀐다. 경보가 동작하는 모습이다. `mai-watch check --config ~/mai-watch-demo/mai-watch.toml` 도 같은 것을 찍고 종료 코드 1 을 낸다 (PowerShell 에서도 `~` 가 된다). demo 는 새 폴더, 빈 폴더, 자기가 만든 폴더에만 쓰므로 실제 설정은 건드리지 않는다. 끝나면 폴더를 지운다.

실제로 쓸 때: `mai-watch init <폴더>` 로 만들고, 작업이 그 `status` 폴더에 쓰게 한 뒤 `mai-watch live --config <폴더>/mai-watch.toml` 로 띄운다. 설정의 `watch_paths = ["D:/runs", "//nas/share"]` 로 지켜볼 폴더를 정한다.

## 상태 파일 (작업이 쓰는 것)

| 칸 | 뜻 |
|---|---|
| `schema_version` | `1` |
| `id`, `kind` | 작업 이름. `job` 또는 `service` |
| `state` | `running`, `waiting`, `blocked`, `done`, `failed`. `waiting` 과 `blocked` 는 `hold_reason` 이 필요 |
| `updated_at` | 이번에 쓴 UTC 시각. `heartbeat_interval_s` 를 세 번 놓치면 멈춘 것으로 본다 |
| `device_uuids` | 쓰는 GPU (`nvidia-smi -L` 에서). 비워도 된다 |
| 선택 | `started_at`, `progress {done, total}`, `deadline`, `artifacts` (바뀐 시각이 실제 진척을 보여 주는 파일), `labels` |

전체 계약: `schema/status.v1.schema.json`. 파일 검사: `mai-watch validate <파일>`.

## 명령

`mai-watch` (`live` 와 같음) · `demo [폴더]` · `status [--json]` · `init <폴더>` · `collect [--once]` · `check` (경보가 있으면 종료 코드 1) · `show` (스냅샷 전체를 JSON 으로) · `serve` (따로 도는 수집기용 화면) · `validate <파일>`. 모두 127.0.0.1 에서만 연다.

설계 · 놀고 있음 판정 규칙 · 검토 기록: [DESIGN.md](DESIGN.md). 시험: `python -I tests/test_mai_watch.py`, `tests/test_live.py`, `tests/test_resources.py`, `tests/test_judge.py`, `tests/test_notify.py`, `tests/test_schema_contract.py` (`jsonschema` 필요, 화면 시험은 Node.js 필요).
