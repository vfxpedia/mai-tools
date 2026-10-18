> 분류: 시스템 플러그인 운영
> 작성: pipeline · 2026-10-14
> 근거: mai-os #30 · #33 B10 · Windows 두 홈과 ai-lt01의 Codex 0.160.1 실기 · API 직접 재조회
> 요지: Codex가 준 턴·세션 토큰과 계정 한도를 표시하며, USD는 엔진 응답이 있을 때만 표시한다
> 상태: 0.2.2 · 독립 실기 3곳의 8종 훅·토큰·manual compact 재개 확인. 두 번째 Codex 세션 native 발화·자동 동반 창·inline 다섯 줄·작업 단위 compact 제어는 미완료

# MAI Codex Gauge

## 0.2.2 간단 설치와 실제 상태 확인

### 10/14 실제 적용 범위

Windows Orca 관리 홈과 일반 `~/.codex`, Ubuntu ai-lt01의 일반 홈에서 각각 독립 시험 세션을 만들었다. 세 곳 모두 native 0.160.1의 8종 lifecycle, 원문 토큰 대조, 명시적 compact 후 같은 thread의 작업 재개를 확인했다. 이는 독립 시험 결과이며 설치 전부터 열린 모든 세션의 발화를 뜻하지 않는다. 실제 pipeline에서는 새 Node hook이 발화한다. 기존 두 번째 Codex 세션는 passive 동반 관측을 붙였으나 native 발화는 아직 0건이다. 다른 프로세스를 종료하거나 재시작하지 않았다.

ai-lt01의 기본 읽기 전용 sandbox는 현재 7.0.0-38-generic 커널에서 bwrap의 RTM_NEWADDR 단계가 거부됐다. 해당 실패를 OS 설정 변경으로 우회하지 않았다. 마지막 시험은 알려진 답의 작은 파일만 읽는 독립 thread를 full-access로 만들어 통과했다. 따라서 Linux 읽기 전용 sandbox 정상 작동을 주장하지 않는다. 근거는 `os/reports/20261014-codex-mods-linux.md`와 #30의 실기 보고에 있다.

Linux bootstrap은 공식 0.160.1 전체 패키지를 받는다. 단독 `codex` 실행 파일만 받으면 code-mode host가 없어 실제 도구 실행이 실패한다. Node와 Codex는 사용자 소유 `.local/share/mai-codex-runtime`에 설치하며 셸 초기화 파일, 시스템 패키지, 인증 파일을 바꾸지 않는다.

```bash
# 사용자가 설치와 정확한 8종 훅 신뢰를 직접 승인한 뒤 실행한다.
bash bin/bootstrap-linux.sh /ABSOLUTE/PATH/mai-codex-gauge-0.2.2.tgz codex:ACCOUNT
```

`doctor`와 `trust`에는 관리 proxy 대신 판을 지정할 `--exe ABSOLUTE_NATIVE_CODEX`를 사용할 수 있다. `doctor --native true --exe ...`는 읽기 전용 조회다. `trust --approve true --exe ...`는 팀장의 명시적 설치·신뢰 승인 뒤에만 실행한다. 필요한 재개는 같은 ID를 `codex resume EXACT_ID`로 이어 간다. 원문 기록과 설치·신뢰 rollback manifest는 보존한다. WS01의 미래 Linux 설치 환경은 아직 미확인이다.

시간 초과로 hook 프로세스가 끝나면 빈 잠금 파일이 남을 수 있었다. 새 잠금은 로컬 PID·호스트·nonce를 기록하며 **같은 호스트의 죽은 PID만** 자동 회수한다. 기존 잠금은 abandoned 증거 파일로 남긴다. 살아 있는 PID, 다른 호스트, 소유자 정보가 없는 옛 빈 잠금은 자동 회수하지 않는다. 회수 중단으로 recovery-lock이 남으면 쓰기를 보류하고 진단한다. pipeline의 옛 빈 잠금 하나만 크기·기록 시각을 다시 확인한 후 증거 이름으로 옮겼다. 다른 세션의 잠금은 건드리지 않았다.

일반 홈의 native cache가 Orca 홈의 junction으로 보이면 root 방식과 native 방식이 중복될 수 있었다. hooks 방식은 해당 홈에서 **이 제품의 native 선언만** `enabled = false`로 가리고 root 8종을 유지한다. 이미 `enabled = true`인 정확한 제품 선언은 기본 설치로 덮어쓰지 않으며, 승인한 전환에서 `--mask-native true`를 명시해야 한다. 다른 플러그인, 기존 Orca 핸들러, 공유 cache 파일을 변경하지 않는다. 실제 native 조회에서 제품 정의가 16개에서 root 8개로 줄었으며 모두 trusted였다. 실행 중인 옛 TUI가 즉시 이 설정을 다시 읽었다는 뜻은 아니다.

제품 파일이 아니라 실행할 수 있는 로컬 설치 패키지를 제공한다. 기본 홈은 현재 터미널의 `CODEX_HOME`이며, 설정하지 않은 일반 CLI만 `~/.codex`를 사용한다. 계정 별칭은 로그인 정보가 아니라 공유 원장의 구분값이다. 최초 설치에는 직접 지정해야 하고, 재설치는 기존 별칭을 재사용할 수 있다.

```powershell
node src/setup.mjs plan --account codex:ACCOUNT
node src/setup.mjs install --account codex:ACCOUNT
node src/setup.mjs doctor --session EXACT_SESSION_ID --native true
node src/setup.mjs metrics --session EXACT_SESSION_ID
node src/setup.mjs rollback --manifest ABSOLUTE_BACKUP_MANIFEST
```

`install`은 복구 manifest를 먼저 남기고 현재 홈만 설치한다. 일반 홈에는 `.codex-plugin/plugin.json` 정식 manifest·로컬 marketplace·version cache를 설치한다. Orca처럼 공유 plugin junction이 있으면 자동으로 root-hooks 호환 방식을 선택한다. skills도 공유 junction이면 그쪽에는 쓰지 않고 SessionStart가 제품 안의 continuity 스킬 참조를 제공한다. 공유 캐시와 기존 Orca 핸들러는 바꾸지 않는다. 이미 설정한 방식은 자동으로 전환하지 않는다. 이미 존재하는 다른 continuity 스킬은 덮어쓰지 않는다.

배포용 tarball은 `npm pack --ignore-scripts`로 생성한다. registry 게시 없이 다른 터미널에서 설치할 수 있다.

```powershell
npx --yes --ignore-scripts --package C:/ABSOLUTE/PATH/mai-codex-gauge-0.2.2.tgz mai-codex-mods install --account codex:ACCOUNT
```

계정 별칭은 그 터미널에서 실제로 쓰는 계정 구분값으로 바꾼다. 관리 홈을 일반 PowerShell에서 설치하려면 `--home`으로 정확한 관리 홈을 명시한다. 여러 홈을 일괄 탐색하거나 변경하지 않는다.

`doctor`는 설치, 핸들러 등록, 관측된 이벤트, API USD, 제공된 quota 창, checkpoint·Issue 영수증을 따로 보고한다. **설치 성공을 native 활성화로 판정하지 않는다.** `/hooks`에서 정확한 정의를 검토한다. `trust`는 검토 목록만 읽고, 팀장의 명시적 승인 뒤에만 `trust --approve true`로 native `config/batchWrite` 신뢰 API를 실행한다. exact command·source·현재 hash·8종 이벤트를 확인하고 config 사본과 manifest를 먼저 만든다. 다른 hook은 승인하지 않는다. 기존 세션을 종료·재시작하지 않는다. 초기 0.162.1 격리 시험과 10/14의 0.160.1 Windows 두 홈·Linux 실기는 서로 다른 근거다. 최신 실기와 sandbox 제한은 위 적용 범위 및 날짜가 붙은 보고서에서 확인한다.

75% 알림 이후에도 Issue 기록이 확인되지 않았으면 다음 사용자 턴과 compact 직후 continuation에 안내를 다시 준다. 실제 게시한 댓글은 `checkpoint --session ID --comment EXACT_ISSUE_COMMENT_URL`로 독립적으로 읽어 확인한다. 원장에는 URL·검증 시각·본문 해시만 남기며 원문 대화를 업로드하지 않는다. 댓글 생성 시각이 checkpoint 전이거나 다른 Issue면 거절한다. 자동으로 GitHub에 댓글을 쓰지는 않는다. 기록은 해당 작업을 수행하는 에이전트가 기존 승인 범위에서 한다.

`doctor --native true`는 관리 proxy에서 현재 hook 정의의 enabled·trustStatus와 API를 직접 읽는다. 기본 doctor의 저장 관측과 구분하며, 이 진단은 한도 표본·Issue·세션 상태를 쓰지 않는다. Windows 제어 소켓을 일반 파일처럼 stat하지 않는다. 실제 AF_UNIX 소켓은 Node에서 EACCES여도 native proxy가 연결할 수 있기 때문이다.

10/13 실제 관리 API는 자기 `threadUsage:null`·300분 창 미제공이며 10080분 창은 제공한다. 수치는 요청 시점마다 바뀌므로 고정값으로 쓰지 않는다. 팀장의 직접 승인으로 운영 hook 8개를 native 신뢰 API에 등록했고 다시 조회해 trusted를 확인했다. 기존 pipeline 턴은 시작 시 표본이 없어 턴 한도 변화가 null이다. 신뢰 승인 이후 기존 실행 프로세스에 새 hook이 즉시 발화한다고 가정하지 않는다. 네이티브 입력창 안 다섯 줄·자동 compact 통제는 이 설치 패키지로 해결되지 않는다. 아래 동반 화면과 구분한다.

실제 native 플러그인 시험에서는 installed·enabled뿐 아니라 `hooks/list`의 8개 정의를 확인한다. 기존 root `plugin.json`의 `extensions.com.openai.hooks`만 선언하면 native가 그 manifest를 우선 읽어 `.codex-plugin/plugin.json` 선언을 가리고 hook 0개가 되는 결함을 잡았다. 두 manifest 모두 native `hooks`·`skills` 선언을 갖도록 고쳤다. 신뢰는 여전히 사용자 검토를 거친다.

Node.js 22 이상, 추가 패키지와 모델 호출 없음. Claude 소스와 Orca의 기존 훅 핸들러는 변경하지 않는다. 제품에는 native 플러그인 설치 준비, 기본 footer와 별도 동반 화면이 있다. **동반 화면은 Codex CLI 입력창 안의 Mods가 아니다.** 플러그인 설치와 훅 신뢰 승인은 다르다. 이미 실행 중인 Codex에 설정이 즉시 반영됐다고 가정하지 않는다.

## 설치와 철회

`node src/install.mjs plan HOME codex:alias`는 변경 목록만 출력한다. `apply HOME codex:alias BACKUP`는 원본 해시 확인 후 사본과 복구 manifest를 먼저 만든다. `rollback MANIFEST`는 설치 이후 파일이 그대로인 경우에만 되돌린다. 남의 새 변경이 있으면 자동 복원을 거절한다. 공유 사용량이나 대화 기록은 철회 대상이 아니다. 자동 재시작과 훅 신뢰 우회는 하지 않는다.

Orca 홈의 `plugins`가 기본 홈으로 연결된 junction이면 native 설치를 거절한다. `plan-companion`과 `apply-companion`은 현재 홈 안의 제품 파일·관측 설정·footer만 적용하고 공유 캐시와 플러그인 등록을 건드리지 않는다. 이 모드는 동반 `live` 화면으로 동작하며 생명주기 훅과 자동 맥락 주입은 설치하지 않는다. 공유 캐시 적용은 별도 범위 승인이 필요하다.

`plan-product HOME codex:alias` · `apply-product HOME codex:alias BACKUP`은 제품 파일만 갱신한다. 기존 `config.toml`·관측 설정·훅 신뢰·공유 plugin cache는 변경하지 않는다. 기존 계정 별칭이 다르면 거절한다. 실행 중인 제품은 자동 재시작하거나 hot reload하지 않는다.

`plan-hooks HOME codex:alias` · `apply-hooks HOME codex:alias BACKUP`은 공유 plugin junction을 건드리지 않고 현재 홈의 `hooks.json`에 게이지 핸들러를 추가한다. 기존 Orca 핸들러·원문·공유 캐시는 그대로 남긴다. 이 제품의 native 플러그인만 현재 홈의 `config.toml`에서 가려 중복 등록을 막는다. 사본과 manifest가 먼저 생기며 원복 시험은 원래 hooks 바이트까지 대조한다. 등록은 신뢰 승인이 아니다. native `/hooks` 또는 승인한 `trust`에서 정확한 정의를 검토한다. 신뢰 bypass는 사용하지 않는다.

설치된 정의는 설치 당시의 **절대 Node 실행 경로**를 사용한다. Linux bootstrap의 임시 PATH를 부모 셸에 남길 필요가 없다. Windows에서는 같은 Node 파일을 가리키는 공백 없는 경로를 검증해 cmd·PowerShell 양쪽에서 직접 실행한다. 안전한 경로를 확인할 수 없거나 hook 경로에 셸 확장 문자가 있으면 설치를 거절한다. 런타임 경로가 바뀌면 재설치 후 바뀐 정확한 8개 hash를 다시 신뢰해야 한다. 선언용 패키지는 장비 경로를 담지 않으며 설치 시 홈별 정의를 만든다.

증분 읽기는 기본 400행·처리 예산으로 제한한다. 파싱과 집계를 함께 수행한 행까지만 cursor를 확정한다. 실패한 토큰 기록은 `pendingTurns`에 먼저 저장하고 다음 관측에서 이전 턴도 다시 시도한다. 날짜별 일괄 costlog 쓰기를 사용한다. `scan`이 예산에 걸리면 **같은 명령**으로 그 cursor부터 이어 간다. 의도적으로 처음부터 다시 만들 때만 `scan --rebuild true`를 쓴다. 파일 I/O 지연의 절대 상한을 보장하지는 않으며 native 실제 시험으로 timeout 여부를 확인한다.

Codex의 `/plugins`에서 `mai-codex-gauge@mai-codex-local` 설치 상태와 훅 내용을 검토한다. `/statusline`에서 footer 항목을 고를 수 있다. 기존에 설정한 footer는 교체하지 않는다. 로컬 marketplace와 버전 cache는 native `codex plugin marketplace add`, `codex plugin add`를 임시 홈에서 실측한 형식이다.

## 관측과 표시

```
node src/cli.mjs scan --home HOME --account codex:alias --session ID
node src/cli.mjs status --session ID --name pipeline --doing "Current work" --issues "vfxpedia/mai-os#30" --next "Next work"
node src/cli.mjs show --session ID
node src/cli.mjs watch --session ID
```

`scan`은 최초 과거 기록의 전체 사용량을 계산한다. 이후 `observe`와 훅은 cursor 이후만 읽는다. `watch`는 상태판을 읽기만 하며 한도 표본을 쓰거나 요청을 생성하지 않는다. `status`는 사람이 정한 이름·업무·이슈·다음 일을 기록한다. 기본 공유 경로는 `~/.mai/sessions`, `limits.json`, `costlog`, `units`다. 자기 세션 파일만 쓰며 계정은 명시적인 로컬 별칭이다. 로그인 계정 자체의 식별은 아니다. 계정 변경 시 별칭도 확인해야 한다.

### 10/13 비용 기준 정정

단가표 환산은 구현하지 않는다. 턴과 세션의 입력·캐시 입력·출력 토큰을 Codex `token_count`에서 합산한다. 캐시는 입력에 포함되므로 total은 입력+출력이다. 모델 이름이 새로 바뀌어도 가격표가 필요 없다. `metrics`는 생략 없는 숫자·원천·coverage를 JSON으로 내고, 띠의 `T input/cache/output · S input/cache/output`은 턴·세션을 보여준다. 폭이 좁으면 수치는 축약하며 정확한 값은 metrics에 남는다. 이전 턴을 현재 턴으로 표시하지 않는다.

native UserPromptSubmit·Stop의 계정 quota 표본은 같은 창·같은 reset·증가한 값·정상 시각만 비교한다. `account 7d+2pp`는 계정 전체의 관측 변화다. 다른 병렬 세션도 기여하고 응답 해상도 아래 변화는 0pp일 수 있으므로 이 턴의 독점 소모나 정확한 가격이 아니다. reset·감소·누락·중복 Stop은 새 차이를 만들지 않는다. 5시간 창은 실제 응답에 생긴 경우만 표시한다. 쉬는 세션은 한도 표본 시각을 새로 찍지 않는다.

Claude Code의 USD도 엔진이 토큰과 단가로 계산한 추정값이다. 구독의 추가 청구액은 아니다. [Claude 공식 비용 문서](https://code.claude.com/docs/en/costs)는 로컬 계산과 구독 청구의 차이를 명시한다. Orca의 ‘예상 비용’도 [단가표](https://github.com/stablyai/orca/blob/v1.4.224/src/main/codex-usage/codex-model-pricing.ts)와 [비용 계산 함수](https://github.com/stablyai/orca/blob/v1.4.224/src/main/codex-usage/codex-usage-cost-estimate.ts)로 만든 값이며 OpenAI USD API 응답이 아니다. Codex Mods는 둘의 계산표를 복제하지 않는다.

costlog의 기존 Claude 필드·account 구분은 유지한다. Codex 이벤트에 inputTokens·cachedInputTokens·outputTokens·tokenSource·quotaChange를 추가한다. 세션 상태판의 공통 형식은 바꾸지 않는다. Windows의 짧은 읽기 잠금은 원본 해시를 매번 재검증하면서 atomic rename만 최대 350ms 재시도한다. 장기 잠금이나 외부 변경은 덮어쓰지 않는다.

`live --home HOME --account codex:alias --session ID`는 이미 실행 중이라 새 훅을 아직 읽지 않은 세션을 위한 동반 관측 화면이다. 2초마다 cursor 이후 관측과 화면 갱신만 한다. `watch`와 달리 사용량 원장을 쓰는 명시적 모드다. 에이전트 입력·추가 모델 요청·compact 통제는 하지 않으며 네이티브 훅이 발화했다는 증거도 아니다.

연속 TTY 표시는 별도 화면 버퍼를 사용해 옛 화면 잔상과 섞이지 않게 한다. Ctrl+C로 끝내면 원래 셸 화면으로 돌아온다. `--once`와 리다이렉트는 화면 버퍼를 바꾸지 않는다. 강제 프로세스 종료는 정상 복귀 절차를 실행하지 못하므로 Ctrl+C를 우선한다.

입력은 fresh+cache read+cache write, 출력은 reasoning을 이미 포함한다. 중복 합산하지 않는다. **0.2.2는 단가표·환산 함수·그 전용 시험을 소스와 배포에서 제거했다.** 설치기는 정확한 폐기 대상 파일만 사본·해시를 먼저 남긴 뒤 삭제하고, 다른 파일·공유 캐시·기록은 건드리지 않는다. 턴의 `costUsd`는 검증된 native 턴 경계의 API 누적액 차이가 있을 때만 기록하며 `costSource:provider-estimate-delta`와 두 원천 표본을 함께 남긴다. 이것도 확정 청구액은 아니다. 없는 시작 표본·null·다른 턴·감소액은 null이며 과거 턴을 환산해 채우지 않는다. 자정을 넘는 턴은 첫 요청 UTC 날짜에 계속 갱신한다.

설치기 갱신은 이미 실행 중인 `live` 프로세스의 메모리를 갱신하지 않는다. 구형 writer와 신형 writer가 같은 세션 costlog에 함께 쓰면 신형 필드가 다시 없어질 수 있다. 파일 병합 코드만 고쳐 이 문제가 해결됐다고 보고하지 않는다. 팀장 승인 후 동반 관측 프로세스만 Ctrl+C로 마치고 같은 session ID·CODEX_HOME·account를 사용해 새 제품으로 다시 실행하는 것이 최소 변경이다. Codex 본 세션과 원문 대화는 종료하지 않는다. 승인 전에는 units/metrics의 정확한 근거를 유지하며 costlog 안정화는 미완료로 남긴다.

비용 원천은 native `account/usage/read`의 자기 세션 `threadUsage.estimatedUsageUsdMicros`뿐이다. 이 값은 API가 보고한 추정액이며 확정 청구액이 아니다. threadUsage 또는 USD 미제공은 `USD not provided`, 조회 실패·다른 세션·잘못된 숫자는 `API unavailable`로 구분한다. 0은 API가 명시적으로 0을 줬을 때만 금액으로 표시한다. 그룹별 USD는 응답에 없으므로 토큰 비율로 만들어 내지 않는다.

```
node src/cli.mjs api --exe ABSOLUTE_NATIVE_CODEX_EXE --session ID --transport proxy --sock SOCKET_PATH --timeout 3000
node src/cli.mjs api --exe ABSOLUTE_NATIVE_CODEX_EXE --session ID --transport stdio --timeout 5000
```

`api`는 기본적으로 읽기만 한다. `--record --account codex:alias`를 추가하면 기존 자기 units의 계정을 확인하고 `codex.provider`에만 표본을 저장한다. 다른 상태·이벤트는 보존하며 오래된 표본은 거절한다. 로그인 파일·키를 읽거나 새 모델 요청·thread resume을 하지 않는다. proxy는 실행 중 관리 서버, stdio는 별도 진단 서버다. 진단 성공을 관리 서버 성공으로 보고하지 않는다.

현재 `observe`·`live`·native 훅은 새 요청이 관측될 때 실제 API를 자동 조회한다. Orca 홈의 관리 소켓과 버전별 native 실행 파일만 찾으며 인증 파일은 읽지 않는다. proxy는 HTTP Upgrade 검증·masked client frame·응답 예산을 갖춘 WebSocket으로 연결한다. `account/usage/read`와 `account/rateLimits/read` 외의 요청이나 유료 모델 호출은 없다. idle polling은 API 요청이나 한도 표본을 만들지 않는다.

native `UserPromptSubmit`가 시작 전 API 표본을, 같은 `turn_id`의 `Stop`이 종료 표본을 받아 턴 차액과 세션 누적액을 저장한다. 첫 기준선이 없으면 턴 금액은 `-`다. fixture에서는 $1.00 → $1.25를 턴 $0.25·세션 $1.25로 표시하고 기록한다. 이 fixture 성공을 현재 계정의 실제 USD 수신으로 설명하지 않는다. 10/12 실제 관리 서버는 `threadUsage:null`, 7일 8%, `secondary:null`을 반환했다. 이 경우 `USD not provided`와 `5 hours: not provided`이며 미제공 값을 만들어 내지 않는다.

후속 실제 조회에서는 7일 9%였다. 첫 prompt 때 받은 quota도 읽기 화면에 반영하되 idle account 표본은 만들지 않는다. costlog 잠금 때문에 쓰기가 실패하면 자기 units에 남은 API 근거로 다음 관측에서 재시도한다. 저장된 이전 턴을 매 hook마다 다시 쓰지는 않는다. 잘못된 quota 스키마를 명시적 null 창으로 취급하지 않는다.

띠는 Claude `ce92211`의 12칸 가는 선·칸 폭·조각별 색 규칙을 사용한다. 사용 구간은 판정 색, 예상 구간은 같은 색을 흐리게, 빈 구간은 회색, 문맥 임계 표시는 흰색이다. 제공된 Claude 화면의 dark daltonized 팔레트(파랑 `#3399FF` · 노랑 `#FFCC00` · 빨강 `#FF6666` · 회색 `#999999` · 작업 문구 `#99CCFF`)를 truecolor로 고정한다. Claude 테마 변경 자동 감지는 하지 않는다. `watch`와 `live`는 TTY에서 같은 색을 쓰고, 리다이렉트 출력은 ANSI 없이 낸다. 새 프레임은 기존 화면을 지워 중복 행을 남기지 않는다. 56칸 미만에서는 막대를 숨기며, 폭 40~200에서 비용 숫자를 중간에 잘라 잘못 읽히게 하지 않는지 시험한다. 실기 모바일·입력창 안 다섯 줄 배치는 별도 인수 항목이다.

context는 마지막 요청의 입력과 모델 창을 비교한 관측값이다. 85%는 정리 권고일 뿐 자동 compact 임계값이 아니다. 공유 `contextPercent`는 compact 분모가 확인되지 않아 null이다. 한도는 마지막 실제 요청의 표본이며 5시간/7일을 창 길이로 구분한다. 실제 quota 조회가 성공했지만 없는 창은 `not provided`, 아직 조회 근거가 없으면 `no data yet`이다. 쉬는 세션이 시간만 바꿔 새 표본을 만들지 않는다.

## 맥락 보존과 한계

훅은 원본 JSONL을 수정하거나 요약으로 대체하지 않는다. 50%에서 원문 경로·cursor·업무·이슈·next를 자기 units에 저장한다. 75%에서 현재 작업 단위 종료 후 정본 Issue에 목표·결과·결정·실측·남은 일·대기를 게시하고 다시 읽어 확인하도록 모델에 지시한다. 85%에서 이어가기 기록을 준비한다. 지시 생성은 실제 Issue 게시와 다르므로 체크포인트의 `issueStatus`는 확인 근거가 없으면 `requested`다. `compactStatus:not-triggered`를 기록하며 실행하지 않은 compact를 성공으로 표시하지 않는다.

Stop에서 처음 넘은 단계는 화면 안내만으로 전달 완료 처리하지 않는다. 다음 모델이 읽을 수 있는 hook에 기록 지시를 한 번 전달할 때까지 자기 pending 상태로 남긴다.

SessionStart(compact 포함)는 자기 업무·원문·원장과 함께 Claude·Codex 공유 상태판의 live 세션 doing·waiting·next·이슈를 읽는다. 12시간 이상 갱신이 없거나 종료된 세션·손상 파일·ID 불일치는 제외한다. 다른 세션의 파일은 쓰지 않으며 내용은 지시나 승인으로 취급하지 않는다. 메시지를 보내기 전 Orca 핸들을 다시 조회해야 한다. PostCompact는 단계 cycle을 초기화하고 다음 즉시 continuation에서 최신 상태를 읽는다. 원문 보존과 모델의 무한 기억은 다르다. **Claude의 native 턴 경계 compact API에 해당하는 실행 제어는 현재 Codex 훅만으로 보장하지 못한다.** 작업을 멈추는 `continue:false`를 compact 지연으로 꾸미지 않는다. native 신뢰·실제 발화·재개 검증 전에는 작동 완료라고 보고하지 않는다.

손상·경로 탈출·junction·ID 불일치·writer 충돌은 진단만 내고 정상 에이전트 작업을 차단하지 않는다. limits 쓰기는 원자적 교체와 재검증을 사용하나 Claude writer가 동일한 잠금을 쓰지 않아 최후 rename 직전의 완전한 상호 배제는 아직 보장하지 않는다. 독립 시험의 8종 lifecycle·manual compact 재개와 설치 전부터 열린 운영 세션은 구분한다. 계정 전환 자동 식별, 실제 모바일, 두 번째 Codex 세션 native 발화, 기존 운영 세션 모두의 lifecycle 전체는 미확인이다. 자동 compact를 작업 단위로 옮기는 제어는 미구현이다.

시험: `node --test tests/*.test.mjs`. native 상태줄은 [기본 항목 선택](https://learn.chatgpt.com/docs/developer-commands), 비용 조회는 [App Server](https://learn.chatgpt.com/docs/app-server), 훅 신뢰·compact는 [Hooks](https://learn.chatgpt.com/docs/hooks)를 따른다. 현재 경로의 실제 응답이 문서보다 우선이며 미제공 값을 환산으로 채우지 않는다.
