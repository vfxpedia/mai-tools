# mai-tools

[English](README.md)

오래 걸리는 무인 AI · GPU 작업을 돌리는 사람이 「무엇이 언제 돌았고, 지금도 살아 있는가」 를 믿을 수 있게 하는 작은 범용 도구들이다.

도구마다 만든 사람이 자기 기기에서 필요해서 만들었고, 실측으로 확인한 뒤 누구나 쓸 수 있게 일반화했다. 원칙은 [PRINCIPLES.md](PRINCIPLES.md): **나로부터 시작하고, 증거로 검증하고, 모두를 위해 일반화한다.**

| 도구 | 하는 일 | 상태 |
|---|---|---|
| [mai-code](tools/mai-code/README.ko.md) | 이미 로그인된 공식 CLI 로 논문을 분석하고 경계가 정해진 모듈을 구현. 증거를 남기고 고정 시험으로 확인 | 초안 알파 0.1.0a1, maintainer 검수 뒤 병합. 실제 논문 단위는 미측정 |
| [mai-approve](tools/mai-approve/README.ko.md) | 무인 실행을 위한 기한 있는 상시 승인: 해시로 봉인한 승인 파일, 실행마다 영수증, 실행 id 를 바꿔도 초기화되지 않는 횟수, 변조를 드러내는 감사 기록 | M1, 검토 받음 |
| [mai-watch](tools/mai-watch/README.ko.md) | GPU 사용과 작업 상태를 읽기만 하는 감시: 수집기, 「모름」 을 따로 다루는 놀고 있음 판정, 생존 확인, 사건 기록, 로컬 화면 | M2, 검토 받음 |
| [mai-tabs](tools/mai-tabs/README.ko.md) | 탭 정리 전에 열린 탭을 분류된 Markdown 으로 남기고 닫을 후보를 제안. 아무것도 닫지 않는다 | M1, 격리 프로필에서 한 번 확인 |
| [mai-resume](tools/mai-resume/README.ko.md) | Orca 의 AI 코딩 세션에 사용 한도가 차기 직전 마무리를 알리고, 풀리면 다시 깨우고, 쉬는 세션의 맥락 캐시를 잇는다. 하나만 돌고, 글이 들어 있는 입력창에는 치지 않는다 | M1, Windows 한 대 실제 창으로 확인 |

세션 Mods 는 [mods/](mods/) 에 있다: Claude Code 용 **mai-gauge** (`/plugin marketplace add vfxpedia/mai-tools` 다음 `/plugin install mai-gauge@mai-mods`) 와 Codex 용 **mai-codex-gauge**.

## 여기서 시작

도구마다 README 에 **5분 실습** 이 있다. 적힌 명령은 그대로 실행해 본 것이고, 나온 출력을 함께 적었다. 각 도구 링크를 따라가면 된다.

## 이름 규칙

| 자리 | 규칙 | 예 |
|---|---|---|
| 도구 · 폴더 · 명령 이름 · 문서 | `mai-<도구>` | `mai-watch` |
| Python 패키지 (`python -m ...`) | `mai_<도구>` (Python 은 하이픈을 import 하지 못한다) | `mai_watch` |
| 스키마 이름 | `mai-<도구>-<문서>-v<N>` | `mai-watch-snapshot-v1`, `mai-approve-approval-v1` |

도구마다 폴더 · 시험 · 문서 · 버전을 따로 갖고 다른 도구를 import 하지 않는다. 그래서 어느 도구든 나중에 자기 저장소로 그대로 떼어 낼 수 있다.

## 「검증했다」 의 뜻

시험이 통과했다고 끝났다고 하지 않는다. [docs/VERIFICATION.md](docs/VERIFICATION.md) 에 배포 가능하다고 부르기 전의 관문이 있고, [docs/PLATFORMS.md](docs/PLATFORMS.md) 에 OS 별로 실제로 돌린 것이 있다. 재지 않은 것은 재지 않았다고 적는다.

## 전체 실행

```
pip install -r requirements-dev.txt
python common/hygiene_check.py        # 개인 경로 · 주소 · 기기 이름 · 비밀 값이 없는지
python common/run_all_tests.py        # 모든 시험 파일을 각각 격리된 인터프리터로
```

라이선스: [LICENSE](LICENSE).
