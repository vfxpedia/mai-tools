export type Limit = { kind: string; percentUsed: number; resetsAt?: string }

export type Usage = {
  tokens: number | null
  window: number
  percent: number | null
  costUsd: number | null
  limits: Limit[]
  // 자동 compact 가 도는 토큰 수. 자동 compact 가 꺼져 있으면 null (팀장 결정 3).
  threshold: number | null
}

export type TurnTally = {
  steps: number
  // 새 입력 + 캐시 쓰기
  input: number
  output: number
  cacheRead: number
  // 그중 캐시 쓰기 (단가가 새 입력의 1.25 배라 따로 센다)
  cacheWrite?: number
  costUsd: number
}

export type ToolTally = {
  calls: number
  resultTokens: number
  costUsd: number
}

// 세션 하나의 상태 파일 (%USERPROFILE%/.mai/sessions/<id>.json). 팀장 결정 4.
export type SessionFile = {
  id: string
  name: string
  // 팀장이 /rename 으로 붙인 이름이면 true. 이때 모델이 session_status 로 이름을 바꾸지 못한다.
  titled?: boolean
  // Orca 터미널 핸들. 다른 세션이 이 세션에 말을 걸 때 쓴다.
  handle: string | null
  cwd: string
  repo: string | null
  doing: string
  issues: string[]
  waiting: string
  next: string
  contextPercent: number | null
  startedAt: number
  updatedAt: number
  statusAt: number | null
  endedAt?: number
  // 지금 단위에서 저장소 밖에 쓴 자리 수
  outside?: number
}

// 백그라운드 명령. 출력에 `PROGRESS i/N` 을 찍으면 남은 시간을 셈한다.
export type Job = {
  id: string
  command: string
  path: string
  startedAt: number
  progress: { done: number; total: number } | null
  updatedAt: number
}

export type CostEvent =
  | {
      kind: 'turn'
      at: number
      prompt: string
      steps: number
      avgInput: number
      costUsd: number
      cacheBreaks: number
      topTool: string | null
      subagentSteps: number
      durationMs: number
    }
  | {
      kind: 'compact'
      at: number
      trigger: string
      tokensBefore: number | null
      tokensAfter: number | null
      // 요약기의 토큰 (엔진이 요약했을 때) 과 그 사이 세션 비용 증가분
      usage?: { input: number; output: number; cacheRead: number; cacheWrite: number } | null
      costUsd?: number | null
    }

// account: 이 세션이 쓰는 Claude 계정의 구분 (CLAUDE_CONFIG_DIR, 없으면 default). 한도는 계정마다 따로다
export type CostLog = { sessionId: string; name: string; account?: string; events: CostEvent[] }

// 작업 단위 하나의 기계 기록 (LLM 0 원). %USERPROFILE%/.mai/units/<세션 id>.json
export type Unit = {
  doing: string
  issues: string[]
  startedAt: number
  endedAt: number | null
  commits: string[]
  files: string[]
  links: string[]
  // 세션이 열린 저장소 밖에 쓴 자리. 막지 않고 기록해 보이게 한다 (10/7 팀장 결정).
  outside?: string[]
  // 막지 않고 실행한 지우기 · 프로세스 종료 명령 (10/12 팀장 결정: git 기록 파괴만 막는다).
  risky?: string[]
  turns: number
  costUsd: number
}

export type UnitLog = { sessionId: string; name: string; units: Unit[] }

// 보류한 위험 명령. 띠의 「이번 한 번 허용」 단추가 읽는다.
export type Held = { kind: string; command: string }

declare module 'claude-code' {
  interface PluginState {
    'mai-gauge': {
      usage: Usage | null
      turn: TurnTally | null
      tools: Record<string, ToolTally>
      current: string | null
      hidden: boolean
      held: Held | null
      // 「이번 한 번 허용」: 같은 위험 종류를 정한 시각까지 한 번 통과시킨다
      allowOnce: { kind: string; until: number } | null
      jobs: Job[]
      outside: number
      // 최근 턴들이 컨텍스트를 한 턴에 평균 몇 토큰 늘렸나 (정리까지 몇 번 남았나를 셈)
      growth: number | null
      // 한도 표본 (모든 세션이 ~/.mai/limits.json 에 함께 쓰는 것을 읽어 둔 값)
      samples: Record<string, { at: number; pct: number; reset: string }[]>
      // 모든 세션의 턴 · compact 비용 기록 (최근 하루). 한도 예측을 촘촘하게 하는 데 쓴다
      spend: { at: number; cost: number }[]
    }
  }
}
