상태: 초안 (M1). 시험 43 + 2개가 Windows, Linux (WSL과 CI), macOS (CI)에서 통과. 실제 실행기 안에서 쓴 것은 아직 재지 않았다.

[English](README.md)

# mai-approve

주인이 한 번 써 두는 기한 있는 상시 승인이다. 무인 실행이 「이걸 시작해도 되나」를 누구도 깨우지 않고 물어볼 수 있게 한다.

- 주인이 `grant` 로 정한다: 어느 폴더, 어느 장치, 실험 단위마다 몇 번, 언제까지. 파일은 SHA-256 해시로 봉인된다.
- 실행기는 실행 직전에 `receipt` 를 부른다. 승인이 없거나, 기한이 지났거나, 철회됐거나, 다른 폴더거나, 제외된 행동이거나, 그 단위의 횟수를 다 썼으면 거부된다. 실행 id 를 새로 붙여도 횟수는 초기화되지 않는다.
- 모든 변경은 해시로 이어진 감사 기록에 덧붙는다.

조율과 기록을 위한 도구이지 보안 경계가 아니다. 같은 OS 사용자로 도는 프로세스는 같은 파일을 쓸 수 있다.

## 5분 실습

진짜 승인은 건드리지 않도록 버리는 저장 폴더를 쓴다. `tools/mai-approve` 에서 실행한다. 아래는 PowerShell 이고, Linux · macOS 에서는 `export MAI_APPROVE_DIR=...` 과 `/` 경로를 쓴다.

```powershell
$env:MAI_APPROVE_DIR = "$HOME\mai-approve-demo\store"
mkdir "$HOME\mai-approve-demo\lab\runs" -Force | Out-Null
$lab = "$HOME\mai-approve-demo\lab"

# 1. 주인이 하루짜리 승인을 쓴다: 실험 단위마다 1회, 무인 실행 허용
python -m mai_approve grant --scope demo --days 1 --allowed-path $lab --runs-per-unit 1 --unattended `
  --eula-accept --eula-license "Example License" --eula-subject owner --eula-source "typed by the owner"

# 2. 실행기가 시작 전에 묻는다: 허용 (종료 코드 0)
python -m mai_approve receipt --scope demo --unattended --path "$lab\runs" --experiment-unit exp-1 --attempt-kind normal --run-id run-1

# 3. 같은 단위를 새 실행 id 로 다시: 거부, "runs_exhausted" (종료 코드 2)
python -m mai_approve receipt --scope demo --unattended --path "$lab\runs" --experiment-unit exp-1 --attempt-kind normal --run-id run-2

# 4. 승인 밖의 폴더: 거부, "path" (종료 코드 2)
python -m mai_approve check --scope demo --path $HOME --experiment-unit exp-1

# 5. 제외된 행동: 거부, "excluded" (종료 코드 2)
python -m mai_approve check --scope demo --path "$lab\runs" --experiment-unit exp-1 --action data_deletion

# 6. 실행을 닫고, 감사 기록을 검사하고, 철회한다
python -m mai_approve finish --scope demo --run-id run-1 --status ended
python -m mai_approve audit-verify
python -m mai_approve revoke --scope demo
```

보여야 하는 것 (2026-10-18 Windows 에서 위 명령을 그대로 실행해 확인): 1번은 `"ok": true` 와 하루 뒤의 `valid_until`, 파일 경로. 2번은 `"ok": true`. 3 ~ 5번은 `mai-approve refused (...)` 한 줄과 종료 코드 2. `audit-verify` 는 `"ok": true` 와 줄 수. `revoke` 뒤에는 `check --inquiry` 가 `missing` 이라고 답한다. 끝나면 `$HOME\mai-approve-demo` 를 지운다.

## 명령

| 명령 | 누가 | 무엇 |
|---|---|---|
| `grant` | 주인 | 승인을 쓴다 (`--until` 또는 `--days`, 최대 31일. 제외 행동 여섯 가지가 기본으로 켜짐) |
| `extend`, `revoke`, `show` | 주인 | 기한 변경, 즉시 종료, 내용 보기 |
| `check` | 누구나 | 기록 없이 묻기. `--inquiry` 는 승인이 살아 있는지만 묻는다 |
| `receipt` | 실행기 | 묻고 그 실행을 기록한다. 실행기가 써야 하는 관문은 이것이다 |
| `finish` | 실행기 | 실행이 어떻게 끝났는지 기록 |
| `audit-verify`, `audit-head` | 주인 | 해시 고리 검사. 머리값을 다른 곳에 적어 두면 끝부분이 잘린 것도 잡는다 |

기본 저장 위치: `~/.mai/approvals`, 또는 `MAI_APPROVE_DIR` 의 폴더. 종료 코드 0 은 허용, 2 는 거부 (이유는 표준 출력의 JSON).

## 알아 둘 규칙

- 경로는 링크와 정션을 풀어서 비교한다. 한 OS 에서 쓴 승인은 다른 OS 에서 거부된다 (`foreign_path_notation`). 새 기기에서는 다시 승인한다.
- 행동 여섯 가지는 주인이 빼지 않는 한 늘 제외된다: 유료 · 외부 자원, 데이터 삭제, 남의 프로세스 종료, 시스템 · 보안 설정, 외부 발송, 범위 밖 실험.

설계와 검토 기록: [DESIGN.md](DESIGN.md). 시험: `python -I tests/test_cli.py`, `tests/test_hardening.py`, `tests/test_schema_contract.py` (`jsonschema` 필요).
