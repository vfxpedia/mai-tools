import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, TurnStepResult } from 'claude-code'

import type { CostEvent, CostLog, Job, Limit, SessionFile, TurnTally, Unit, UnitLog, Usage } from '../types'
import type { Piece } from './lib'
import {
  type OrcaTerminal,
  handleByName,
  normPath,
  addTo,
  budgeted,
  commitDir,
  commitFrom,
  fileOf,
  outsideOf,
  shellWriteTargets,
  linksFrom,
  rollUnits,
  unitText,
  attribute,
  bar,
  brief,
  compact,
  compactInstructions,
  compactPercent,
  crossed,
  blockingKind,
  notedKind,
  scratchTargets,
  day,
  duration,
  holdReason,
  pace,
  gauge,
  verdict,
  turnsLeft,
  growthOf,
  COMPACT_AT,
  recentRate,
  addSample,
  RECENT_BY_KIND,
  RECENT_MS,
  freshLimits,
  KEEP_BY_KIND,
  spendRate,
  pad,
  bandRows,
  splitCost,
  isCacheBreak,
  otherSessionsText,
  outputPath,
  ownStatus,
  parseProgress,
  parseSession,
  remainingMs,
  sessionsTable,
  thresholdNote,
  topTurns,
  untilReset,
  usd,
  whyCostly,
  level,
} from './lib'

// 프롬프트 위 띠와 명령이 읽는 값. 모듈 변수와 달리 다시 불러와도 남는다.
const usageAtom = atom({ plugin: 'mai-gauge', key: 'usage' } as const, null)
const turnAtom = atom({ plugin: 'mai-gauge', key: 'turn' } as const, null)
const toolsAtom = atom({ plugin: 'mai-gauge', key: 'tools' } as const, {})
const currentAtom = atom({ plugin: 'mai-gauge', key: 'current' } as const, null)
const hiddenAtom = atom({ plugin: 'mai-gauge', key: 'hidden' } as const, false)
const heldAtom = atom({ plugin: 'mai-gauge', key: 'held' } as const, null)
const allowOnceAtom = atom({ plugin: 'mai-gauge', key: 'allowOnce' } as const, null)
const jobsAtom = atom({ plugin: 'mai-gauge', key: 'jobs' } as const, [])
const outsideAtom = atom({ plugin: 'mai-gauge', key: 'outside' } as const, 0)
const growthAtom = atom({ plugin: 'mai-gauge', key: 'growth' } as const, null)
const samplesAtom = atom({ plugin: 'mai-gauge', key: 'samples' } as const, {})
const spendAtom = atom({ plugin: 'mai-gauge', key: 'spend' } as const, [])

const STATUS_TOOL: string = 'mcp__mai-gauge__session_status'
const SHELLS = new Set(['Bash', 'PowerShell'])

const LIMIT_NAMES: Record<string, string> = {
  five_hour: '5시간',
  seven_day: '7일',
  spend_limit: '지출',
}

// ---------------------------------------------------------------- 요청 사이를 잇는 값

type Tracker = {
  prevInput: number | null
  prevOutput: number
  prevTools: string[]
  prevCost: number | null
  // 이번 턴의 비용 로그 재료
  prompt: string
  turnCostStart: number | null
  inputSum: number
  cacheBreaks: number
  subagentSteps: number
  turnTools: Record<string, number>
  // 이미 알린 문턱 (75 · 85). compact 뒤 0 으로 돌아간다.
  noted: number
  toasted: number
  // 이 세션의 상태 파일과 비용 로그
  me: SessionFile | null
  log: CostLog | null
  logDay: string
  // 작업 단위 기계 기록. 바뀔 때마다 파일을 통째로 다시 쓴다.
  units: UnitLog | null
  // 85 % 턴 사이 compact 를 이미 걸었는가. compact 뒤 false 로 돌아간다.
  compactAsked: boolean
  // 이미 알린 한도 소진 예고 (창 종류와 리셋 시각)
  paceWarned: string[]
  // 입력창에 채울 다시 실행 문장. 명령 · 단추 처리 안에서 못 채우면 타이머가 꺼내 채운다
  rerun: string | null
  rerunTries: number
  // 최근 턴 끝의 컨텍스트 크기 (정리까지 몇 번 남았나를 셈)
  ctxHist: number[]
}

// 다시 불러오면 모듈 변수가 처음부터 시작하므로 session.start 에서 파일로 되살린다.
function fresh(): Tracker {
  return {
    prevInput: null,
    prevOutput: 0,
    prevTools: [],
    prevCost: null,
    prompt: '',
    turnCostStart: null,
    inputSum: 0,
    cacheBreaks: 0,
    subagentSteps: 0,
    turnTools: {},
    noted: 0,
    toasted: 0,
    me: null,
    log: null,
    logDay: '',
    units: null,
    compactAsked: false,
    paceWarned: [],
    rerun: null,
    rerunTries: 0,
    ctxHist: [],
  }
}

// ---------------------------------------------------------------- 엔진을 부르는 함수 (최상위에 둔다)

async function home($: EngineInterface): Promise<string> {
  const h = (await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME')) ?? '.'
  return `${h.replace(/\\/g, '/')}/.mai`
}

async function readUsage($: EngineInterface, threshold: number | null): Promise<Usage> {
  const u = await $.session.usage()
  const limits: Limit[] = u.rateLimits.map(r => ({
    kind: r.kind,
    percentUsed: r.percentUsed,
    resetsAt: r.resetsAt,
  }))
  return {
    tokens: u.context.tokens ?? null,
    window: u.context.window,
    percent: u.context.percent ?? null,
    costUsd: u.cost?.usd ?? null,
    limits,
    threshold,
  }
}

// 자동 compact 문턱. 요청을 보내지 않는 추정 (`summary`).
async function readThreshold($: EngineInterface): Promise<number | null> {
  const u = await $.session.usage({ breakdown: 'summary' })
  const b = u.context.breakdown
  if (!b || !b.isAutoCompactEnabled) return null
  return b.autoCompactThreshold ?? null
}

async function refresh($: EngineInterface): Promise<Usage> {
  let threshold: number | null = null
  try {
    threshold = await readThreshold($)
  } catch {
    // 문턱을 못 읽으면 창 기준으로 그린다.
  }
  const u = await readUsage($, threshold)
  await update($, usageAtom, () => u)
  return u
}

async function listSessions($: EngineInterface): Promise<SessionFile[]> {
  const dir = `${await home($)}/sessions`
  if (!(await $.fs.exists(dir))) return []
  const out: SessionFile[] = []
  for (const f of await $.fs.list(dir)) {
    if (f.kind !== 'file' || !f.name.endsWith('.json')) continue
    try {
      const s = parseSession(await $.fs.read(`${dir}/${f.name}`))
      if (s) out.push(s)
    } catch {
      // 다른 세션이 쓰는 중이면 이번엔 건너뛴다.
    }
  }
  return out
}

// 이 세션의 상태 파일을 만들거나 갱신한다. /clear 뒤에는 id 가 바뀌어 새 파일이 된다.
async function saveSession($: EngineInterface, tr: Tracker, patch: Partial<SessionFile>): Promise<SessionFile> {
  const id = await $.session.id()
  const now = await $.clock.now()
  const dir = `${await home($)}/sessions`
  if (!tr.me || tr.me.id !== id) {
    let prior: SessionFile | null = null
    try {
      if (await $.fs.exists(`${dir}/${id}.json`)) prior = parseSession(await $.fs.read(`${dir}/${id}.json`))
    } catch {
      prior = null
    }
    const cwd = await $.session.cwd()
    const repo = await $.session.repo()
    tr.me = prior ?? {
      id,
      name: repo?.name ?? cwd.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? 'session',
      handle: (await $.env.get('ORCA_TERMINAL_HANDLE')) ?? null,
      cwd,
      repo: repo?.root ?? null,
      doing: '',
      issues: [],
      waiting: '',
      next: '',
      contextPercent: null,
      startedAt: now,
      updatedAt: now,
      statusAt: null,
    }
  }
  tr.me = { ...tr.me, ...patch, id, updatedAt: now }
  await $.fs.write(`${dir}/${id}.json`, JSON.stringify(tr.me, null, 2))
  return tr.me
}

// 상태판의 Orca 핸들은 세션이 처음 적힐 때 환경 변수에서 읽은 값이다. Orca 가 창을 다시 붙이면 새 핸들이 나와
// 옛 값으로 말을 걸면 거절되거나 엉뚱한 곳으로 간다 (10/9 · 10/12 lead 실측, #33 B22).
// 지금 핸들이 살아 있는지 Orca 에 묻고, 낡았으면 같은 폴더의 claude 터미널 화면에서 이 세션 이름 줄을 찾아 고친다.
// 하나로 못 좁히면 핸들을 비운다: 틀린 핸들보다 없는 핸들이 낫다.
async function checkHandle($: EngineInterface, tr: Tracker): Promise<void> {
  const me = tr.me ?? (await saveSession($, tr, {}))
  const orca = async (args: string[]): Promise<Record<string, unknown> | null> => {
    const r = await $.process.run(['orca', ...args, '--json'], { timeoutMs: 10_000 })
    try {
      return JSON.parse(r.stdout) as Record<string, unknown>
    } catch {
      return null
    }
  }
  if (me.handle) {
    const shown = await orca(['terminal', 'show', '--terminal', me.handle])
    if (shown === null) return // Orca 밖이거나 Orca 가 꺼져 있다. 판단하지 않는다
    if (shown.ok === true) return
  }
  const listed = await orca(['terminal', 'list'])
  const all = ((listed?.result as { terminals?: OrcaTerminal[] } | undefined)?.terminals ?? []).filter(t => t.agentIdentity === 'claude')
  const here = normPath(me.repo ?? me.cwd).toLowerCase()
  const near = all.filter(t => t.worktreePath && normPath(t.worktreePath).toLowerCase() === here)
  const seen: { handle: string; tail: string[] }[] = []
  for (const t of near.length > 0 ? near : all) {
    const read = await orca(['terminal', 'read', '--terminal', t.handle])
    const tail = (read?.result as { terminal?: { tail?: string[] } } | undefined)?.terminal?.tail
    if (tail) seen.push({ handle: t.handle, tail })
  }
  const found = handleByName(me.name, seen)
  if (found !== me.handle) await saveSession($, tr, { handle: found })
}

// 비용 로그는 세션·날짜마다 파일 하나. $.fs.write 는 덧붙이기가 없어 통째로 다시 쓴다.
async function logCost($: EngineInterface, tr: Tracker, ev: CostEvent): Promise<void> {
  const id = await $.session.id()
  const d = day(ev.at)
  const path = `${await home($)}/costlog/${d}/${id}.json`
  if (!tr.log || tr.log.sessionId !== id || tr.logDay !== d) {
    tr.log = { sessionId: id, name: tr.me?.name ?? id, account: await account($), events: [] }
    try {
      if (await $.fs.exists(path)) {
        const prior = JSON.parse(await $.fs.read(path)) as CostLog
        if (Array.isArray(prior.events)) tr.log.events = prior.events
      }
    } catch {
      // 깨진 로그는 새로 시작한다.
    }
    tr.logDay = d
  }
  tr.log = { ...tr.log, name: tr.me?.name ?? tr.log.name, events: [...tr.log.events, ev] }
  await $.fs.write(path, JSON.stringify(tr.log))
}

// 한 걸음(모델 요청) 끝마다 사용량을 더한다. 1.3.2 에서 계정 함수 account 와 이름이 겹쳐 덮였고, 10/9 04:47 부터 턴 집계가 사흘간 멈췄다
async function tallyStep($: EngineInterface, tr: Tracker, r: TurnStepResult, agentId: string | undefined): Promise<void> {
  const u = r.usage
  const prior = await read($, usageAtom)
  const now = await readUsage($, prior?.threshold ?? null)
  await update($, usageAtom, () => now)
  if (!u) return

  const input = u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens
  const stepCost =
    tr.prevCost !== null && now.costUsd !== null ? Math.max(0, now.costUsd - tr.prevCost) : 0
  tr.prevCost = now.costUsd
  if (isCacheBreak(input, u.cache_creation_input_tokens)) tr.cacheBreaks += 1

  // 하위 에이전트의 요청은 본 대화의 입력 사슬과 섞지 않는다. 비용과 횟수만 센다.
  if (agentId) {
    tr.subagentSteps += 1
  } else {
    if (tr.prevInput !== null && tr.prevTools.length > 0) {
      const added = input - tr.prevInput - tr.prevOutput
      const share = input > 0 ? stepCost * (Math.max(0, added) / input) : 0
      const tools = tr.prevTools
      await update($, toolsAtom, t => attribute(t, tools, added, share))
      for (const name of tools) tr.turnTools[name] = (tr.turnTools[name] ?? 0) + Math.max(0, added) / tools.length
    }
    tr.prevInput = input
    tr.prevOutput = u.output_tokens
    tr.prevTools = r.toolUses.map(t => t.name)
  }
  tr.inputSum += input

  await update($, turnAtom, t => {
    const base: TurnTally = t ?? { steps: 0, input: 0, output: 0, cacheRead: 0, costUsd: 0 }
    return {
      steps: base.steps + 1,
      input: base.input + u.input_tokens + u.cache_creation_input_tokens,
      cacheWrite: (base.cacheWrite ?? 0) + u.cache_creation_input_tokens,
      output: base.output + u.output_tokens,
      cacheRead: base.cacheRead + u.cache_read_input_tokens,
      costUsd: base.costUsd + stepCost,
    }
  })
}

async function unitPath($: EngineInterface): Promise<string> {
  return `${await home($)}/units/${await $.session.id()}.json`
}

// 지금 세션의 단위 기록을 불러온다. 다시 불러오거나 resume 해도 파일에서 이어진다.
async function loadUnits($: EngineInterface, tr: Tracker): Promise<UnitLog> {
  const id = await $.session.id()
  if (tr.units && tr.units.sessionId === id) return tr.units
  let units: Unit[] = []
  try {
    const path = await unitPath($)
    if (await $.fs.exists(path)) {
      const prior = JSON.parse(await $.fs.read(path)) as UnitLog
      if (Array.isArray(prior.units)) units = prior.units
    }
  } catch {
    units = []
  }
  tr.units = { sessionId: id, name: tr.me?.name ?? id, units }
  return tr.units
}

// 단위 기록을 고친다. fn 은 지금 단위(없으면 새로 연 단위)를 받는다.
async function editUnit($: EngineInterface, tr: Tracker, fn: (u: Unit) => Unit): Promise<void> {
  const log = await loadUnits($, tr)
  const now = await $.clock.now()
  const units = rollUnits(log.units, undefined, undefined, now)
  const last = units.length - 1
  const changed = fn(units[last]!)
  if (changed === units[last] && units.length === log.units.length) return
  units[last] = changed
  tr.units = { ...log, name: tr.me?.name ?? log.name, units }
  await $.fs.write(await unitPath($), JSON.stringify(tr.units, null, 1))
}

async function currentUnitText($: EngineInterface, tr: Tracker): Promise<string> {
  const log = await loadUnits($, tr)
  const cur = log.units[log.units.length - 1]
  if (!cur || cur.endedAt !== null) return ''
  return unitText(cur, await $.clock.now())
}

// 셸 결과에서 커밋 · 남긴 글을 줍는다. -q 커밋은 출력이 없어 그 저장소에 git log 로 묻는다.
async function harvest($: EngineInterface, tr: Tracker, command: string, text: string): Promise<void> {
  const links = linksFrom(text)
  let commit = commitFrom(text)
  const dir = commitDir(command)
  if (!commit && dir !== null) {
    const cwd = dir || (await $.session.cwd())
    const r = await $.process.run(['git', '-C', cwd, 'log', '-1', '--format=%h %s'], { timeoutMs: 5_000 })
    if (r.exitCode === 0 && r.stdout.trim()) commit = r.stdout.trim()
  }
  if (!commit && links.length === 0) return
  await editUnit($, tr, u => addTo(addTo(u, 'commits', commit ? [commit] : []), 'links', links))
}

// 세션의 저장소와 예외 자리. 저장소가 아니면 열린 폴더가 그 세션의 자리다.
async function roots($: EngineInterface): Promise<{ root: string; exempt: string[] }> {
  const repo = await $.session.repo()
  const root = repo?.root ?? (await $.session.cwd())
  const h = ((await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME')) ?? '').replace(/\\/g, '/')
  const exempt = [`${h}/.mai`, `${h}/.claude`, `${h}/AppData/Local/Temp`, '/tmp']
  // 엔진은 읽는 환경 변수를 글자 그대로 적어야 받는다 (모드가 무엇을 읽는지 목록이 남게).
  const temp = await $.env.get('TEMP')
  const tmp = await $.env.get('TMP')
  for (const v of [temp, tmp]) if (v) exempt.push(v)
  return { root, exempt }
}

// 저장소 밖에 쓴 자리를 기록하고 알린다. 막지 않는다 (작업이 끊기면 안 된다).
async function noteOutside($: EngineInterface, tr: Tracker, paths: readonly string[]): Promise<void> {
  const { root, exempt } = await roots($)
  const out = outsideOf(paths, root, exempt)
  if (out.length === 0) return
  let count = 0
  await editUnit($, tr, u => {
    const next = addTo(u, 'outside', out)
    count = next.outside?.length ?? 0
    return next
  })
  await update($, outsideAtom, () => count)
  await saveSession($, tr, { outside: count })
  $.ui.toast(`저장소 밖에 씀: ${out[0]}${out.length > 1 ? ` 외 ${out.length - 1}` : ''}`)
}

async function finishTurn($: EngineInterface, tr: Tracker, durationMs: number): Promise<number | null> {
  const u = await refresh($)
  const cp = compactPercent(u.tokens, u.threshold, u.percent)
  await saveSession($, tr, { contextPercent: cp })
  try {
    await recordSamples($, u)
  } catch {
    // 표본을 못 적으면 창 평균으로 내다본다.
  }
  if (u.tokens !== null) {
    tr.ctxHist = [...tr.ctxHist.slice(-6), u.tokens]
    const g = growthOf(tr.ctxHist)
    if (g !== null) await update($, growthAtom, () => g)
  }

  // 한도: 이 속도면 리셋 전에 바닥나는 창을 한 번 알린다 (아끼라는 뜻이 아니라 중단 시점을 미리 보라는 뜻).
  const nowMs = await $.clock.now()
  const samples = await read($, samplesAtom)
  const spend = await read($, spendAtom)
  for (const l of freshLimits(u.limits, samples, nowMs)) {
    const ro = rateOf(samples, spend, l, nowMs)
    const p = pace(l, nowMs, ro.rate, ro.basis)
    const key = `${l.kind}:${l.resetsAt ?? ''}`
    if (p?.fullAt && !tr.paceWarned.includes(key)) {
      tr.paceWarned = [...tr.paceWarned.slice(-9), key]
      $.ui.toast(`${LIMIT_NAMES[l.kind] ?? l.kind} 한도가 이 속도면 ${duration(p.fullAt - nowMs)} 뒤 바닥납니다 (리셋까지 ${untilReset(l.resetsAt, nowMs)})`)
    }
  }

  // 50 % 는 1차 정리: 기계 기록이 이미 파일에 있으니 LLM 을 부르지 않고 알리기만 한다.
  const step = crossed(cp, tr.toasted, [50, 75, 85])
  if (step) {
    tr.toasted = step
    $.ui.toast(
      step === 50
        ? `컨텍스트 ${cp}% · 1차 정리: 이번 단위의 커밋 · 글 · 파일이 단위 기록에 있습니다`
        : `컨텍스트가 자동 compact 문턱의 ${cp}% 입니다`,
    )
  }

  const turn = await read($, turnAtom)
  if (!turn || turn.steps === 0) return cp
  const cost = turn.costUsd
  await editUnit($, tr, x => ({ ...x, turns: x.turns + 1, costUsd: x.costUsd + cost }))
  const top = Object.entries(tr.turnTools).sort((a, b) => b[1] - a[1])[0]
  await logCost($, tr, {
    kind: 'turn',
    at: await $.clock.now(),
    prompt: tr.prompt,
    steps: turn.steps,
    avgInput: Math.round(tr.inputSum / turn.steps),
    costUsd: turn.costUsd,
    cacheBreaks: tr.cacheBreaks,
    topTool: top && top[1] >= 5_000 ? `${top[0]} ${compact(top[1])}` : null,
    subagentSteps: tr.subagentSteps,
    durationMs,
  })
  return cp
}

// 백그라운드 출력 파일 끝에서 `PROGRESS i/N` 을 읽는다. 아주 큰 파일은 읽지 않는다.
async function pollJobs($: EngineInterface): Promise<void> {
  const jobs = await read($, jobsAtom)
  if (jobs.length === 0) return
  const now = await $.clock.now()
  const next: Job[] = []
  let changed = false
  for (const j of jobs) {
    try {
      const st = await $.fs.stat(j.path)
      // 30분 동안 출력이 안 늘면 끝난 것으로 본다.
      if (now - st.mtimeMs > 30 * 60_000) {
        changed = true
        continue
      }
      if (st.mtimeMs <= j.updatedAt || st.size > 5_000_000) {
        next.push(j)
        continue
      }
      const p = parseProgress((await $.fs.read(j.path)).slice(-4_000))
      changed = true
      if (p && p.done >= p.total) continue
      next.push({ ...j, progress: p ?? j.progress, updatedAt: st.mtimeMs })
    } catch {
      changed = true // 파일이 사라졌다
    }
  }
  if (changed) await update($, jobsAtom, () => next)
}

async function gaugeText($: EngineInterface): Promise<string> {
  const u = await refresh($)
  const turn = await read($, turnAtom)
  const tools = await read($, toolsAtom)
  const nowMs = await $.clock.now()
  const cp = compactPercent(u.tokens, u.threshold, u.percent)
  const NAMES: Record<string, string> = { five_hour: '5 hours', seven_day: '7 days', spend_limit: 'spend' }

  // 띠와 같은 낱말 · 같은 순서. 띠가 한 줄로 줄인 것을 여기서 풀어 쓴다.
  const lines: string[] = ['## Context']
  if (u.tokens === null) {
    lines.push(`Not known until the first reply · window ${compact(u.window)}`)
  } else if (u.threshold !== null) {
    const point = (u.threshold * COMPACT_AT) / 100
    lines.push(
      `${compact(u.tokens)} / ${compact(u.window)} window (${u.percent}%) · ${cp}% of the auto-compact point ${compact(u.threshold)}`,
      `mai-gauge compacts between turns at ${COMPACT_AT}% (${compact(point)}): ${compact(Math.max(0, point - u.tokens))} to go`,
    )
  } else {
    lines.push(`${compact(u.tokens)} / ${compact(u.window)} window (${u.percent}%) · auto-compact off, mai-gauge compacts at ${COMPACT_AT}% of the window`)
  }
  const fresh = freshLimits(u.limits, await read($, samplesAtom), nowMs)
  if (fresh.length > 0) {
    lines.push('', '## Limits (shared by every session on this account)')
    const samples = await read($, samplesAtom)
    const spend = await read($, spendAtom)
    for (const l of fresh) {
      const ro = rateOf(samples, spend, l, nowMs)
      const p = pace(l, nowMs, ro.rate, ro.basis)
      const v = verdict(l, nowMs, ro.rate, ro.basis)
      const left = untilReset(l.resetsAt, nowMs)
      const BASIS = {
        spend: `spending of the last ${l.kind === 'seven_day' ? '3 h' : '15 min'} (all sessions)`,
        recent: `rise of the last ${l.kind === 'seven_day' ? '6 h' : '30 min'}`,
        window: 'average pace of this window',
      }
      const basis = p ? BASIS[p.basis] : ''
      const ahead = p
        ? ` · at the ${basis}: ~${p.projected}% at reset${p.fullAt ? `, runs out in ${duration(p.fullAt - nowMs)}` : ''}`
        : ' · pace not known yet'
      lines.push(`${NAMES[l.kind] ?? l.kind}: ${l.percentUsed}% used · resets in ${left || '?'}${ahead} · ${v.sign} ${v.word}`)
    }
  }
  lines.push('', '## Cost')
  if (u.costUsd !== null) lines.push(`total (this session) ${usd(u.costUsd)}`)
  if (turn) {
    const avg = turn.steps > 0 ? (turn.input + turn.cacheRead) / turn.steps : 0
    lines.push(
      `this turn ${usd(turn.costUsd)} · ${turn.steps} request${turn.steps === 1 ? '' : 's'} · avg input ${compact(avg)} · new input ${compact(turn.input)} · cache read ${compact(turn.cacheRead)} · out ${compact(turn.output)}`,
    )
    const c = splitCost({ steps: turn.steps, cost: turn.costUsd, reads: turn.cacheRead, out: turn.output, fresh: Math.max(0, turn.input - (turn.cacheWrite ?? 0)), cacheWrite: turn.cacheWrite ?? 0 })
    lines.push(
      `where it went (est.): reads ${usd(c.reads)} · out ${usd(c.out)} · new ${usd(c.fresh)}. The sum is the real turn cost; the split uses standard price ratios (cache read 0.1 · cache write 1.25 · output 5 × input).`,
    )
  }
  const rows = Object.entries(tools).sort((a, b) => b[1].resultTokens - a[1].resultTokens)
  if (rows.length > 0) {
    lines.push(
      '',
      '## Tools (this session, since mai-gauge loaded)',
      '',
      '| tool | calls | tokens added (est.) | cost share (est.) |',
      '|---|---:|---:|---:|',
    )
    for (const [name, t] of rows.slice(0, 15)) {
      lines.push(`| ${name} | ${t.calls} | ${compact(t.resultTokens)} | ${usd(t.costUsd)} |`)
    }
    lines.push('', 'tokens added = next request input - this request input - this request output, split evenly across tools in one request. cost share = that share of the request that first read them.')
  }
  return lines.join('\n')
}

async function costlogText($: EngineInterface, arg: string): Promise<string> {
  const d = /^\d{4}-\d{2}-\d{2}$/.test(arg) ? arg : day(await $.clock.now())
  const dir = `${await home($)}/costlog/${d}`
  if (!(await $.fs.exists(dir))) return `${d} 의 비용 로그가 없습니다.`
  const logs: CostLog[] = []
  for (const f of await $.fs.list(dir)) {
    if (f.kind !== 'file' || !f.name.endsWith('.json')) continue
    try {
      const l = JSON.parse(await $.fs.read(`${dir}/${f.name}`)) as CostLog
      if (Array.isArray(l.events)) logs.push(l)
    } catch {
      // 쓰는 중인 파일은 건너뛴다.
    }
  }
  const turnsOf = (l: CostLog) => l.events.filter((e): e is Extract<CostEvent, { kind: 'turn' }> => e.kind === 'turn')
  const sum = (l: CostLog) => turnsOf(l).reduce((s, e) => s + e.costUsd, 0)
  const total = logs.reduce((s, l) => s + sum(l), 0)

  const lines = [`## ${d} 비용 · 세션 ${logs.length}개 · 합계 ${usd(total)}`, '']
  lines.push('| 세션 | 턴 | 비용 | compact |', '|---|---:|---:|---:|')
  for (const l of [...logs].sort((a, b) => sum(b) - sum(a))) {
    const compacts = l.events.filter(e => e.kind === 'compact').length
    lines.push(`| ${l.name} | ${turnsOf(l).length} | ${usd(sum(l))} | ${compacts} |`)
  }
  const all = logs.flatMap(l => l.events.map(e => ({ e, name: l.name })))
  const top = topTurns(all.map(x => x.e), 5)
  if (top.length > 0) {
    lines.push('', '## 비싼 턴 다섯', '', '| 세션 | 비용 | 왜 비싼가 | 프롬프트 |', '|---|---:|---|---|')
    for (const t of top) {
      const name = all.find(x => x.e === t)?.name ?? ''
      lines.push(`| ${name} | ${usd(t.costUsd)} | ${whyCostly(t)} | ${t.prompt.replace(/\|/g, '/')} |`)
    }
    lines.push('', '턴 비용 ≈ 요청 수 × 평균 입력. 캐시 깨짐은 새로 쓴 캐시가 입력의 절반을 넘은 요청입니다.')
  }
  return lines.join('\n')
}

// 모델이 부르는 상태 갱신 도구의 답. 안 준 칸은 그대로 둔다.
async function answerStatus($: EngineInterface, tr: Tracker, o: Record<string, unknown>): Promise<string> {
  const str = (k: string) => (typeof o[k] === 'string' ? (o[k] as string).slice(0, 200) : undefined)
  const patch: Partial<SessionFile> = { statusAt: await $.clock.now() }
  for (const k of ['name', 'doing', 'waiting', 'next'] as const) {
    const v = str(k)
    if (v !== undefined) patch[k] = v
  }
  // 팀장이 붙인 이름은 모델이 덮지 않는다.
  if (tr.me?.titled) delete patch.name
  const issues = o.issues
  if (Array.isArray(issues)) patch.issues = issues.filter((x): x is string => typeof x === 'string').slice(0, 10)
  const me = await saveSession($, tr, patch)
  // 하는 일이 바뀌면 단위를 닫고 새로 연다.
  const log = await loadUnits($, tr)
  tr.units = { ...log, name: me.name, units: rollUnits(log.units, patch.doing, patch.issues, await $.clock.now()) }
  await $.fs.write(await unitPath($), JSON.stringify(tr.units, null, 1))
  const others = otherSessionsText(await listSessions($), me.id, await $.clock.now())
  return `상태를 적었습니다.\n${ownStatus(me)}\n\n${others || '다른 세션 상태 파일이 없습니다.'}`
}

// 세션 이름은 팀장이 /rename 으로 붙인 제목이 첫째다. 엔진이 세션 시작과 프롬프트마다 넘기므로
// 중간에 이름을 바꿔도 다음 프롬프트에서 따라간다. 제목이 없으면 폴더 이름 그대로 둔다.
async function applyTitle($: EngineInterface, tr: Tracker, title: unknown): Promise<void> {
  if (typeof title !== 'string') return
  const t = title.replace(/\s+/g, ' ').trim().slice(0, 60)
  if (!t) return
  if (tr.me && tr.me.id === (await $.session.id()) && tr.me.name === t && tr.me.titled) return
  await saveSession($, tr, { name: t, titled: true })
}

async function haikuTest($: EngineInterface, tr: Tracker): Promise<string> {
  const msgs = await $.session.messages()
  const body = msgs
    .map(m => {
      const tools = m.toolUses.map(t => t.tool).join(', ')
      return `[${m.role}] ${m.text}${tools ? ` (도구: ${tools})` : ''}`
    })
    .join('\n\n')
  const before = (await $.session.usage()).cost?.usd ?? null
  const started = await $.clock.now()
  const r = await $.model.complete({
    model: 'haiku',
    system: '너는 긴 작업 대화를 다음 세션이 이어 갈 수 있게 요약한다. 결정 · 수치 · 근거(커밋 · 이슈 · 파일) · 남은 일을 빠짐없이 남긴다.',
    prompt: `${compactInstructions(`${await home($)}/sessions/${await $.session.id()}.json`, ownStatus(tr.me))}\n\n[대화]\n${body}`,
    maxTokens: 8_000,
  })
  const after = (await $.session.usage()).cost?.usd ?? null
  const ms = (await $.clock.now()) - started
  const cost = before !== null && after !== null ? usd(after - before) : '미확인'
  if (!r.isAnswered) {
    return `Haiku 요약 실패: ${r.reason}${'status' in r && r.status ? ` ${r.status}` : ''} · 대화 ${msgs.length}개 · ${body.length.toLocaleString()}자 · 비용 증가 ${cost}`
  }
  const path = `${await home($)}/costlog/${day(started)}/haiku-test-${await $.session.id()}-${started}.md`
  await $.fs.write(path, r.text)
  return [
    `Haiku 요약 시험 (대화는 바꾸지 않음)`,
    `- 넣은 대화: 메시지 ${msgs.length}개 · ${body.length.toLocaleString()}자`,
    `- 토큰: 입력 ${compact(r.usage.input_tokens)} · 캐시 읽기 ${compact(r.usage.cache_read_input_tokens)} · 출력 ${compact(r.usage.output_tokens)}`,
    `- 세션 비용 증가 ${cost} · ${Math.round(ms / 1000)}초`,
    `- 요약 ${r.text.length.toLocaleString()}자 · 전문 ${path}`,
  ].join('\n')
}

// 다시 실행은 팀장이 Enter 로 보낸다. 계기판이 직접 보내면 자동 모드 분류기가 「승인 우회」로 막는다
// (10/9 test 세션 실측). 사람 대신 위험 명령을 시키지 않는 그 안전장치를 피하지 않는다.
async function sendRerun($: EngineInterface, tr: Tracker): Promise<void> {
  const text = tr.rerun
  if (!text) return
  let filled = false
  try {
    filled = (await $.prompt.fill({ text, mode: 'replace' })).isFilled
  } catch {
    filled = false
  }
  if (filled) {
    tr.rerun = null
    tr.rerunTries = 0
    $.ui.toast('입력창에 다시 실행 문장을 넣었습니다. Enter 만 누르세요.')
    return
  }
  // 대화창이 열려 있는 등 지금 못 채우면 타이머가 몇 번 더 해 본다.
  tr.rerunTries += 1
  if (tr.rerunTries >= 5) {
    tr.rerun = null
    tr.rerunTries = 0
    $.ui.toast('입력창에 넣지 못했습니다. 다시 실행하라고 말해 주세요.')
  }
}

type Samples = Record<string, { at: number; pct: number; reset: string }[]>

// 계정 구분. 두 계정이 한 설정 폴더에 동시에 로그인할 수 없으므로 CLAUDE_CONFIG_DIR 가 계정을 가른다 (10/9: 계정이 섞여 7일 예측이 >200% 가 됨).
async function account($: EngineInterface): Promise<string> {
  const d = await $.env.get('CLAUDE_CONFIG_DIR')
  return d ? d.replace(/[\\]/g, '/').toLowerCase() : 'default'
}

async function loadShared($: EngineInterface): Promise<void> {
  const path = `${await home($)}/limits.json`
  if (!(await $.fs.exists(path))) return
  const file = JSON.parse(await $.fs.read(path)) as Record<string, Samples>
  const acct = await account($)
  await update($, samplesAtom, () => file[acct] ?? {})
  const ev = await readSpend($, await $.clock.now(), acct)
  await update($, spendAtom, () => ev)
}

// 자기 턴이 끝난 직후에만 부른다: 그때의 한도 값은 방금 받은 응답의 것이라 새것이다.
async function recordSamples($: EngineInterface, u: Usage): Promise<void> {
  if (u.limits.length === 0) return
  const path = `${await home($)}/limits.json`
  // 파일은 계정마다 칸을 나눈다: { 계정: { 창 종류: 표본[] } }. 옛 모양(계정 칸 없음)은 버린다.
  let file: Record<string, Samples> = {}
  try {
    if (await $.fs.exists(path)) file = JSON.parse(await $.fs.read(path)) as Record<string, Samples>
  } catch {
    file = {}
  }
  for (const k of Object.keys(file)) if (Array.isArray((file as Record<string, unknown>)[k])) delete file[k]
  const acct = await account($)
  const all: Samples = file[acct] ?? {}
  const now = await $.clock.now()
  for (const l of u.limits) {
    if (!l.resetsAt) continue
    all[l.kind] = addSample(all[l.kind] ?? [], { at: now, pct: l.percentUsed, reset: l.resetsAt }, KEEP_BY_KIND[l.kind] ?? 2 * (RECENT_BY_KIND[l.kind] ?? RECENT_MS))
  }
  file[acct] = all
  await $.fs.write(path, JSON.stringify(file))
  await update($, samplesAtom, () => all)
  try {
    await update($, spendAtom, () => [])
    const ev = await readSpend($, now, acct)
    await update($, spendAtom, () => ev)
  } catch {
    // 비용 기록을 못 읽으면 % 기울기로 내다본다.
  }
}

// 모든 세션의 오늘 · 어제 비용 기록에서 (시각, 비용) 만 모은다. 모델을 부르지 않는다.
async function readSpend($: EngineInterface, now: number, acct: string): Promise<{ at: number; cost: number }[]> {
  const out: { at: number; cost: number }[] = []
  const base = `${await home($)}/costlog`
  for (const d of [day(now), day(now - 86_400_000)]) {
    const dir = `${base}/${d}`
    if (!(await $.fs.exists(dir))) continue
    for (const f of await $.fs.list(dir)) {
      if (f.kind !== 'file' || !f.name.endsWith('.json') || f.name.startsWith('haiku-test')) continue
      try {
        const log = JSON.parse(await $.fs.read(`${dir}/${f.name}`)) as CostLog
        // 다른 계정 세션의 비용은 이 계정 한도와 상관없다. 계정 표시가 없는 옛 기록은 쓰지 않는다
        if (log.account !== acct) continue
        for (const e of log.events ?? []) {
          const cost = (e as { costUsd?: number | null }).costUsd
          if (typeof cost === 'number' && cost > 0 && e.at > now - 86_400_000) out.push({ at: e.at, cost })
        }
      } catch {
        // 다른 세션이 쓰는 중이면 건너뛴다.
      }
    }
  }
  return out
}

// 가장 촘촘한 근거부터: 비용 기반 → % 기울기. 둘 다 없으면 pace 가 창 평균을 쓴다.
function rateOf(samples: Samples, spend: { at: number; cost: number }[], l: Limit, nowMs: number): { rate: number | null; basis: 'spend' | 'recent' } {
  const s = spendRate(samples[l.kind] ?? [], l.resetsAt, spend, nowMs, l.kind)
  if (s !== null) return { rate: s, basis: 'spend' }
  return { rate: recentRate(samples[l.kind] ?? [], l.resetsAt, nowMs, l.kind), basis: 'recent' }
}

// 세션 자기 임시 자리: $CLAUDE_JOB_DIR/tmp 와 이 세션의 scratchpad. 다른 세션 · 저장소 · 실험 결과는 들지 않는다.
async function scratchRoots($: EngineInterface, tr: Tracker): Promise<{ roots: string[]; env: Record<string, string> }> {
  const id = await $.session.id()
  const h = ((await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME')) ?? '').replace(/\\/g, '/')
  // 엔진 환경에 없으면 Claude Code 가 쓰는 자리 (~/.claude/jobs/<세션 id 앞 8자>) 로 푼다 (lead 실측 jobs/09bbf294).
  const job = ((await $.env.get('CLAUDE_JOB_DIR')) ?? (h ? `${h}/.claude/jobs/${id.slice(0, 8)}` : '')).replace(/\\/g, '/')
  const temp = ((await $.env.get('TEMP')) ?? '').replace(/\\/g, '/')
  const start = (tr.me?.cwd ?? (await $.session.cwd())).replace(/[^A-Za-z0-9]/g, '-')
  const roots: string[] = []
  if (job) roots.push(`${job}/tmp`)
  if (temp) roots.push(`${temp}/claude/${start}/${id}/scratchpad`)
  return { roots, env: job ? { CLAUDE_JOB_DIR: job } : {} }
}

// 지울 대상이 전부 자기 임시 자리 안이면 보류하지 않는다. 단 git worktree(.git 이 파일)는 다른 저장소에 묶여 있어 여전히 보류.
async function ownScratchOnly($: EngineInterface, tr: Tracker, command: string): Promise<boolean> {
  try {
    const { roots, env } = await scratchRoots($, tr)
    const targets = scratchTargets(command, roots, env)
    if (!targets) return false
    for (const t of targets) {
      const root = roots.find(r => t.toLowerCase().startsWith(`${normPath(r).toLowerCase()}/`))
      if (!root) return false
      for (let p = t; p.length > normPath(root).length; p = p.slice(0, p.lastIndexOf('/'))) {
        try {
          if ((await $.fs.read(`${p}/.git`)).startsWith('gitdir:')) return false
        } catch {
          // .git 이 없거나 폴더(받은 사본)다
        }
      }
    }
    return true
  } catch {
    return false
  }
}

async function noteRisky($: EngineInterface, tr: Tracker, kind: string, command: string): Promise<void> {
  try {
    const line = `${kind}: ${command.replace(/\s+/g, ' ').slice(0, 140)}`
    await editUnit($, tr, u => addTo(u, 'risky', [line]))
    $.ui.toast(`기록함 (막지 않음): ${line.slice(0, 80)}`)
  } catch {
    // 기록을 못 해도 명령은 간다
  }
}

async function onPressAllow($: EngineInterface, tr: Tracker): Promise<void> {
  const held = await read($, heldAtom)
  if (!held) return
  // 모델은 명령을 조금씩 바꿔 다시 낸다 (; echo 를 붙이는 식). 그래서 글자가 아니라 위험 종류로 10 분 안 한 번.
  await update($, allowOnceAtom, () => ({ kind: held.kind, until: Date.now() + 10 * 60_000 }))
  await update($, heldAtom, () => null)
  // 팀장이 다시 쓰지 않아도 되게 입력창에 문장을 채운다. 곧바로 못 채우면 타이머가 채운다.
  // 「다시 실행해」로 시키면 그사이 다른 길로 끝낸 일도 그대로 다시 돌린다 (10/12 lead · super 두 번).
  tr.rerun =
    `보류됐던 ${held.kind} 명령을 허용했다 (10 분 안 한 번). 아직 필요하면 다시 실행하고, ` +
    `그사이 다른 방법으로 끝냈으면 실행하지 말고 넘어가라: ${held.command.slice(0, 200)}`
  await sendRerun($, tr)
}

// ---------------------------------------------------------------- 훅

export const register: Register = on => {
  const tr = fresh()

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'gauge',
      description: '컨텍스트 · 한도 · 이번 턴 · 도구별 토큰과 비용을 표로 본다 (/gauge hide · show · allow · close)',
    })
    await $.command.register({ name: 'sessions', description: '이 기기에서 도는 세션들의 상태판' })
    await $.command.register({ name: 'costlog', description: '오늘(또는 /costlog YYYY-MM-DD) 세션별 비용과 비싼 턴' })
    await $.tool.register({
      name: 'session_status',
      description:
        '이 세션의 상태판 줄을 갱신한다. 다른 세션들이 이것을 맥락으로 읽는다. ' +
        '작업 단위를 시작하거나 끝낼 때, 기다리는 것이 생기거나 풀릴 때 부른다. ' +
        '안 준 칸은 그대로 둔다. 다른 세션들의 현재 상태를 돌려준다.',
      inputSchema: {
        type: 'object',
        properties: {
          name: { type: 'string', description: '세션 이름 (super · rl · lead 처럼 짧게)' },
          doing: { type: 'string', description: '지금 하는 일 한 줄' },
          issues: { type: 'array', items: { type: 'string' }, description: '잡은 이슈 (예: owner/repo#12)' },
          waiting: { type: 'string', description: '누구의 무엇을 기다리는지. 없으면 빈 문자열' },
          next: { type: 'string', description: '다음 할 일 한 줄' },
        },
      },
    })
    const u = await refresh($)
    tr.prevCost = u.costUsd
    try {
      await loadShared($)
    } catch {
      // 공유 표본이 없으면 자기 값으로 그린다.
    }
    try {
      await saveSession($, tr, {})
    } catch {
      // 상태 파일을 못 써도 세션은 시작한다.
    }
    checkHandle($, tr).catch(() => {})
    $.clock.every(5 * 60_000, () => checkHandle($, tr).catch(() => {}))
    $.clock.every(20_000, () => pollJobs($).catch(() => {}))
    // 쉬는 세션의 한도 값은 낡았으므로 적지 않는다. 다른 세션이 적은 것을 1 분마다 읽기만 한다
    $.clock.every(60_000, () => loadShared($).catch(() => {}))
    $.clock.every(2_000, () => sendRerun($, tr).catch(() => {}))
    return next(e)
  })

  on('classic.SessionStart', async ($, e, next) => {
    try {
      await applyTitle($, tr, e.session_title)
    } catch {
      // 이름을 못 적어도 세션은 시작한다.
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('classic.UserPromptSubmit', async ($, e, next) => {
    try {
      await applyTitle($, tr, e.session_title)
    } catch {
      // 이름을 못 적어도 프롬프트는 간다.
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    try {
      if (tr.me && tr.me.id === e.sessionId) await saveSession($, tr, { endedAt: await $.clock.now() })
    } catch {
      // 못 적으면 12시간 뒤 조용한 세션으로 빠진다.
    }
    return next(e)
  })

  // 다른 세션 한 줄씩. 대화의 첫 메시지에, 그리고 compact 뒤 다시 읽혀 들어간다 (팀장 결정 5).
  on('prompt.context', async ($, e, next) => {
    const r = await next(e)
    const files = await listSessions($)
    const others = otherSessionsText(files, await $.session.id(), await $.clock.now())
    // compact 뒤 다시 읽힐 때 이 세션이 하던 단위의 사실이 함께 들어간다 (예산 1,000 자, 넘치면 파일 자리를 밝힌다).
    const unit = await currentUnitText($, tr)
    const text = [
      `이 세션의 상태는 ${STATUS_TOOL} 로 갱신한다. 다른 세션들이 그것을 읽는다.`,
      unit ? budgeted(`[이 세션이 하던 단위]\n${unit}`, 1_000, await unitPath($)) : '',
      others,
    ]
      .filter(Boolean)
      .join('\n')
    return { ...r, blocks: [...r.blocks, { name: 'maiSessions', text }] }
  }).catch(($, e, next) => next(e))

  on('prompt.submit', async ($, e, next) => {
    // 턴의 첫 요청에는 사용자 프롬프트가 더해지므로 앞 요청의 도구와 잇지 않는다.
    tr.prevTools = []
    tr.prompt = e.text.replace(/\s+/g, ' ').trim().slice(0, 60)
    tr.inputSum = 0
    tr.cacheBreaks = 0
    tr.subagentSteps = 0
    tr.turnTools = {}
    await update($, turnAtom, () => ({ steps: 0, input: 0, output: 0, cacheRead: 0, costUsd: 0 }))

    // 75 · 85 % 를 처음 넘은 프롬프트 끝에 한 줄 (팀장 결정 2).
    const u = await read($, usageAtom)
    const cp = u ? compactPercent(u.tokens, u.threshold, u.percent) : null
    const step = crossed(cp, tr.noted)
    if (step && cp !== null) {
      tr.noted = step
      return next({ ...e, text: e.text + thresholdNote(step, cp, STATUS_TOOL, await unitPath($)) })
    }
    return next(e)
  }).catch(($, e, next) => next(e)) // 계기판이 실패해도 프롬프트는 간다

  on('session.compact', async ($, e, next) => {
    if (e.agentId) return next(e)
    const path = `${await home($)}/sessions/${await $.session.id()}.json`
    let facts = ''
    try {
      facts = budgeted(await currentUnitText($, tr), 2_000, await unitPath($))
    } catch {
      facts = ''
    }
    const instructions = [e.instructions, compactInstructions(path, ownStatus(tr.me), facts)].filter(Boolean).join('\n\n')
    let costBefore: number | null = null
    try {
      costBefore = (await $.session.usage()).cost?.usd ?? null
    } catch {
      costBefore = null
    }
    const r = await next({ ...e, instructions })
    if (r.skip !== undefined) return r
    if (e.trigger !== 'precompute') {
      tr.noted = 0
      tr.toasted = 0
      tr.prevInput = null
      tr.compactAsked = false
      tr.ctxHist = []
      try {
        const after = (await $.session.usage()).cost?.usd ?? null
        await logCost($, tr, {
          kind: 'compact',
          at: await $.clock.now(),
          trigger: e.trigger,
          tokensBefore: r.tokensBefore ?? null,
          tokensAfter: r.tokensAfter ?? null,
          usage: r.usage
            ? {
                input: r.usage.input_tokens,
                output: r.usage.output_tokens,
                cacheRead: r.usage.cache_read_input_tokens,
                cacheWrite: r.usage.cache_creation_input_tokens,
              }
            : null,
          costUsd: costBefore !== null && after !== null ? Math.round((after - costBefore) * 10_000) / 10_000 : null,
        })
        const u = await refresh($)
        // 엔진의 사용량은 다음 요청 전까지 compact 전 값이라 띠가 그대로 남는다. 엔진이 잰 compact 뒤 크기로 바로 고친다.
        if (typeof r.tokensAfter === 'number') {
          const t = r.tokensAfter
          await update($, usageAtom, () => ({ ...u, tokens: t, percent: Math.round((t / u.window) * 100) }))
        }
      } catch {
        // 기록을 못 해도 compact 는 선다.
      }
    }
    return r
  }).catch(($, e, next) => next(e))

  // 위험 명령 보류 (팀장 결정 · ask 는 자동 모드에서 분류기로 가므로 deny 로 확실히 사람에게 돌린다).
  on('tool.check', async ($, e, next) => {
    if (e.tool === STATUS_TOOL) return { decision: 'allow' as const }
    if (!SHELLS.has(e.tool)) return next(e)
    const command = (e.input as { command?: unknown } | null)?.command
    if (typeof command !== 'string') return next(e)
    const kind = blockingKind(command)
    if (!kind) {
      // 지우기 · 프로세스 종료는 막지 않고 단위 기록과 띠 알림으로 남긴다. 자기 임시 자리 삭제는 기록할 거리도 아니다.
      const noted = notedKind(command)
      if (noted && !(await ownScratchOnly($, tr, command))) await noteRisky($, tr, noted, command)
      return next(e)
    }
    const once = await read($, allowOnceAtom)
    if (once && once.kind === kind && Date.now() <= once.until) {
      await update($, allowOnceAtom, () => null)
      return next(e)
    }
    await update($, heldAtom, () => ({ kind, command }))
    $.ui.toast(`위험 명령을 보류했습니다: ${kind} · 허용은 띠 단추나 /gauge allow`)
    return { decision: 'deny' as const, reason: holdReason(kind) }
  }).catch(($, e, next) => next(e)) // 계기판이 깨져도 도구는 엔진의 권한 판단으로 간다 (작업이 멈추지 않게)

  on('tool.call', async ($, e, next) => {
    // 상태 도구는 매처 없는 tool.call 을 둘 걸 수 없어 여기서 가른다 (이름이 엔진 타입에 실리기 전).
    if (e.tool === STATUS_TOOL) {
      const result = await answerStatus($, tr, e as unknown as Record<string, unknown>)
      return { result } as Awaited<ReturnType<typeof next>>
    }
    const label = [e.tool, brief(e)].filter(Boolean).join(' ')
    await update($, currentAtom, () => label)
    try {
      const r = await next(e)
      // 도구가 돈 뒤의 기록. 여기서 던지면 아래 .catch 가 도구를 한 번 더 돌리므로 반드시 삼킨다.
      try {
        const text = 'text' in r && typeof r.text === 'string' ? r.text : ''
        const bg = (e as { run_in_background?: unknown }).run_in_background === true
        const command = (e as { command?: unknown }).command
        if (bg && SHELLS.has(e.tool)) {
          // 백그라운드 명령은 출력 파일을 기억해 PROGRESS i/N 을 읽는다.
          const path = outputPath(text)
          if (path) {
            const now = await $.clock.now()
            const label = brief(e)
            await update($, jobsAtom, jobs => [
              ...jobs.filter(j => j.path !== path),
              { id: e.tool_use_id, command: label, path, startedAt: now, progress: null, updatedAt: 0 },
            ])
          }
        } else if (SHELLS.has(e.tool) && typeof command === 'string' && !r.isError) {
          await harvest($, tr, command, text)
        }
        const file = r.isError || r.deny !== undefined ? null : fileOf(e.tool, e)
        if (file) await editUnit($, tr, u => addTo(u, 'files', [file]))
        const shellPaths =
          SHELLS.has(e.tool) && typeof command === 'string' && !r.isError ? shellWriteTargets(command) : []
        if (file || shellPaths.length) await noteOutside($, tr, [...(file ? [file] : []), ...shellPaths])
      } catch {
        // 기록을 못 해도 도구 결과는 그대로 간다.
      }
      return r
    } finally {
      await update($, currentAtom, () => null)
    }
  }).catch(($, e, next) => next(e)) // 계기판이 실패해도 도구는 돈다

  on('turn.step', async function* ($, e, next) {
    const r: TurnStepResult = yield* next(e)
    try {
      await tallyStep($, tr, r, e.agentId)
    } catch {
      // 계기판이 셈을 못 해도 응답은 그대로 간다.
    }
    return r
  })

  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (!e.agentId) {
      let cp: number | null = null
      try {
        cp = await finishTurn($, tr, e.durationMs)
      } catch {
        // 기록을 못 해도 턴은 끝난다. compact 판정은 기록과 떼어 다시 잰다.
        try {
          const u = await refresh($)
          cp = compactPercent(u.tokens, u.threshold, u.percent)
        } catch {
          cp = null
        }
      }
      // 85 %: 도구가 도는 중이 아니라 턴이 끝난 자리에서 계기판이 직접 compact 한다 (팀장 목적 1).
      if (cp !== null && cp >= COMPACT_AT && !tr.compactAsked) {
        tr.compactAsked = true
        $.ui.toast(`컨텍스트 ${cp}% · 턴 사이에서 compact 합니다`)
        void $.session.compact({}).catch(() => {
          tr.compactAsked = false
          $.ui.toast('compact 를 걸지 못했습니다. /compact 를 직접 쳐 주세요.')
        })
      }
    }
    return r
  })

  on('command.run', { command: 'gauge' }, async ($, e) => {
    // 인자 없이 부르면 args 가 비어 올 수 있다 (시험이 잡았다).
    const arg = (e.args ?? '').trim()
    // 단추를 못 누르는 화면(Orca 모바일 등)에서도 글자로 같은 일을 한다.
    if (arg === 'allow') {
      if (!(await read($, heldAtom))) return { text: '보류된 명령이 없습니다.' }
      await onPressAllow($, tr)
      return { text: '보류된 명령을 한 번 허용했습니다. 입력창의 다시 실행 문장을 Enter 로 보내세요.' }
    }
    if (arg === 'close') {
      await update($, heldAtom, () => null)
      return { text: '보류 띠를 닫았습니다. 명령은 계속 막혀 있습니다.' }
    }
    // 시험: 지금 대화를 Haiku 로 요약해 보고 비용 · 크기를 잰다. 대화는 바꾸지 않는다 (#33 B5).
    if (arg === 'haiku-test') return { text: await haikuTest($, tr) }
    if (arg === 'hide' || arg === 'show') {
      await update($, hiddenAtom, () => arg === 'hide')
      return { text: arg === 'hide' ? '계기판 띠를 숨겼습니다. /gauge show 로 다시 켭니다.' : '계기판 띠를 켰습니다.' }
    }
    return { text: await gaugeText($) }
  })

  on('command.run', { command: 'sessions' }, async $ => {
    const files = await listSessions($)
    return { text: sessionsTable(files, await $.session.id(), await $.clock.now()) }
  })

  on('command.run', { command: 'costlog' }, async ($, e) => {
    return { text: await costlogText($, (e.args ?? '').trim()) }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const u = await read($, usageAtom)
    if (e.props.hasSurvey || u === null || (await read($, hiddenAtom))) return next(e)

    const turn = await read($, turnAtom)
    const current = await read($, currentAtom)
    const held = await read($, heldAtom)
    const jobs = await read($, jobsAtom)
    const outside = await read($, outsideAtom)
    const nowMs = await $.clock.now()
    const { Box, Button, Text } = $.ui.resolve(e)

    const cp = compactPercent(u.tokens, u.threshold, u.percent)
    const job = jobs
      .map(j => {
        if (!j.progress) return `progress ${j.command.slice(0, 20)}`
        const ms = remainingMs(j, nowMs)
        return `progress ${j.progress.done}/${j.progress.total}${ms !== null ? ` [${duration(ms)}]` : ''}`
      })
      .join(' | ')
    const growth = await read($, growthAtom)
    const samples = await read($, samplesAtom)
    const spend = await read($, spendAtom)
    const point = u.tokens !== null ? ((u.threshold ?? u.window) * COMPACT_AT) / 100 : null
    const NAMES: Record<string, string> = { five_hour: '5 hours', seven_day: '7 days', spend_limit: 'spend' }

    // 배치는 lib 의 bandRows 가 정한다 (폭마다 시험). 여기서는 조각을 글자로 옮기기만 한다.
    const rows = bandRows(
      {
        cp,
        tokens: u.tokens,
        window: u.window,
        turnsTo: turnsLeft(u.tokens, point, growth),
        limits: freshLimits(u.limits, samples, nowMs)
          .filter(l => NAMES[l.kind])
          .map(l => {
            const ro = rateOf(samples, spend, l, nowMs)
            const p = pace(l, nowMs, ro.rate, ro.basis)
            return {
              name: NAMES[l.kind]!,
              pct: Math.round(l.percentUsed),
              projected: p ? p.projected : null,
              verdict: verdict(l, nowMs, ro.rate, ro.basis),
              reset: untilReset(l.resetsAt, nowMs),
              outIn: p?.fullAt ? duration(p.fullAt - nowMs) : null,
            }
          }),
        totalCost: u.costUsd,
        turn:
          turn && turn.steps > 0
            ? {
                steps: turn.steps,
                cost: turn.costUsd,
                reads: turn.cacheRead,
                out: turn.output,
                fresh: Math.max(0, turn.input - (turn.cacheWrite ?? 0)),
                cacheWrite: turn.cacheWrite ?? 0,
              }
            : null,
        job: job || null,
        current: current ?? null,
        outside,
      },
      e.props.bodyColumns,
    )
    // 고정 조각(이름 · 막대 · % · 비용)은 줄어들지 않게, 뒤의 설명만 폭이 모자라면 잘린다.
    const draw = (r: Piece[], key: string) =>
      r.map((p, i) => (
        <Box key={`${key}${i}`} flexShrink={p.fill ? 1 : 0}>
          <Text color={p.tone} dimColor={p.dim} bold={p.bold} wrap={p.fill ? 'truncate-end' : undefined}>
            {p.t}
          </Text>
        </Box>
      ))
    // 보류가 있으면 now 줄 자리에 보류 줄과 단추를 띄운다. 비용 줄은 가리지 않는다.
    const shown = held ? rows.filter(r => r[0]?.t.trim() !== 'now') : rows

    return (
      <Box flexDirection="column">
        {shown.map((r, i) => (
          <Box key={`r${i}`}>{draw(r, `r${i}`)}</Box>
        ))}
        {held ? (
          <Box>
            <Text color="error" wrap="truncate-end">
              {pad('held', 9)}
              {held.kind}: {held.command.slice(0, 60)}{' '}
            </Text>
            <Button key="allow" label="Allow once" onPress={() => onPressAllow($, tr)} />
            <Button key="dismiss" label="Dismiss" onPress={() => update($, heldAtom, () => null)} />
          </Box>
        ) : null}
      </Box>
    )
  })
}
