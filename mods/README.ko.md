> 분류: 가이드
> 작성: 오흥재 (super 세션 정리) · 2026-10-09 01:30
> 근거: 실측 (mai-gauge 0.4.2 · test 세션 · 시험 41/41)
> 요지: mai-mods 를 어느 기기 · 어느 프로젝트에서든 깔고 쓰는 법과 지키는 약속
> 상태: 확정 (1.0 · 띠 모양 팀장 컨펌 2026-10-09)

# mai-mods

어느 프로젝트에서든 Claude Code 세션을 지켜보지 않아도 맡겨 둘 수 있게 하는 모드 묶음이다. 지금은 `mai-gauge` 하나다. 특정 프로젝트 · 기기 · 사람에 묶인 것이 없다.

## 설치

새 기기나 다른 사람 (저장소 읽기 권한이 있으면):

```
/plugin marketplace add vfxpedia/mai-os
/plugin install mai-gauge@mai-mods
```

이 저장소를 고치며 쓰는 기기 (고친 것이 `/reload-plugins` 한 번으로 바로 들어온다):

```
/plugin marketplace add <이 저장소를 받은 자리>/mods
/plugin install mai-gauge@mai-mods
```

깐 뒤 떠 있는 세션에는 `/reload-plugins` 를 친다. 프로세스를 끌 필요는 없다.

## mai-gauge 가 하는 일

| 무엇 | 어디에 보이나 |
|---|---|
| 띠: `context` (막대 · % · 토큰 · 정리까지 몇 턴) · `5 hours` · `7 days` (쓴 % · [리셋 때 예상] · 판정 · 리셋까지) · `turn` (이번 턴 비용 · [세션 합계] · 요청 수 · 어디에 썼나) · 알릴 것이 있으면 `now` (저장소 밖 경고 · 지금 도구 · 진행). 모든 줄이 같은 세로선 | 프롬프트 위. 56칸 미만이면 막대를 빼고, turn 내역은 가장 싼 것부터 뺀다 |
| 컨텍스트가 자동 compact 문턱의 몇 % 인지 | 프롬프트 위 띠 첫 줄, `/gauge` |
| 한도 예측: 모든 세션의 턴 비용으로 「1달러 = 몇 %」 를 배우고 최근 쓴 돈(5시간 15분 · 7일 3시간)에 곱한다. 근거가 모자라면 % 기울기, 그다음 창 평균. 모델을 부르지 않아 비용 0 | 띠 판정, `/gauge` 에 근거 |
| 이번 턴의 요청 수 · 입력 · 출력 · 비용 | 띠 둘째 줄 |
| 50 · 75 · 85 % 알림. 85 % 를 넘으면 턴이 끝난 자리에서 직접 compact (작업 도중에는 안 함) | 알림 |
| compact 요약에 지금 작업 단위의 사실(커밋 · 글 · 고친 파일)을 남기라는 지시 | 요약 |
| 세션끼리 보는 상태판: 이름(`/rename` 을 따름) · Orca 핸들 · 하는 일 · 잡은 이슈 · 기다리는 것 | `/sessions`, 새 세션의 맥락 |
| git 기록 파괴 5종 보류 (`git reset --hard` · `git checkout -- .` · `git clean -f` · `git stash -u` · `git push --force`). 지우기(`rm -r` · `Remove-Item -Recurse`) · 프로세스 종료는 막지 않고 작업 단위 기록(「지우거나 끈 명령」)과 띠 알림으로 남긴다 (10/12 팀장 결정: 하루 보류 일곱 번 중 사고를 막은 것 0). 세션 자기 임시 자리 안 삭제는 기록도 안 한다. 따옴표 안 검색어는 명령으로 보지 않는다 (`bash -c "…"` 처럼 실행하는 꼴은 본다) | 띠의 「이번 한 번 허용」 · 「닫기」, 또는 `/gauge allow` · `/gauge close` |
| 비용 로그와 비싼 턴 | `/costlog` |
| 긴 백그라운드 작업이 `PROGRESS i/N` 을 찍으면 남은 시간 | 띠 둘째 줄 |
| 저장소 밖에 쓴 자리 (막지 않고 기록) | 띠 · 상태판 |

허용 뒤 다시 실행: 계기판이 「다시 실행하라」를 직접 보내면 Claude Code 자동 모드가 승인 우회로 막는다. 그래서 다시 실행 문장을 입력창에 채워 두고, 보내는 것은 사람이 Enter 로 한다. 문장은 「아직 필요하면 다시 실행하고, 그사이 다른 방법으로 끝냈으면 넘어가라」다 (명령조로 채우면 이미 끝난 일을 다시 돌린다 · 10/12 두 번).

계기판 자체의 보류 규칙을 고치는 편집은 Claude Code 자동 모드가 「자기 수정」으로 막는다. 팀장이 자동 모드를 끄고 확인 창에서 승인해야 한다 (10/12).

## 기록 자리

모두 사용자 폴더 아래 `.mai/` 다 (`%USERPROFILE%` 또는 `$HOME`). 저장소에는 쓰지 않는다.

| 자리 | 무엇 |
|---|---|
| `.mai/sessions/<세션 id>.json` | 상태판 (Claude · Codex 가 같은 형식을 쓴다. 정본 `mai-gauge/types/index.d.ts` 의 `SessionFile`) |
| `.mai/units/` | 작업 단위 기록 |
| `.mai/costlog/<날짜>/` | 턴 · compact 비용 |

## 프로젝트마다 다른 일은 프로젝트에

compact 직전에 그 프로젝트만의 인계 파일을 쓰는 것처럼 프로젝트에 묶인 훅은 사용자 전역 설정에 두지 않는다. 그 저장소의 `.claude/settings.json` 에 두고 경로는 `$CLAUDE_PROJECT_DIR` 로 적는다. 그러면 그 프로젝트 세션에서만 돌고, 다른 기기 · 다른 사람에게도 그대로 간다.

```json
{
  "hooks": {
    "PreCompact": [
      { "hooks": [{ "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/scripts/precompact.sh\"", "timeout": 20 }] }
    ]
  }
}
```

예: project-x 의 압축 직전 인계 (example/project-x#548).

## 고칠 때

```
claude plugin validate mods/mai-gauge
claude plugin test mods/mai-gauge
npx -p typescript tsc -p mods/mai-gauge --noEmit
```

셋 다 통과해야 한다. validate 와 test 만으로는 같은 이름 함수가 둘이어도 통과한다: 1.3.2 에서 계정 함수가 턴 집계 함수를 덮어 10/9~10/12 사흘간 턴 비용이 한 건도 안 적혔고, 형식 검사(TS2393)만 그것을 잡는다.

시험은 진짜 `~/.mai` 에 쓰지 않는다 (fs 를 메모리로 대신 답한다). 새 기능에는 그 기능을 끄면 실패하는 시험을 붙인다.

## 알려진 한계

- Fable 같은 모델별 한도는 Claude Code 가 모드에 주지 않아 보이지 않는다 (5시간 · 7일만)
- `/reload-plugins` 로 다시 불러온 세션은 다음 지시 때 상태판 이름이 `/rename` 이름으로 바뀐다
- Codex 세션은 이 모드가 닿지 않는다. 상태판 형식만 같이 쓴다 (Codex 쪽은 별도 작업)
