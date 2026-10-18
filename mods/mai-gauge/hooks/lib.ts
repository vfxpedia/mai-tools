// 엔진($)을 안 쓰는 순수 계산. 시험이 엔진 없이 바로 부른다.

import type { CostEvent, Job, Limit, SessionFile, ToolTally, Unit } from '../types'

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 100_000 ? 0 : 1)}k`
  return String(Math.round(n))
}

export function usd(n: number): string {
  return n >= 10 ? `$${n.toFixed(1)}` : `$${n.toFixed(2)}`
}

export function bar(percent: number, width = 10): string {
  const filled = Math.max(0, Math.min(width, Math.round((percent / 100) * width)))
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

// 문턱은 자동 compact 문턱 기준의 % 다 (팀장 결정 3).
export function level(percent: number): 'success' | 'warning' | 'error' {
  if (percent >= 85) return 'error'
  if (percent >= 50) return 'warning'
  return 'success'
}

export function untilReset(resetsAt: string | undefined, nowMs: number): string {
  if (!resetsAt) return ''
  const ms = Date.parse(resetsAt) - nowMs
  if (!Number.isFinite(ms) || ms <= 0) return ''
  return duration(ms)
}

export function duration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '0m'
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  if (h >= 24) return `${Math.floor(h / 24)}d${h % 24}h`
  if (h > 0) return `${h}h${m}m`
  if (m > 0) return `${m}m`
  return `${Math.max(1, Math.round(ms / 1000))}s`
}

// 도구 이름 옆에 붙일 짧은 인자. 무엇을 부르는지 알아볼 만큼만.
export function brief(input: unknown): string {
  if (typeof input !== 'object' || input === null) return ''
  const o = input as Record<string, unknown>
  const pick = o.command ?? o.file_path ?? o.pattern ?? o.url ?? o.description ?? o.query
  if (typeof pick !== 'string') return ''
  const one = pick.replace(/\s+/g, ' ').trim()
  return one.length > 48 ? `${one.slice(0, 47)}…` : one
}

// 요청 k 가 부른 도구들의 결과가 요청 k+1 의 입력에 더한 토큰.
// 입력(k+1) = 입력(k) + 출력(k) + 결과(k) 이므로 결과(k) = 입력(k+1) - 입력(k) - 출력(k).
// 한 요청이 도구를 여럿 부르면 똑같이 나눈다 (추정).
export function attribute(
  tools: Record<string, ToolTally>,
  prevTools: readonly string[],
  added: number,
  costShare: number,
): Record<string, ToolTally> {
  if (prevTools.length === 0) return tools
  const each = Math.max(0, added) / prevTools.length
  const eachCost = Math.max(0, costShare) / prevTools.length
  const next: Record<string, ToolTally> = { ...tools }
  for (const name of prevTools) {
    const t = next[name] ?? { calls: 0, resultTokens: 0, costUsd: 0 }
    next[name] = {
      calls: t.calls + 1,
      resultTokens: t.resultTokens + each,
      costUsd: t.costUsd + eachCost,
    }
  }
  return next
}

// 캐시가 깨진 요청: 새로 쓴 캐시가 입력의 절반을 넘고 크기도 작지 않다.
export function isCacheBreak(input: number, cacheCreation: number): boolean {
  return input >= 20_000 && cacheCreation > input * 0.5
}

// ---------------------------------------------------------------- 위험 명령 보류

// 명령 문자열만 본다. 자연어 판단을 넣지 않는다 (rl 린트가 거짓 양성 70 % 로 꺼진 교훈).
const GIT = String.raw`\bgit(?:\s+(?:-C|-c|--git-dir|--work-tree|--namespace)(?:\s+|=)(?:"[^"]*"|'[^']*'|\S+)|\s+--?[A-Za-z][\w-]*(?:=\S+)?)*\s+`
const DANGEROUS: readonly { name: string; re: RegExp }[] = [
  // 앞에 따옴표 · 괄호도 본다: bash -c "rm -rf x" 가 1.5.0 까지 안 잡혔다 (10/12 새 시험이 찾음)
  { name: 'rm -r', re: /(^|[;&|("'`{]\s*|\s)rm\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b/ },
  { name: 'Remove-Item -Recurse', re: /\bRemove-Item\b[^;\n]*-Recurse\b/i },
  // git 과 하위 명령 사이의 전역 옵션(-C 폴더 · -c 키=값 · --git-dir 등)도 건넌다: git -C x reset --hard 가 1.6.0 까지 안 잡혔다 (10/12 실측)
  { name: 'git reset --hard', re: new RegExp(`${GIT}reset\\s+[^;\\n]*--hard\\b`) },
  { name: 'git checkout -- .', re: new RegExp(`${GIT}checkout\\s+(\\S+\\s+)?--\\s+\\.(\\s|$|;)`) },
  { name: 'git clean -f', re: new RegExp(`${GIT}clean\\s+[^;\\n]*-[a-zA-Z]*f`) },
  { name: 'git stash -u', re: new RegExp(`${GIT}stash\\s+[^;\\n]*(-u\\b|--include-untracked|-a\\b|--all)`) },
  { name: 'git push --force', re: new RegExp(`${GIT}push\\b[^;\\n]*(\\s-f\\b|--force\\b|--force-with-lease\\b)`) },
  { name: '프로세스 종료', re: /(^|[;&|("'`{]\s*|\s)(kill|taskkill|pkill|killall)\b|\bStop-Process\b/i },
]

// 따옴표 안은 검색어 · 메시지라 명령이 아니다 (10/12 super 가 기록에서 「taskkill」 글자를 grep 하다 보류됨).
// 다만 따옴표 안을 «실행하는» 꼴(bash -c · powershell -Command · eval · & "x" · $( ) · 백틱)이 하나라도 있으면 전부 본다.
const RUNS_QUOTED =
  /\b(bash|sh|zsh|dash|pwsh|powershell|cmd|python[\d.]*|py|node|perl|ruby|wsl)(\.exe)?\b[^;|&\n]*\s(-c|-e|-Command|-EncodedCommand|\/c|\/k)\b|\b(eval|iex|Invoke-Expression|Invoke-Command|Start-Process|xargs|ssh|exec|source|watch|nohup|timeout|env)\b|&\s*["']|\.\s+["']/i

export function executableText(command: string): string {
  if (RUNS_QUOTED.test(command)) return command
  return command.replace(/'[^']*'|"(?:[^"\\`$]|\\.|\$(?!\())*"/g, '""')
}

function kindsOf(command: string): string[] {
  const text = executableText(command)
  return DANGEROUS.filter(d => d.re.test(text)).map(d => d.name)
}

export function dangerous(command: string): string | null {
  return kindsOf(command)[0] ?? null
}

// 막는 것은 실제 사고가 난 git 기록 파괴뿐이다 (8/27 checkout -- . · 9/14 reset --hard).
// 지우기 · 프로세스 종료는 막지 않고 기록만 한다: 10/12 하루 보류 일곱 번 중 사고를 막은 것은 0, 팀장 결정 「보류 줄이기」.
const NOTE_ONLY = new Set(['rm -r', 'Remove-Item -Recurse', '프로세스 종료'])

export function blockingKind(command: string): string | null {
  return kindsOf(command).find(k => !NOTE_ONLY.has(k)) ?? null
}

export function notedKind(command: string): string | null {
  return kindsOf(command).find(k => NOTE_ONLY.has(k)) ?? null
}

// 세션 자기 임시 자리 안을 지우는 것은 보류하지 않는다 (10/12 lead 가 $CLAUDE_JOB_DIR/tmp 의 받은 사본을 지우다 보류됨).
// 지우는 대상을 전부 절대 경로로 풀어 낼 수 있고 모두 roots 안(그 자리 자체는 아님)일 때만 그 경로들을 돌려준다.
// 못 푸는 것(모르는 변수 · .. · ~ · 와일드카드 · 상대 경로인데 cd 를 모름)이 하나라도 있으면 null (보류).
export function scratchTargets(command: string, roots: readonly string[], env: Readonly<Record<string, string>> = {}): string[] | null {
  const kinds = kindsOf(command)
  if (!kinds.length || kinds.some(k => k !== 'rm -r' && k !== 'Remove-Item -Recurse')) return null
  if (!roots.length) return null
  const BAD = '\u0000'
  const vars: Record<string, string> = { ...env }
  const expand = (s: string): string =>
    s.replace(/\$\{(\w+)\}|\$(\w+)/g, (_, a?: string, b?: string) => vars[(a ?? b)!] ?? BAD)
  const unquote = (t: string): string => (/^(["']).*\1$/.test(t) ? t.slice(1, -1) : t)
  const isAbs = (p: string): boolean => /^([a-zA-Z]:[\\/]|\/)/.test(p)
  let cwd: string | null = null
  const out: string[] = []
  for (const seg of command.split(/&&|\|\||[;\n|]/)) {
    const toks = (seg.match(/"[^"]*"|'[^']*'|[^\s{}()]+/g) ?? []).map(t => t.trim()).filter(Boolean)
    // 변수 대입: bash  T="..."  ·  PowerShell  $k = '...'
    const sh = /^\s*([A-Za-z_]\w*)=("[^"]*"|'[^']*'|\S*)\s*$/.exec(seg)
    if (sh) {
      const v = unquote(sh[2]!)
      vars[sh[1]!] = sh[2]!.startsWith("'") ? v : expand(v)
      continue
    }
    const ps = /^\s*\$([A-Za-z_]\w*)\s*=\s*('[^']*'|"[^"]*")\s*$/.exec(seg)
    if (ps) {
      const v = unquote(ps[2]!)
      vars[ps[1]!] = ps[2]!.startsWith("'") ? v : expand(v)
      continue
    }
    const head = toks[0]?.toLowerCase()
    if (head === 'cd' || head === 'set-location' || head === 'pushd') {
      const arg = toks[1] ? expand(unquote(toks[1])) : ''
      cwd = !arg || arg.includes(BAD) ? null : isAbs(arg) ? arg : cwd ? `${cwd}/${arg}` : null
      continue
    }
    const at = toks.findIndex(t => t === 'rm' || /^Remove-Item$/i.test(t))
    if (at < 0) continue
    const isRm = toks[at] === 'rm'
    const targets: string[] = []
    for (let i = at + 1; i < toks.length; i++) {
      const t = toks[i]!
      if (/^\d?>/.test(t)) break
      if (t.startsWith('-')) {
        if (!isRm && /^-(Path|LiteralPath)$/i.test(t)) targets.push(toks[++i] ?? '')
        else if (!isRm && /^-(ErrorAction|EA|Exclude|Include|Filter)$/i.test(t)) i++
        continue
      }
      targets.push(t)
    }
    if (!targets.length) return null
    for (const raw of targets) {
      const t = expand(unquote(raw))
      if (!t || t.includes(BAD) || t.split(/[\\/]/).includes('..') || /[*?[\]]/.test(t) || t.startsWith('~')) return null
      const abs = isAbs(t) ? t : cwd && !cwd.includes(BAD) ? `${cwd}/${t}` : null
      // .. 은 대상뿐 아니라 cd 에도 숨는다 (cd .. && rm -rf x)
      if (!abs || abs.split(/[\\/]/).includes('..')) return null
      const p = normPath(abs).toLowerCase()
      const inside = roots.some(r => {
        const rr = normPath(r).toLowerCase()
        return p.startsWith(`${rr}/`)
      })
      if (!inside) return null
      out.push(normPath(abs))
    }
  }
  return out.length ? out : null
}

export function holdReason(kind: string): string {
  return (
    `계기판 보류 (${kind}): 되돌릴 수 없거나 다른 세션에 닿는 명령이다. ` +
    '대상 목록을 먼저 보여 주고 채팅에서 팀장 확인을 받아라. ' +
    '팀장이 프롬프트 위 띠의 「이번 한 번 허용」을 누르거나 /gauge allow 를 치면 같은 종류의 명령이 한 번 통과하고, 계기판이 입력창에 다시 실행 문장을 채워 둔다.'
  )
}

// ---------------------------------------------------------------- 문턱 알림

// 75 % 가 단위 끝 정리의 자리다. LLM 정리는 여기서 한 번, 본 세션이 원래 할 인계로 한다.
export function thresholdNote(level: number, percent: number, statusTool: string, unitPath = ''): string {
  const facts = unitPath ? ` 커밋 · 남긴 글 · 고친 파일은 ${unitPath} 에 기계로 적혀 있으니 그것을 근거로 쓴다.` : ''
  if (level < 85) {
    return (
      `\n\n[계기판] 컨텍스트가 자동 compact 문턱의 ${percent}% 다. ` +
      '지금 작업 단위를 마치는 자리에서 멈추고, 그 단위의 인계(목표 · 결과 · 결정 · 확인한 사실과 근거 · 남은 것 · 기다리는 것)를 해당 이슈 댓글로 남겨라.' +
      facts +
      ` 그리고 ${statusTool} 로 다음 단위를 적고 이어 가라.`
    )
  }
  return (
    `\n\n[계기판] 컨텍스트가 자동 compact 문턱의 ${percent}% 다. 곧 compact 된다. ` +
    `이번 응답에서 ${statusTool} 로 세션 상태를 확정하고, ` +
    '인계를 아직 안 남겼으면 이슈 댓글로 남겨라. 이 응답이 끝나면 계기판이 턴 사이에서 compact 한다 (작업 도중에는 하지 않는다).' +
    facts
  )
}

// 다른 세션 소식은 compact 뒤 prompt.context 가 새로 읽어 넣으므로 요약에 싣지 않는다 (낡은 값이 남는다).
export function compactInstructions(handoffPath: string, own: string, facts = ''): string {
  return [
    '요약에 반드시 남길 것: 열린 이슈 번호 · 브랜치 · 미커밋 파일 · 다음 할 일 · 결정 대기 · 누구의 답을 기다리는지.',
    own ? `이 세션이 마지막으로 적은 상태:\n${own}` : '',
    facts ? `기계로 적은 이번 단위의 사실 (요약에 그대로 남겨라):\n${facts}` : '',
    `요약의 맨 끝에 이 한 줄을 그대로 넣어라: 「이어 가기 전에 ${handoffPath} 와 잡은 이슈를 다시 읽어라.」`,
  ]
    .filter(Boolean)
    .join('\n')
}

// ---------------------------------------------------------------- 한도 속도

// 창의 길이. 이 둘만 리셋 시각에서 시작 시각을 거꾸로 셀 수 있다.
export const WINDOW_MS: Record<string, number> = { five_hour: 5 * 3_600_000, seven_day: 7 * 86_400_000 }

export type Pace = {
  // 지금 속도로 리셋 때 몇 % 가 되는가
  projected: number
  // 지금 속도로 100 % 에 닿는 시각. 리셋 전에 안 닿으면 null
  fullAt: number | null
  // 속도를 어디서 냈나: 최근 15 분 사용 비용(모든 세션, 가장 촘촘) · 최근 % 기울기 · 창 전체 평균
  basis: 'spend' | 'recent' | 'window'
}

// 한도 % 는 계정 전체 값이다. 세션마다 (시각, %) 를 한 파일에 적어 두면 그 기울기가
// 다른 세션 · 다른 기기가 쓴 것까지 담는다. 창 평균보다 지금 속도를 빨리 따라간다.
export type LimitSample = { at: number; pct: number; reset: string }

export const RECENT_MS = 30 * 60_000

// 창마다 「최근」의 길이. 주간 % 는 1 % 씩 천천히 움직여 30 분으로는 한 계단이 속도를 부풀린다 (10/9 실측: 7일 ~993%).
export const RECENT_BY_KIND: Record<string, number> = { five_hour: 30 * 60_000, seven_day: 6 * 3_600_000 }

// 표본을 얼마나 남기나. 비용 기반 예측은 창 안의 긴 이력에서 「1 % 가 몇 달러인가」를 배우므로 길게 둔다.
export const KEEP_BY_KIND: Record<string, number> = { five_hour: 5 * 3_600_000, seven_day: 24 * 3_600_000 }

// ---------------------------------------------------------------- 비용 기반 한도 예측

// 한도 % 는 1 % 계단이라 짧은 구간에서 거칠다. 세션마다 턴 비용을 적어 두므로(모든 세션 합),
// 이 창에서 「% 가 오른 만큼 ÷ 그동안 쓴 돈」 으로 1 달러가 몇 % 인지 배우고, 최근 15 분 쓴 돈에 곱한다.
export type SpendEvent = { at: number; cost: number }
export const SPEND_RECENT_MS = 15 * 60_000
// 7일은 15 분 쉬면 「이번 주 더 안 쓴다」 로 읽혀 흔들린다. 창마다 최근 길이를 달리 둔다.
export const SPEND_RECENT_BY_KIND: Record<string, number> = { five_hour: 15 * 60_000, seven_day: 3 * 3_600_000 }

export function spendBetween(events: readonly SpendEvent[], from: number, to: number): number {
  let n = 0
  for (const e of events) if (e.at > from && e.at <= to) n += e.cost
  return n
}

export function spendRate(samples: readonly LimitSample[], reset: string | undefined, events: readonly SpendEvent[], nowMs: number, kind = 'five_hour'): number | null {
  const s = sameSource(samples.filter(x => x.reset === reset && x.at <= nowMs))
  if (s.length < 2) return null
  const first = s[0]!
  const last = s[s.length - 1]!
  const rise = last.pct - first.pct
  // 3 % 넘게 올라야 비율이 계단 한 칸에 휘둘리지 않는다
  if (rise < 3) return null
  const spent = spendBetween(events, first.at, last.at)
  if (spent <= 0) return null
  const perDollar = rise / spent
  const span = SPEND_RECENT_BY_KIND[kind] ?? SPEND_RECENT_MS
  return (perDollar * spendBetween(events, nowMs - span, nowMs)) / span
}

// 같은 창(리셋 시각이 같은) 안에서 최근 구간의 % 증가 속도 (%/ms).
// % 는 계단으로 움직이므로 구간이 짧으면 최근 길이의 절반으로 늘려 나눈다 (한 계단이 속도를 부풀리지 않게).
export function recentRate(samples: readonly LimitSample[], reset: string | undefined, nowMs: number, kind = 'five_hour'): number | null {
  const span = RECENT_BY_KIND[kind] ?? RECENT_MS
  const s = sameSource(samples.filter(x => x.reset === reset && x.at >= nowMs - span && x.at <= nowMs))
  if (s.length < 2) return null
  const first = s[0]!
  const last = s[s.length - 1]!
  const elapsed = last.at - first.at
  if (elapsed < span / 6) return null
  return Math.max(0, (last.pct - first.pct) / Math.max(elapsed, span / 2))
}

// 같은 계정 · 같은 창의 % 는 줄지 않는다. 앞 표본보다 낮은 값이 오면 다른 계정이 섞인 것이므로 거기서부터 새로 센다.
export function sameSource(samples: readonly LimitSample[]): LimitSample[] {
  const s = [...samples].sort((a, b) => a.at - b.at)
  let start = 0
  for (let i = 1; i < s.length; i++) if (s[i]!.pct < s[i - 1]!.pct) start = i
  return s.slice(start)
}

// 세션의 한도 값은 그 세션이 마지막으로 요청을 보낸 때의 것이다. 하루 쉰 세션은 어제 % 를 들고 있다 (10/9 실측: site 27 % · 실제 39 %).
// 모든 세션이 자기 턴 직후에 적은 표본 중 가장 새것으로 고친다. 같은 창의 % 는 줄지 않으므로 더 큰 값 · 더 늦은 리셋이 새것이다.
export function freshLimits(own: readonly Limit[], samples: Record<string, readonly LimitSample[]>, nowMs: number): Limit[] {
  const out: Limit[] = []
  const kinds = new Set([...own.map(l => l.kind), ...Object.keys(samples)])
  for (const kind of kinds) {
    const mine = own.find(l => l.kind === kind)
    const latest = [...(samples[kind] ?? [])]
      .filter(x => Date.parse(x.reset) > nowMs)
      .sort((a, b) => Date.parse(b.reset) - Date.parse(a.reset) || b.pct - a.pct)[0]
    if (!latest) {
      // 리셋이 지난 내 값은 지난 창의 것이다 (10/12 lead: 쉬는 동안 리셋이 지나 58 % · 빈 괄호). 새 표본이 올 때까지 그리지 않는다
      if (mine && !(mine.resetsAt && Date.parse(mine.resetsAt) <= nowMs)) out.push(mine)
      continue
    }
    const mineReset = mine?.resetsAt ? Date.parse(mine.resetsAt) : 0
    const theirs = Date.parse(latest.reset)
    if (!mine || mineReset < theirs - 60_000 || mineReset <= nowMs) out.push({ kind, percentUsed: latest.pct, resetsAt: latest.reset })
    else if (Math.abs(mineReset - theirs) <= 60_000) out.push({ ...mine, percentUsed: Math.max(mine.percentUsed, latest.pct) })
    else out.push(mine)
  }
  return out
}

export function addSample(samples: readonly LimitSample[], next: LimitSample, keepMs = 2 * RECENT_MS): LimitSample[] {
  const keep = samples.filter(x => x.reset === next.reset && x.at >= next.at - keepMs)
  const last = keep[keep.length - 1]
  if (last && last.pct === next.pct && next.at - last.at < 5 * 60_000) return keep
  return [...keep, next].slice(-400)
}

// 팀장이 계산하지 않아도 한도를 끝까지 쓰게: 지금까지의 평균 속도로 리셋 시점을 내다본다.
// 창의 10 % 도 안 지났으면 속도가 흔들려 내놓지 않는다.
export function pace(l: Limit, nowMs: number, recent: number | null = null, recentBasis: 'spend' | 'recent' = 'recent'): Pace | null {
  const len = WINDOW_MS[l.kind]
  if (!len || !l.resetsAt) return null
  const reset = Date.parse(l.resetsAt)
  if (Number.isNaN(reset) || reset <= nowMs) return null
  let rate: number
  let basis: Pace['basis']
  if (recent !== null) {
    rate = recent
    basis = recentBasis
  } else {
    const elapsed = nowMs - (reset - len)
    if (elapsed < len * 0.1 || l.percentUsed <= 0) return null
    rate = l.percentUsed / elapsed
    basis = 'window'
  }
  const projected = Math.round(l.percentUsed + rate * (reset - nowMs))
  if (l.percentUsed >= 100) return { projected, fullAt: nowMs, basis }
  if (rate <= 0) return { projected, fullAt: null, basis }
  const full = nowMs + (100 - l.percentUsed) / rate
  return { projected, fullAt: full < reset ? Math.round(full) : null, basis }
}

// ---------------------------------------------------------------- 띠 그림

// 계기판이 직접 compact 를 거는 자리 (자동 compact 문턱의 85 %).
export const COMPACT_AT = 85

// 막대 한 줄을 같은 모양끼리 묶은 조각으로. used = 쓴 몫, ahead = 이 속도로 더 쓸 몫,
// mark = 눈금 한 칸 (정리 지점). 글꼴에 기대지 않게 칸은 배경색으로 칠한다.
export type Seg = { kind: 'used' | 'ahead' | 'free' | 'mark'; n: number }

export function gauge(used: number, width: number, ahead: number | null = null, mark: number | null = null): Seg[] {
  const clamp = (p: number) => Math.max(0, Math.min(width, Math.round((p / 100) * width)))
  const u = clamp(used)
  const a = ahead === null ? u : Math.max(u, clamp(ahead))
  const m = mark === null ? -1 : Math.min(width - 1, clamp(mark))
  const cells: Seg['kind'][] = []
  for (let i = 0; i < width; i++) cells.push(i === m && i >= u ? 'mark' : i < u ? 'used' : i < a ? 'ahead' : 'free')
  const out: Seg[] = []
  for (const k of cells) {
    const last = out[out.length - 1]
    if (last && last.kind === k) last.n += 1
    else out.push({ kind: k, n: 1 })
  }
  return out
}

// 한도 판정: 색을 못 가리는 사람도 읽게 낱말과 기호를 함께 낸다. 띠는 누구나 쓰게 영어로.
export type Verdict = { word: string; sign: string; tone: 'success' | 'warning' | 'error' | 'inactive' }

export function verdict(l: Limit, nowMs: number, recent: number | null = null, recentBasis: 'spend' | 'recent' = 'recent'): Verdict {
  if (l.percentUsed >= 100) return { word: 'out', sign: '✕', tone: 'error' }
  const p = pace(l, nowMs, recent, recentBasis)
  if (!p) return { word: 'measuring', sign: '…', tone: 'inactive' }
  if (p.fullAt) return { word: 'short', sign: '✕', tone: 'error' }
  if (p.projected >= 85) return { word: 'tight', sign: '▲', tone: 'warning' }
  return { word: 'enough', sign: '●', tone: 'success' }
}

// 띠의 칸 맞춤. 글자 수가 아니라 화면 칸으로 센다 (한글 · 기호가 섞여도 줄이 맞게).
export function cells(text: string): number {
  let n = 0
  for (const ch of text) {
    const c = ch.codePointAt(0) ?? 0
    n += (c >= 0x1100 && c <= 0x115f) || (c >= 0x2e80 && c <= 0xa4cf) || (c >= 0xac00 && c <= 0xd7a3) || (c >= 0xf900 && c <= 0xfaff) || (c >= 0xff00 && c <= 0xff60) ? 2 : 1
  }
  return n
}

export function pad(text: string, width: number): string {
  const n = cells(text)
  return n >= width ? text : text + ' '.repeat(width - n)
}

export function padStart(text: string, width: number): string {
  const n = cells(text)
  return n >= width ? text : ' '.repeat(width - n) + text
}

// 지금 같은 크기의 턴을 몇 번 더 주고받으면 계기판이 정리(compact)하는가.
export function turnsLeft(tokens: number | null, compactAt: number | null, growth: number | null): number | null {
  if (tokens === null || compactAt === null || !growth || growth <= 0) return null
  return Math.max(0, Math.floor((compactAt - tokens) / growth))
}

// 최근 턴 끝 크기들에서 한 턴에 늘어난 평균. compact 로 줄어든 자리는 뺀다.
export function growthOf(history: readonly number[]): number | null {
  const d: number[] = []
  for (let i = 1; i < history.length; i++) if (history[i]! > history[i - 1]!) d.push(history[i]! - history[i - 1]!)
  // 턴 하나로는 들쭉날쭉하다. 두 번 이상 늘어난 뒤에 낸다.
  if (d.length < 2) return null
  return Math.round(d.reduce((a, b) => a + b, 0) / d.length)
}

// 띠와 문턱이 쓰는 % . 자동 compact 문턱이 있으면 그것 기준, 없으면 창 기준.
export function compactPercent(tokens: number | null, threshold: number | null, windowPercent: number | null): number | null {
  if (tokens !== null && threshold !== null && threshold > 0) return Math.round((tokens / threshold) * 100)
  return windowPercent
}

// 문턱을 넘은 가장 높은 단계. 이미 알린 단계면 0 (같은 알림을 되풀이하지 않는다).
export function crossed(percent: number | null, noted: number, levels: readonly number[] = [75, 85]): number {
  if (percent === null) return 0
  for (const l of [...levels].sort((a, b) => b - a)) if (percent >= l && noted < l) return l
  return 0
}

export function ownStatus(f: SessionFile | null): string {
  if (!f) return ''
  return [
    f.doing ? `하는 일: ${f.doing}` : '',
    f.issues.length ? `이슈: ${f.issues.join(' ')}` : '',
    f.waiting ? `기다리는 것: ${f.waiting}` : '',
    f.next ? `다음: ${f.next}` : '',
  ]
    .filter(Boolean)
    .join('\n')
}

// 끝났거나 12시간 넘게 소식이 없는 세션은 맥락에 넣지 않는다.
export const STALE_MS = 12 * 3_600_000

export function isLive(f: SessionFile, nowMs: number): boolean {
  return !f.endedAt && nowMs - f.updatedAt < STALE_MS
}

export function parseSession(text: string): SessionFile | null {
  try {
    const o = JSON.parse(text) as SessionFile
    if (typeof o?.id !== 'string' || typeof o.updatedAt !== 'number') return null
    return { ...o, issues: Array.isArray(o.issues) ? o.issues : [] }
  } catch {
    return null
  }
}

export function sessionsTable(files: readonly SessionFile[], selfId: string, nowMs: number): string {
  const live = files.filter(f => isLive(f, nowMs)).sort((a, b) => b.updatedAt - a.updatedAt)
  const gone = files.length - live.length
  if (live.length === 0) return '살아 있는 세션 상태 파일이 없습니다.'
  const cell = (s: string) => (s || '-').replace(/\|/g, '/').replace(/\s+/g, ' ')
  const lines = [
    '| 세션 | Orca 핸들 | 하는 일 | 이슈 | 기다리는 것 | 다음 | 컨텍스트 | 갱신 |',
    '|---|---|---|---|---|---|---:|---|',
  ]
  for (const f of live) {
    const out = f.outside ? ` · 밖 ${f.outside}` : ''
    const who = (f.id === selfId ? `**${cell(f.name)}** (이 세션)` : cell(f.name)) + out
    const ctx = f.contextPercent === null ? '-' : `${f.contextPercent}%`
    const status = f.statusAt === null ? ' · 상태 미기재' : ''
    lines.push(
      `| ${who} | ${cell(f.handle ?? '')} | ${cell(f.doing)} | ${cell(f.issues.join(' '))} | ${cell(f.waiting)} | ${cell(f.next)} | ${ctx} | ${duration(nowMs - f.updatedAt)} 전${status} |`,
    )
  }
  if (gone > 0) lines.push('', `끝났거나 12시간 넘게 조용한 세션 ${gone}개는 뺐습니다.`)
  return lines.join('\n')
}

// ---------------------------------------------------------------- 세션 현황

// 다른 세션 한 줄씩. 맥락에 넣는 분량에 상한을 둔다 (팀장 결정 5 · 1,500 토큰 상한).
// 한글은 대략 1 토큰에 1~1.5 자라 보수적으로 1,500 자에서 자른다.
export const OTHERS_CHAR_CAP = 1_500

export function otherSessionsText(
  files: readonly SessionFile[],
  selfId: string,
  nowMs: number,
  cap = OTHERS_CHAR_CAP,
): string {
  const rows = files
    .filter(f => f.id !== selfId && isLive(f, nowMs))
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .map(f => {
      const age = duration(nowMs - f.updatedAt)
      const parts = [
        f.handle ? `${f.name} (${f.handle.slice(0, 13)})` : f.name,
        f.doing || '(하는 일 미기재)',
        f.issues.length ? f.issues.join(' ') : '',
        f.waiting ? `대기: ${f.waiting}` : '',
        f.outside ? `저장소 밖 ${f.outside}` : '',
        `${age} 전`,
      ].filter(Boolean)
      return `- ${parts.join(' · ')}`
    })
  if (rows.length === 0) return ''
  const head = '[다른 세션 · 자세한 것은 /sessions]'
  const out: string[] = [head]
  let used = head.length
  for (const r of rows) {
    if (used + r.length + 1 > cap) {
      out.push(`- …외 ${rows.length - (out.length - 1)}개 (상한)`)
      break
    }
    out.push(r)
    used += r.length + 1
  }
  return out.join('\n')
}

// ---------------------------------------------------------------- 긴 작업의 남은 시간

// 백그라운드 작업이 `PROGRESS i/N` 을 찍는 약속.
export function parseProgress(text: string): { done: number; total: number } | null {
  const all = [...text.matchAll(/PROGRESS\s+(\d+)\s*\/\s*(\d+)/g)]
  const last = all[all.length - 1]
  if (!last) return null
  const done = Number(last[1])
  const total = Number(last[2])
  if (!(total > 0) || done < 0 || done > total) return null
  return { done, total }
}

export function remainingMs(job: Job, nowMs: number): number | null {
  if (!job.progress || job.progress.done <= 0) return null
  const elapsed = nowMs - job.startedAt
  return (elapsed / job.progress.done) * (job.progress.total - job.progress.done)
}

// Bash 결과 글에서 백그라운드 출력 파일 경로를 꺼낸다.
export function outputPath(text: string): string | null {
  const m = text.match(/([A-Za-z]:[\\/][^\s"'`<>|]+\.output)\b/) ?? text.match(/(\/[^\s"'`<>|]+\.output)\b/)
  return m?.[1] ?? null
}

// ---------------------------------------------------------------- 비용 로그

// 「왜 비싼가」: 턴 비용 ≈ 요청 수 × 평균 입력. 캐시가 깨진 요청과 큰 결과를 함께 적는다.
export function whyCostly(e: Extract<CostEvent, { kind: 'turn' }>): string {
  const parts = [`요청 ${e.steps} × 평균 입력 ${compact(e.avgInput)}`]
  if (e.cacheBreaks > 0) parts.push(`캐시 깨짐 ${e.cacheBreaks}회`)
  if (e.topTool) parts.push(`큰 결과 ${e.topTool}`)
  if (e.subagentSteps > 0) parts.push(`하위 에이전트 요청 ${e.subagentSteps}`)
  return parts.join(' · ')
}

export function topTurns(events: readonly CostEvent[], n = 5): Extract<CostEvent, { kind: 'turn' }>[] {
  return events
    .filter((e): e is Extract<CostEvent, { kind: 'turn' }> => e.kind === 'turn')
    .sort((a, b) => b.costUsd - a.costUsd)
    .slice(0, n)
}

export function day(ms: number): string {
  // 기기 시간대 기준 날짜. 엔진 환경에도 Intl 이 있다.
  const d = new Date(ms)
  const p = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// ---------------------------------------------------------------- 작업 단위 기계 기록 (LLM 0 원)

// 커밋 출력의 첫 줄 `[branch abc1234] 제목`. -q 로 조용히 커밋하면 없으므로 git log 로 다시 묻는다.
export function commitFrom(text: string): string | null {
  const m = text.match(/\[[^\]\s]+(?: \([^)]*\))? ([0-9a-f]{7,40})\] (.+)/)
  return m ? `${m[1]!.slice(0, 7)} ${m[2]!.trim()}` : null
}

// 셸 명령이 커밋인가. 그렇다면 어느 폴더의 저장소인가 (-C 나 앞선 cd). 모르면 빈 문자열.
export function commitDir(command: string): string | null {
  if (!/\bgit\b[^;&|]*\bcommit\b/.test(command)) return null
  const c = command.match(/\bgit\s+-C\s+("[^"]+"|'[^']+'|\S+)/)
  const d = c ?? command.match(/(?:^|[;&|]\s*)cd\s+("[^"]+"|'[^']+'|\S+)/)
  return d ? d[1]!.replace(/^["']|["']$/g, '') : ''
}

const LINK = /https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/(?:issues|pull)\/\d+(?:#issuecomment-\d+)?/g

export function linksFrom(text: string): string[] {
  return [...new Set(text.match(LINK) ?? [])]
}

const FILE_TOOLS = new Set(['Edit', 'Write', 'NotebookEdit', 'MultiEdit'])

export function fileOf(tool: string, input: unknown): string | null {
  if (!FILE_TOOLS.has(tool) || typeof input !== 'object' || input === null) return null
  const o = input as Record<string, unknown>
  const p = o.file_path ?? o.notebook_path
  return typeof p === 'string' ? p.replace(/\\/g, '/') : null
}

// ---------------------------------------------------------------- 저장소 밖 쓰기 (막지 않고 기록)

// 비교용 경로: 슬래시로, Git Bash 의 /c/ 를 C:/ 로, 드라이브 글자는 소문자로.
export function normPath(p: string): string {
  let s = p.trim().replace(/^["']|["']$/g, '').replace(/\\/g, '/')
  const m = s.match(/^\/([a-zA-Z])\/(.*)$/)
  if (m) s = `${m[1]}:/${m[2]}`
  s = s.replace(/^([a-zA-Z]):/, (_, d: string) => `${d.toLowerCase()}:`)
  return s.replace(/\/+$/, '')
}

// Orca 터미널 목록의 한 줄 (쓰는 칸만)
export type OrcaTerminal = { handle: string; worktreePath?: string; agentIdentity?: string | null }

// 화면 끝자락에 Claude Code 가 그리는 이름 줄 「──── lead ─」 로 이 세션의 터미널을 찾는다.
// 그 줄이 있는 터미널이 정확히 하나일 때만 돌려준다. 이름이 겹치거나 못 찾으면 null.
export function handleByName(name: string, seen: readonly { handle: string; tail: readonly string[] }[]): string | null {
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const line = new RegExp(`─ ${esc} ─+\\s*$`)
  // 맨 아래 몇 줄만 본다: 위쪽에는 다른 세션 화면을 읽어 온 출력이 섞일 수 있다
  const hits = seen.filter(s => s.tail.slice(-8).some(l => line.test(l)))
  return hits.length === 1 ? hits[0]!.handle : null
}

export function isInside(path: string, root: string): boolean {
  const p = normPath(path).toLowerCase()
  const r = normPath(root).toLowerCase()
  return p === r || p.startsWith(`${r}/`)
}

// 셸 명령에서 «쓰는» 명령이 있을 때만 그 안의 절대 경로를 줍는다. 문자열만 보는 추정이다.
const WRITES = /(^|[\s;&|(])(cp|mv|install|tee|mkdir|touch|rsync|robocopy|xcopy|Copy-Item|Move-Item|New-Item|Set-Content|Add-Content|Out-File|Expand-Archive)\b|>>?\s*\S/i
const ABS = /(?:[A-Za-z]:[\\/]|\/[a-zA-Z]\/)[^\s"'|;&<>]+/g

export function shellWriteTargets(command: string): string[] {
  if (!WRITES.test(command)) return []
  return [...new Set(command.match(ABS) ?? [])].map(normPath)
}

// 밖이면서 예외(임시 폴더 · ~/.mai · ~/.claude)가 아닌 것만.
export function outsideOf(paths: readonly string[], root: string, exempt: readonly string[]): string[] {
  return paths.map(normPath).filter(p => !isInside(p, root) && !exempt.some(x => isInside(p, x)))
}

export function newUnit(doing: string, issues: string[], nowMs: number): Unit {
  return { doing, issues, startedAt: nowMs, endedAt: null, commits: [], files: [], links: [], turns: 0, costUsd: 0 }
}

// 지금 단위에 사실 하나를 더한다. 같은 것은 두 번 넣지 않는다.
export function addTo(unit: Unit, key: 'commits' | 'files' | 'links' | 'outside' | 'risky', items: readonly string[]): Unit {
  const cur = unit[key] ?? []
  const fresh = items.filter(x => x && !cur.includes(x))
  return fresh.length ? { ...unit, [key]: [...cur, ...fresh] } : unit
}

// 상태 도구가 하는 일을 바꾸면 단위가 바뀐다. 처음 적는 doing 은 지금 단위의 이름이 된다.
export function rollUnits(units: readonly Unit[], doing: string | undefined, issues: string[] | undefined, nowMs: number): Unit[] {
  const out = [...units]
  const cur = out[out.length - 1]
  if (!cur || cur.endedAt !== null) {
    out.push(newUnit(doing ?? '', issues ?? [], nowMs))
    return out
  }
  if (doing !== undefined && doing !== '' && cur.doing !== '' && doing !== cur.doing) {
    out[out.length - 1] = { ...cur, endedAt: nowMs }
    out.push(newUnit(doing, issues ?? cur.issues, nowMs))
    return out
  }
  out[out.length - 1] = { ...cur, doing: doing || cur.doing, issues: issues ?? cur.issues }
  return out
}

// 사실만 적는다. 요약은 사람이나 모델이 단위 끝에 한 번 쓴다.
export function unitText(u: Unit, nowMs: number): string {
  const tail = <T,>(xs: readonly T[], n: number) => (xs.length > n ? [`…앞의 ${xs.length - n}개 생략`, ...xs.slice(-n)] : xs)
  const lines = [
    `단위: ${u.doing || '(이름 없음)'}${u.issues.length ? ` · ${u.issues.join(' ')}` : ''} · ${duration((u.endedAt ?? nowMs) - u.startedAt)} · 턴 ${u.turns} · ${usd(u.costUsd)}`,
  ]
  if (u.commits.length) lines.push('커밋:', ...tail(u.commits, 8).map(c => `- ${c}`))
  if (u.links.length) lines.push('남긴 글:', ...tail(u.links, 6).map(l => `- ${l}`))
  // 저장소 밖은 맨 앞에 둔다. 인계에서 빠지면 안 되는 사실이다.
  if (u.outside?.length) lines.splice(1, 0, `저장소 밖에 쓴 자리 ${u.outside.length}곳 (정본은 저장소여야 한다):`, ...tail(u.outside, 6).map(f => `- ${f}`))
  if (u.risky?.length) lines.push(`지우거나 끈 명령 ${u.risky.length}개 (막지 않고 기록):`, ...tail(u.risky, 6).map(c => `- ${c}`))
  if (u.files.length) lines.push(`고친 파일 ${u.files.length}개:`, ...tail(u.files, 10).map(f => `- ${f}`))
  return lines.join('\n')
}

// 주입 예산. 넘치면 조용히 버리지 않고 자른 사실과 원문 자리를 끝에 밝힌다 (obsidian-mind 의 계량 줄).
export function budgeted(text: string, cap: number, pointer: string): string {
  if (text.length <= cap) return text
  const cut = text.slice(0, Math.max(0, cap - pointer.length - 40))
  return `${cut.slice(0, cut.lastIndexOf('\n') > 0 ? cut.lastIndexOf('\n') : cut.length)}\n[주입 ${cap}자 상한으로 ${text.length - cap}자 이상 줄임 · 전부는 ${pointer}]`
}

// ---------------------------------------------------------------- 띠 배치 (폭마다 시험하는 순수 함수)

// 띠에 그릴 재료. register 가 엔진 값에서 모아 넘긴다.
export type BandLimit = { name: string; pct: number; projected: number | null; verdict: Verdict; reset: string; outIn: string | null }
export type BandTurn = { steps: number; cost: number; reads: number; out: number; fresh: number; cacheWrite: number }
export type BandModel = {
  cp: number | null
  tokens: number | null
  window: number
  turnsTo: number | null
  limits: BandLimit[]
  totalCost: number | null
  turn: BandTurn | null
  job: string | null
  current: string | null
  outside: number
}

// 턴 비용을 「어디에 썼나」로 나눈다. 합은 실제 턴 비용과 같고, 나누는 비율은 표준 단가 비율
// (새 입력 1 · 캐시 쓰기 1.25 · 캐시 읽기 0.1 · 출력 5) 을 쓴 추정이다.
export const PRICE_RATIO = { fresh: 1, cacheWrite: 1.25, read: 0.1, out: 5 }

export function splitCost(t: BandTurn): { reads: number; out: number; fresh: number } {
  const w = {
    reads: t.reads * PRICE_RATIO.read,
    out: t.out * PRICE_RATIO.out,
    fresh: t.fresh * PRICE_RATIO.fresh + t.cacheWrite * PRICE_RATIO.cacheWrite,
  }
  const sum = w.reads + w.out + w.fresh
  if (sum <= 0) return { reads: 0, out: 0, fresh: 0 }
  return { reads: (t.cost * w.reads) / sum, out: (t.cost * w.out) / sum, fresh: (t.cost * w.fresh) / sum }
}

// 한 칸 조각. tone 은 테마 이름, dim 은 흐리게. fill 은 남은 폭을 채우다 넘치면 자르는 마지막 조각.
export type Piece = { t: string; tone?: string; dim?: boolean; bold?: boolean; fill?: boolean }

const BARS = { used: '━', ahead: '╍', free: '─', mark: '┃' }

function barPieces(used: number, width: number, tone: string, ahead: number | null, mark: number | null): Piece[] {
  return gauge(used, width, ahead, mark).map(g =>
    g.kind === 'used'
      ? { t: BARS.used.repeat(g.n), tone }
      : g.kind === 'ahead'
        ? { t: BARS.ahead.repeat(g.n), tone, dim: true }
        : g.kind === 'mark'
          ? { t: BARS.mark, tone: 'text' }
          : { t: BARS.free.repeat(g.n), dim: true },
  )
}

// 칸 (모든 줄이 같은 세로선을 지킨다):
//   이름 9 | 값 13 (막대, turn 은 이번 턴 비용) | 수치 16 (% · 토큰 · 예상, turn 은 요청 수) | 판정 · 내역 | total
// 폭이 좁으면 막대가 빠지고(값 칸은 그대로 비용), turn 내역은 덜 중요한 것부터 통째로 뺀다. 잘라 버리지 않는다.
export function bandRows(m: BandModel, cols: number): Piece[][] {
  const bar = cols >= 56 ? 12 : 0
  const LABEL = 9
  const VALUE = bar > 0 ? bar + 1 : 0
  const NUM = cols >= 48 ? 16 : 5
  const rows: Piece[][] = []

  const row = (label: string, pct: number | null, tone: string, ahead: number | null, mark: number | null, mid: string, say: string, sayTone: string) => {
    const r: Piece[] = [{ t: pad(label, LABEL), dim: true }]
    if (bar > 0) r.push(...barPieces(pct ?? 0, bar, tone, ahead, mark), { t: ' ' })
    r.push({ t: padStart(pct === null ? '-' : `${pct}%`, 4), tone, bold: true }, { t: ' ' })
    if (NUM > 5) r.push({ t: pad(mid, NUM - 5), dim: true })
    r.push({ t: say, tone: sayTone === 'text' ? undefined : sayTone, fill: true })
    rows.push(r)
  }

  const ctxSay =
    m.cp === null
      ? '… no reply yet'
      : m.cp >= COMPACT_AT
        ? '▲ compact after this turn'
        : m.turnsTo === null
          ? `● compact at ${COMPACT_AT}%`
          : m.turnsTo > 50
            ? '● compact in 50+ turns'
            : `${m.turnsTo <= 3 ? '▲' : '●'} compact in ~${m.turnsTo} turns`
  row(
    'context',
    m.cp,
    m.cp === null ? 'inactive' : level(m.cp),
    null,
    COMPACT_AT,
    m.tokens === null ? '' : `${compact(m.tokens)}/${compact(m.window)}`,
    ctxSay,
    m.cp !== null && (m.cp >= COMPACT_AT || (m.turnsTo !== null && m.turnsTo <= 3)) ? 'warning' : 'text',
  )
  if (m.limits.length > 0) {
    for (const name of ['5 hours', '7 days']) {
      const l = m.limits.find(x => x.name === name)
      if (!l) {
        row(name, null, 'inactive', null, null, '', '… no data yet', 'inactive')
        continue
      }
      const v = l.verdict
      row(
        l.name,
        l.pct,
        v.tone,
        l.projected === null ? null : Math.min(100, l.projected),
        null,
        l.projected === null ? '' : l.projected > 200 ? '[>200%]' : `[~${l.projected}%]`,
        v.word === 'short' && l.outIn ? `${v.sign} short, out in ${l.outIn}` : l.reset ? `${v.sign} ${v.word} (${l.reset})` : `${v.sign} ${v.word}`,
        v.tone,
      )
    }
  }

  // turn: 위 줄들과 같은 세로선. 막대 칸에 이번 턴 비용, 괄호 칸에 세션 합계(위의 [~51%] 처럼 「더 큰 수」),
  // 판정 칸에 ● 요청 수 · 어디에 썼나 (돈 많이 쓴 순). 폭이 모자라면 가장 싼 것부터, 그다음 금액을 뺀다.
  const turnCost = m.turn ? usd(m.turn.cost) : '-'
  const r: Piece[] = [{ t: pad('turn', LABEL), dim: true }]
  r.push({ t: VALUE > 0 ? pad(turnCost, VALUE) : `${turnCost} `, bold: true })
  r.push({ t: '     ' })
  const bracket = m.totalCost !== null ? `[${usd(m.totalCost)}]` : ''
  if (NUM > 5) r.push({ t: pad(bracket, NUM - 5), dim: true })
  else if (bracket) r.push({ t: `${bracket} `, dim: true })
  const used = r.reduce((n, x) => n + cells(x.t), 0)
  let say = '… no turn yet'
  if (m.turn) {
    const c = splitCost(m.turn)
    const parts = [
      { name: 'reads', tokens: m.turn.reads, cost: c.reads },
      { name: 'out', tokens: m.turn.out, cost: c.out },
      { name: 'new', tokens: m.turn.fresh + m.turn.cacheWrite, cost: c.fresh },
    ].sort((x, y) => y.cost - x.cost)
    const req = `${m.turn.steps} req`
    const withCost = parts.map(x => `${x.name} ${compact(x.tokens)} ${usd(x.cost)}`)
    const bare = parts.map(x => `${x.name} ${compact(x.tokens)}`)
    const tries = [
      [req, ...withCost],
      [req, ...withCost.slice(0, 2)],
      [req, ...bare.slice(0, 2)],
      [req, ...bare.slice(0, 1)],
      [req],
    ]
    say = `● ${req}`
    for (const t of tries) {
      const text = `● ${t.join(' · ')}`
      if (used + cells(text) <= cols) {
        say = text
        break
      }
    }
  }
  r.push({ t: say, dim: !m.turn, fill: true })
  rows.push(r)

  // now: 알릴 것이 있을 때만. 경고가 맨 앞이라 잘려도 경고는 남는다.
  const now: Piece[] = []
  if (m.outside > 0) now.push({ t: `▲ outside repo ${m.outside}`, tone: 'warning' })
  if (m.current) now.push({ t: `${now.length ? ' · ' : ''}${m.current}`, tone: 'suggestion', fill: true })
  if (m.job) now.push({ t: `${now.length ? ' · ' : ''}${m.job}`, dim: true, fill: true })
  if (now.length > 0) {
    rows.push([{ t: pad('now', LABEL), dim: true }, ...now])
  }
  return rows
}

// 조각들이 차지하는 칸. fill 조각은 잘리므로 시험에서 뺀다.
export function fixedCells(r: readonly Piece[]): number {
  return r.filter(p => !p.fill).reduce((n, p) => n + cells(p.t), 0)
}
