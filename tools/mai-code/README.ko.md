# mai-code

[English](README.md)

> 상태: 초안 알파 0.1.0a1. Windows 실제 CLI 예제 시험과 세 OS 오프라인 CI 를 측정했고, maintainer 검수를 거쳐 main 에 들어왔다. 실제 논문 단위(MARG · START · AME-2)는 아직 재지 않았다.

mai-code 는 소유자가 쓴 작업 단위를 준비하고, **이미 로그인된 공식 Codex 또는 Claude Code** 를 전용 Git worktree 안에서 실행한다. 원본 입력, 요청, 원시 출력 스트림, 엔진 세션 ID, 고정 시험 영수증을 모두 남긴다. 공급자 API 로 우회하지 않고, 자격 증명을 복사하지 않고, 지금 하고 있는 대화를 대신하지 않는다. 원조 DeepCode 제품이 아니다.

## 설치 없이 써 보기

검토된 판의 이 저장소를 받아 `tools/mai-code` 로 들어간 뒤:

```text
python -m mai_code --help
python -m mai_code doctor
python tests/live/native_probe.py --root <비어 있는 예제용 절대 경로> --engine codex
```

마지막 명령은 **표시가 붙은 로컬 시험용 Git 저장소, worktree, 작업 단위, 증거 묶음만** 만든다. `--execute` 없이는 모델을 부르지 않고, 만든 예제를 지우지 않는다. Python 3.11 이상, Git, 고른 공식 CLI 가 이미 설치돼 있어야 한다. doctor 가 구독 로그인을 확인하지 못하면 직접 로그인한다. 키 · 토큰 · 설정 파일 · 로그인은 복사하지 않는다. doctor 는 CLI 의 버전 · 도움말 · 로그인 상태만 묻고 모델 작업은 하지 않는다.

격리된 환경에 설치하고 싶다면 (네트워크로 의존성을 받지 않는다):

```text
python -m venv --system-site-packages <새 venv>
<venv-python> -m pip install --no-index --disable-pip-version-check --no-build-isolation --no-deps .
<venv-mai-code> --help
```

전역에는 설치하지 않는다. 빌드 백엔드가 없으면 멈추고 그 격리 환경에 직접 설치한다. 지울 때는 그 환경의 `python -m pip uninstall mai-code`. `.mai/mai-code` 증거와 엔진 세션 기록은 남는다. 패키지를 지워도 작업과 기록은 지워지지 않는다.

## 실제 논문 단위

lead 가 **정확한 논문 · 발췌 판, 절 · 식 번호, 프로젝트 이슈, 모듈 경계, 소유한 linked worktree, 바꿀 수 없는 시험 정답** 을 정한다. MARG · START · AME-2 는 먼저 원문을 분석하고, 약어만 보고 논문을 짐작하거나 방법을 재현했다고 주장하지 않는다. 예제 생성기는 형식 예시로만 쓰고, 그 TEST ONLY 원문 · 계약을 승인된 발췌로 바꾼 뒤 파일마다 SHA-256 을 계산해서 준비한다. 과학적 합격 기준은 모두 `contract` 에 넣는다. 필수 칸은 `module`, `negative_test_id`, 양의 정수 `negative_failures` 다.

작업 단위 형식은 `mai-code-unit-v1` 이고 칸은 정확히 이것뿐이다: `schema`, `unit_id`, `issue_url`, 절대 경로 `workspace`, 비어 있지 않은 `inputs` (`path`, 소문자 SHA-256, 비어 있지 않은 `references`), `contract`, `outputs`, `engines`, `test_argv`, `test_framework` (`unittest`), `negative_control_argv`. `engines` 는 analyze · plan · implement 마다 `engine` (codex/claude) 과 선택 `model` 을 준다. `outputs` 의 첫 두 칸은 새 분석 · 계획 JSON 경로, 나머지는 구현 파일이다. 모두 linked worktree 기준 상대 경로다. 시험 정답 파일을 쓰기 대상에 넣지 않는다. 모르는 칸, 커밋 안 된 변경이 있거나 공유된 체크아웃, 밖으로 나가거나 다른 OS 표기인 경로는 거부한다.

```text
mai-code prepare <unit.json>
mai-code status <알려 준 실행 경로>
mai-code run <알려 준 실행 경로> --through analyze
mai-code run <알려 준 실행 경로> --through plan
mai-code run <알려 준 실행 경로>
mai-code verify <알려 준 실행 경로> --existing
```

`--through analyze` 는 lead 가 구조를 검토하는 경로이고, 모듈을 구현하지 않는다. prepare 와 status 는 모델을 부르지 않는다. 분석 · 계획 단계의 모델은 작업 폴더 파일을 고치면 안 되고, 검증된 JSON 은 mai-code 가 저장한다. 마지막 run 은 선언한 출력 경로만 구현하고, 모델이 쓴 셸 명령이 아니라 **소유자가 정한 argv** 로 시험한다. 시험은 셸 확장도, 의존성 설치도 없이 돈다. 종료 코드만으로는 부족하다. unittest 가 시험을 하나 이상 찾아야 하고, 선언한 음성 대조 시험이 기대한 만큼 실패해야 하며, 예상 밖 오류는 0 이어야 한다.

## 실패와 이어 가기

종료 코드: 0 요청한 동작 성공, 1 결정적 검증 실패, 2 잘못됐거나 거부됐거나 끝나지 않은 동작. 준비만 했거나 분석만 한 단위는 구현을 통과한 것이 **아니다**. 단독 검증기가 시험을 통과해도 끝나지 않은 단계가 통과로 바뀌지는 않는다.

평범하게 멈춘 경계에서는 `mai-code run` 또는 `mai-code resume`. 실패하고 닫힌 시도는, 기록된 엔진 UUID 가 정확하고 입력 · 작업 폴더가 그대로이며 프로세스 종료가 확인됐을 때만 `resume` 할 수 있다. 전역 `--last`, `--continue`, 엔진 바꾸기, 자동 재시도는 없다. 영수증이 없거나 잠금(lease)의 주인을 모르면 사람이 정리한다. PID 가 죽었을 거라고 짐작해서 남은 잠금을 지우지 않는다. 하위 프로세스가 아직 돌 수 있는 동안 잠금을 지우지 않는다. 입력이나 합격 기준이 바뀌면 원래 실행은 그대로 두고 새로 승인된 단위를 만든다.

작업 폴더 잠금은 실제 worktree 폴더 옆 `.mai-code-locks` 에 정규화된 절대 경로를 키로 둔다. 그래서 `--data-root` 가 달라도 같은 잠금을 쓴다. 그 상위 폴더는 쓸 수 있어야 하고, 링크된 잠금 폴더는 거부한다. 증거 폴더에 있는 옛 형식 잠금도 실행을 막으며 자동으로 옮기거나 지우지 않는다. 같은 worktree 에서 새 판을 쓰기 전에 옛 판 작업자를 모두 멈춘다. 영수증 해시를 고정하지 않은 옛 판의 실패 시도는 손으로 정리해야 한다.

검증을 다시 시작하면 시험을 띄우기 전에 이전 성공부터 무효로 만든다. 중단되거나 실패한 실행은 그 성공을 재사용하지 못하고, 이전 영수증은 디스크에 남는다. 하위 프로세스 생존을 모르면 작업 폴더 잠금을 유지한다. 끝나지 않은 시도는 직접 확인하고 정리한다. Git 서브모듈(gitlink)이 있는 worktree 는 이 판의 목록 검사가 그 안을 보지 못해서 거부한다.

Claude 의 권한 층이 구현 쓰기를 거부하면, 소유자가 그 실행에 대해 선언된 파일 하나만 명시적으로 허가할 수 있다: `mai-code resume <실행 경로> --allow-write module.py`. 허가할 출력마다 플래그를 반복한다. 와일드카드, 경로 이탈, 입력, 분석 · 계획 출력, 선언 안 된 경로는 받지 않는다. 이것은 전역 설정이나 우회 모드가 아니라 엔진의 `Edit(정확한 경로)` 규칙 하나를 만든다 (Claude 는 Write 에도 이 규칙을 쓴다). Windows 에서는 공식 권한 규칙대로 드라이브를 `/c/...` 로 바꾼다. 기존 deny · ask 규칙은 여전히 거부할 수 있다. 엔진이 거부한 쓰기를 셸 쓰기로 대신하지 않는다.

호출이 주의 기준 시간을 넘으면 `attempts/<id>/lifecycle.jsonl` 에 살아 있는 PID 와 주의 사건을 적고, 두 스트림은 계속 받는다. 이것은 **취소도 완료도 아니다**. `status` 가 현재 시도를 보여 준다. 엔진 권한은 특히 비대화 모드에서 쓰기를 거부할 수 있다. 거부를 성공으로 바꾸려고 권한이나 훅을 끄지 않는다.

## 단계별 권한

새 호출과 정확한 ID 로 이어 가는 호출이 같은 명시 정책을 쓴다. 최종 argv 는 시도마다 `command.json` 에 남는다.

| 엔진 | 분석 · 계획 | 구현 |
|---|---|---|
| Codex | `--sandbox read-only` | `--sandbox workspace-write`, 작업 디렉터리는 소유한 worktree |
| Claude | `--permission-mode default --tools Read,Glob,Grep` | 기본 권한 모드, `Read,Glob,Grep,Edit,Write`. 소유자가 `--allow-write` 로 지정한 경로만 엔진의 Edit 허가가 된다 |

Codex 는 `approval_policy="never"` 를 고정하고 `--ignore-user-config` 와 `--ignore-rules` 를 쓰며, sandbox 옵션을 `resume` 앞에 둔다. Claude 는 `--restricted` 로 사용자 · 프로젝트 · 로컬 설정을 빼고, `--strict-mcp-config` 와 `--disallowedTools mcp__*` 로 MCP 도구를 빼며, `--permission-prompts none` 으로 풀리지 않은 권한 요청을 거부한다. 어느 단계에서도 Claude 에게 셸 도구를 주지 않는다. 필요한 옵션이 없으면 doctor 와 실행 모두 `missing-capability:<옵션>` 으로 거부하고, 느슨하게 대신 도는 길은 없다.

하위 실행은 개인 CLI 설정과 훅을 일부러 **물려받지 않는다**. 인증 폴더, 설치된 설정, 돌고 있는 세션은 고치지 않는다. 관리자가 정한 호스트 정책은 그대로 믿는다. 이 도구가 엔진 자체의 통제를 대신하지는 않으며, Codex 의 workspace-write 는 파일 하나 단위 샌드박스가 아니라서 실행 뒤 출력 목록 검사로 선언된 출력을 다시 확인한다. 모든 사용자 · 관리자 설정이 이 통제를 좁히기만 한다고 주장하지 않고, 새 정책이 실제 모델을 상대로 한 공격 시험을 통과했다고도 주장하지 않는다. 측정한 것: 단계별 argv, 옵션을 뺐을 때 실패하는 회귀 시험, 기능 없음일 때 doctor 종료, Codex 0.163.0 · Claude Code 2.1.302 에서 모델 없이 한 파서 수용. 그 전의 실제 CLI 예제 결과는 이 강화 이전 것이다.

2026-10-18 에 확인한 참고: [Codex CLI reference](https://developers.openai.com/codex/cli/reference/), [Claude CLI reference](https://code.claude.com/docs/en/cli-reference), [Claude permissions](https://code.claude.com/docs/en/permissions).

## 한계

- 모델 · 계정 바꾸기, 한도 우회, 예약 깨우기, 자동 수리, GPU 학습, 패키지 내려받기, Git commit · merge · push, 프로세스 종료, 배포는 하지 않는다.
- USD 를 계산하지 않는다. 엔진이 준 사용량과 USD 만 남긴다.
- 엔진 자체 compact 는 여전히 일어날 수 있다. 원시 기록을 남겨도 모든 과거 토큰이 모델 맥락에 들어가는 것은 아니다.
- 파일 해시는 호출 뒤 계약 위반을 잡을 뿐, 샌드박스 · 서명 · 승인 · 같은 OS 사용자에 대한 방어가 아니다. 엔진의 권한 통제는 그대로 적용된다.
- 비공개 논문 발췌와 원시 기록은 기본으로 Git 밖에 둔다. 공유하기 전에 확인한다. 예시의 실행 ID 와 경로는 자리 표시다.
- 측정은 [DESIGN.md](DESIGN.md), 출처는 [THIRD_PARTY.md](THIRD_PARTY.md). 초안은 엔진 · 플랫폼 관문이 다 끝나지 않았다는 뜻이고, 과학적 결과를 보증한다는 뜻이 아니다.
