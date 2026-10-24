상태: 초안 (M1). 시험 40개가 Windows, Linux (WSL과 CI), macOS (CI)에서 통과. 확장은 Windows 의 격리된 Chrome 프로필에서 손으로 한 번 시험했다. 재지 않은 것: 내 실제 큰 프로필, 소리 나는 탭, 시크릿 창, Linux · macOS 의 Chrome.

[English](README.md)

# mai-tabs

브라우저 탭을 한꺼번에 닫기 전에, 열린 탭을 분류된 Markdown 목록으로 남기고, 중복이거나 오래 안 쓴 탭을 보여 주고, 브라우저가 메모리를 얼마나 쓰는지 보여 준다. 제안만 하고 탭을 닫거나 프로세스를 끝내지 않는다.

- 작은 Chrome 확장 (권한은 `tabs`, `tabGroups` 둘뿐) 이 열린 탭을 JSON 파일 하나로 내려받는다. 주소는 브라우저를 떠나기 전에 `?` 뒤와 `#` 뒤를 지우므로, 주소에 든 토큰은 저장되지 않는다.
- Python 명령이 그 파일을 Markdown, 정리 제안, 프로세스 보고로 바꾼다.

## 탭 보관함 (0.2)

열려 있던 탭을 페이지 하나에 한 줄씩 모아 두고, 분류별 · 날짜별로 보고, 버튼으로 PC 의 Chrome 에서 다시 열거나 (하나씩 · 그룹으로 · 잠든 채로) 재우거나 닫는다. 같은 페이지를 여러 번 열었으면 한 항목에 「중복 3 탭」 으로 보이고 한 번에 하나만 남길 수 있다. 재우기 · 닫기 전후로 Chrome 메모리와 GPU 메모리를 재서 실제로 얼마나 줄었는지 보여 준다. 휴대폰에서도 같은 화면과 버튼을 쓴다 (Tailscale 안에서만).

1. 서버: `tools/mai-tabs` 에서 `python -m mai_tabs serve` (화면 127.0.0.1:28766, 확장용 28767, 자료는 `~/.mai/tabs`). 다른 기기에서 보려면 `tailscale serve --bg --https=8443 http://127.0.0.1:28766` 뒤에 `~/.mai/tabs/config.json` 에 내 Tailscale 로그인을 `{"owner_logins": ["you@example.com"]}` 로 적는다. tailnet 의 다른 사람 · 태그 기기는 막힌다
2. 확장: `chrome://extensions` 에서 개발자 모드를 켜고 **압축해제된 확장 프로그램을 로드합니다** 로 `tools/mai-tabs/extension` 을 고른다 (0.1 을 쓰던 사람은 같은 자리에서 새로고침). 도구 모음의 mai-tabs 를 누르면 「몇 초 전에 보냄 · 탭 n」 이 보여야 한다
3. 화면: PC 는 http://127.0.0.1:28766/ , 휴대폰은 Tailscale 주소의 8443 포트

저장하지 않는 것: 로그인 · 메일 · 은행 주소, 로그인 · 비밀번호 재설정 경로, 주소 속 토큰 같은 값 (`?token=` 등). 더 막을 주소는 `~/.mai/tabs/deny.txt` 에 한 줄씩. 페이지 본문은 읽지 않는다 (한 줄 설명은 주소와 제목으로 만든다).

시험: `python -I tests/test_library.py` · `node --test tests/extension.test.cjs` · 실제 Chrome 확인 `node tests/e2e_chrome.mjs` (내 프로필은 건드리지 않는다). 설계: [DESIGN.md](DESIGN.md) 12 절.

## 실습

`tools/mai-tabs` 에서 실행한다.

**브라우저 없이 (1분)**, 스키마에 딸린 예제 파일로:

```powershell
python -m mai_tabs render schema/examples/valid-full.json --out $HOME/tabs-demo.md   # wrote ...tabs-demo.md
python -m mai_tabs propose schema/examples/valid-full.json                 # "Proposal only. Nothing was closed."
python -m mai_tabs verify schema/examples/valid-full.json --expect-tabs 1  # windows 1, tabs 1, groups 1; collection complete
python -m mai_tabs verify schema/examples/valid-full.json --expect-tabs 2  # tab count 1 does not match the expected 2 (종료 코드 2)
python -m mai_tabs procs --name chrome.exe                                 # 브라우저 프로세스를 종류 · 메모리별로 (psutil 필요)
```

**내 브라우저로 (5분)**:

1. `chrome://extensions` 를 열고 **개발자 모드** 를 켠 뒤 **압축해제된 확장 프로그램을 로드합니다** 에서 `tools/mai-tabs/extension` 폴더를 고른다. `mai-tabs 0.1.0` 이 오류 없이 보여야 한다. 다른 권한은 주지 않는다.
2. 도구 모음의 mai-tabs 버튼을 누르고 **Export open tabs** 를 누른다. 팝업에 나온 숫자 (tabs, windows, groups) 와 INCOMPLETE 표시가 있는지를 적어 둔다. 「Download requested」 는 저장이 끝났다는 뜻이 아니다. 다운로드 폴더에 `mai-tabs-<시각>.json` 이 있는지 본다.
3. 파일이 팝업과 맞는지 본다: `python -m mai_tabs verify <파일> --expect-tabs <숫자>`. `collection complete` 를 찍고 종료 코드 0 이어야 한다. 숫자에 1 을 더해 주면 종료 코드 2 여야 한다.
4. `python -m mai_tabs render <파일> --out $HOME/tabs.md` 로 만든 파일을 연다. `python -m mai_tabs propose <파일>` 은 중복과 14일 넘게 안 쓴 탭을 보여 준다. 고정 탭과 소리 나는 탭은 제안하지 않는다.
5. 닫는 것은 직접 한다. 이 목록은 검토용이지 백업이 아니다 (주소를 줄였으므로 닫은 탭을 이 파일로 다시 열 수 없다). 확장을 지우려면 `chrome://extensions` 에서 **삭제** 를 누른다.

분류 규칙은 `mai_tabs/rules.default.json` 이다. 복사해서 고친 뒤 `--rules 내규칙.json` 으로 넘긴다 (`check-rules` 로 검사).

2026-10-18 Windows 에서 확인: 예제 파일로 위 명령을 돌려 적힌 출력이 나왔고, `procs` 는 Chrome 프로세스 197개를 보여 줬다. 브라우저 단계는 독립 검토자가 격리된 프로필에서 확인했다 (탭 10, 창 1, 그룹 1: 팝업 · 파일 · `verify` 일치). 주인의 실제 프로필에서는 아직 안 돌렸다.

설계와 검토 기록: [DESIGN.md](DESIGN.md). 시험: `python -I tests/test_mai_tabs.py` (`jsonschema` 와 Node.js 필요).
