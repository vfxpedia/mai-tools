import { describe, expect, mock, test } from 'claude-code/testing'
// 시험 실행기에는 있지만 모드 형식 정의에는 없는 전역
declare const setTimeout: (f: (v?: unknown) => void, ms: number) => unknown
import type { On } from 'claude-code'

import type { SessionFile } from '../types'
import {
  attribute,
  bar,
  compactInstructions,
  compactPercent,
  crossed,
  dangerous,
  scratchTargets,
  level,
  OTHERS_CHAR_CAP,
  otherSessionsText,
  pace,
  gauge as segs,
  recentRate,
  addSample,
  bandRows,
  fixedCells,
  splitCost,
  spendRate,
  spendBetween,
  sameSource,
  freshLimits,
  handleByName,
  verdict,
  turnsLeft,
  growthOf,
  parseProgress,
  remainingMs,
  sessionsTable,
  thresholdNote,
  untilReset,
  whyCostly,
} from '../hooks/lib'
import { addTo, budgeted, commitDir, commitFrom, fileOf, linksFrom, newUnit, rollUnits, unitText } from '../hooks/lib'
import { isInside, normPath, outsideOf, shellWriteTargets } from '../hooks/lib'

const NOW = Date.parse('2026-10-07T00:00:00Z')

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 4,
  bodyColumns: 120,
  scroll: { offset: 0, bodyRows: 40 },
  view: {},
}
const BAND = { component: 'AbovePrompt' as const, props: PROPS }

// 사람이 터미널에서 /gauge 를 친 것과 같은 실행.
function gauge(args = '') {
  return {
    command: 'gauge',
    args,
    origin: { kind: 'composer' as const },
    presentation: { isFullscreen: true, columns: 120 },
  }
}

// 엔진 아래에서 session.usage 와 clock 을 대신 답한다. threshold 가 있으면 자동 compact 가 켜진 세션.
function world(on: On, tokens = 780_000, threshold: number | null = null) {
  const clock = mock.clock(on, { now: NOW })
  on('session.usage', async ($, e) => ({
    value: {
      startedAt: 0,
      context: {
        tokens,
        window: 1_000_000,
        percent: Math.round(tokens / 10_000),
        ...(e?.breakdown
          ? {
              breakdown: {
                isAutoCompactEnabled: threshold !== null,
                ...(threshold !== null ? { autoCompactThreshold: threshold } : {}),
              },
            }
          : {}),
      },
      rateLimits: [
        { kind: 'five_hour', percentUsed: 10, resetsAt: new Date(NOW + (3 * 60 + 31) * 60_000).toISOString() },
        { kind: 'seven_day', percentUsed: 35, resetsAt: new Date(NOW + (3 * 24 + 23) * 3_600_000).toISOString() },
      ],
      cost: { usd: 3.2 },
    },
  }) as never)
  return clock
}

// 모드가 비켜서면(next) 엔진이 그리는 것이 보여야 한다. 시험에서는 엔진 대신 표식을 그린다.
function engineBeneath(on: On) {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine">ENGINE</Text>
  })
}

// 엔진의 권한 판단 대신: 위험하지 않으면 허용.
function permitBeneath(on: On) {
  on('tool.check', async () => ({ decision: 'allow' as const }))
}

function session(over: Partial<SessionFile>): SessionFile {
  return {
    id: 'x',
    name: 'x',
    handle: null,
    cwd: 'C:/w',
    repo: null,
    doing: '',
    issues: [],
    waiting: '',
    next: '',
    contextPercent: null,
    startedAt: NOW - 3_600_000,
    updatedAt: NOW - 60_000,
    statusAt: null,
    ...over,
  }
}

describe('도구별 토큰 나누기 (추정 규칙)', () => {
  test('결과 토큰은 다음 요청 입력에서 이번 입력과 출력을 뺀 것을 도구 수로 똑같이 나눈다', async () => {
    // 입력 100k -> 다음 입력 130k, 그 사이 출력 2k: 결과 28k 를 Read 둘이 14k 씩
    const got = attribute({}, ['Read', 'Read'], 130_000 - 100_000 - 2_000, 0.4)
    expect(got.Read?.calls).toBe(2)
    expect(got.Read?.resultTokens).toBe(28_000)
    expect(got.Read?.costUsd).toBe(0.4)
  })

  test('도구를 안 부른 요청은 아무것도 더하지 않는다', async () => {
    const before = { Bash: { calls: 3, resultTokens: 900, costUsd: 0.01 } }
    expect(attribute(before, [], 5_000, 1)).toEqual(before)
  })

  test('compact 로 입력이 줄면 음수를 쌓지 않는다', async () => {
    expect(attribute({}, ['Bash'], -200_000, -1).Bash).toEqual({ calls: 1, resultTokens: 0, costUsd: 0 })
  })
})

describe('자동 compact 문턱 (결정 2 · 3)', () => {
  test('문턱이 있으면 문턱 기준, 없으면 창 기준 % 다', async () => {
    expect(compactPercent(600_000, 800_000, 60)).toBe(75)
    expect(compactPercent(600_000, null, 60)).toBe(60)
    expect(compactPercent(null, 800_000, null)).toBe(null)
  })

  test('75 · 85 는 처음 넘을 때 한 번씩만 알린다', async () => {
    expect(crossed(74, 0)).toBe(0)
    expect(crossed(75, 0)).toBe(75)
    expect(crossed(80, 75)).toBe(0)
    expect(crossed(85, 75)).toBe(85)
    expect(crossed(99, 85)).toBe(0)
    // 75 를 건너뛰고 바로 90 이면 85 로 알린다
    expect(crossed(90, 0)).toBe(85)
  })

  test('알림 문장이 상태 도구와 인계 자리를 가리킨다', async () => {
    const t75 = thresholdNote(75, 76, 'mcp__mai-gauge__session_status')
    expect(t75).toContain('76%')
    expect(t75).toContain('mcp__mai-gauge__session_status')
    expect(thresholdNote(85, 86, 'T')).toContain('이슈 댓글')
  })

  test('compact 요약기 지시에 복원 줄과 마지막 상태가 들어간다', async () => {
    const s = compactInstructions('C:/u/.mai/sessions/abc.json', '하는 일: v0.2')
    expect(s).toContain('C:/u/.mai/sessions/abc.json 와 잡은 이슈를 다시 읽어라')
    expect(s).toContain('하는 일: v0.2')
    expect(s).toContain('미커밋 파일')
  })

  test('50 · 85 를 경계로 색이 바뀐다', async () => {
    expect(level(49)).toBe('success')
    expect(level(50)).toBe('warning')
    expect(level(84)).toBe('warning')
    expect(level(85)).toBe('error')
  })
})

describe('위험 명령 판정', () => {
  test('되돌릴 수 없는 명령을 잡는다', async () => {
    expect(dangerous('git reset --hard HEAD~1')).toBe('git reset --hard')
    expect(dangerous('cd x && git checkout -- .')).toBe('git checkout -- .')
    expect(dangerous('git clean -fd')).toBe('git clean -f')
    expect(dangerous('git stash -u')).toBe('git stash -u')
    expect(dangerous('git push --force origin main')).toBe('git push --force')
    expect(dangerous('rm -rf build')).toBe('rm -r')
    expect(dangerous('Remove-Item -Recurse -Force .\\out')).toBe('Remove-Item -Recurse')
    expect(dangerous('taskkill /PID 42 /F')).toBe('프로세스 종료')
  })

  test('git 과 하위 명령 사이에 전역 옵션이 껴도 잡는다 (10/12 실측: git -C x reset --hard 가 통과됨)', async () => {
    expect(dangerous('git -C "/c/Users/user/zz-no-repo-here" reset --hard')).toBe('git reset --hard')
    expect(dangerous('git -C C:/w -c core.quotepath=off checkout -- .')).toBe('git checkout -- .')
    expect(dangerous('git --git-dir=.git --work-tree=. clean -fd')).toBe('git clean -f')
    expect(dangerous('git -C repo stash -u')).toBe('git stash -u')
    expect(dangerous('git --no-pager -C repo push --force origin main')).toBe('git push --force')
    expect(dangerous('git -C repo status --short')).toBe(null)
    expect(dangerous('git -C repo log --oneline -1')).toBe(null)
  })

  test('범위를 파일로 적은 명령과 평범한 명령은 통과한다', async () => {
    expect(dangerous('git checkout -- hooks/register.tsx')).toBe(null)
    expect(dangerous('git push origin main')).toBe(null)
    expect(dangerous('git status --short')).toBe(null)
    expect(dangerous('rm build/a.txt')).toBe(null)
    expect(dangerous('claude plugin validate .')).toBe(null)
  })
})

describe('세션 상태판 (결정 4 · 5)', () => {
  test('다른 세션만, 최근 것부터, 끝났거나 낡은 것은 빼고 적는다', async () => {
    const files = [
      session({ id: 'me', name: 'super' }),
      session({ id: 'a', name: 'rl', doing: 'v2 학습', issues: ['#511'], updatedAt: NOW - 120_000 }),
      session({ id: 'b', name: 'lead', waiting: '팀장 컨펌', updatedAt: NOW - 30_000 }),
      session({ id: 'c', name: 'old', updatedAt: NOW - 13 * 3_600_000 }),
      session({ id: 'd', name: 'done', endedAt: NOW - 1_000 }),
    ]
    const t = otherSessionsText(files, 'me', NOW)
    const lines = t.split('\n')
    expect(lines[1]).toContain('lead')
    expect(lines[1]).toContain('대기: 팀장 컨펌')
    expect(lines[2]).toBe('- rl · v2 학습 · #511 · 2m 전')
    expect(t).not.toContain('super')
    expect(t).not.toContain('old')
    expect(t).not.toContain('done')
  })

  test('상한을 넘으면 자르고 몇 개를 뺐는지 적는다', async () => {
    const many = Array.from({ length: 60 }, (_, i) =>
      session({ id: `s${i}`, name: `s${i}`, doing: '긴 작업 설명 '.repeat(5) }),
    )
    const t = otherSessionsText(many, 'me', NOW)
    expect(t.length).toBeLessThan(OTHERS_CHAR_CAP + 40)
    expect(t).toMatch(/…외 \d+개 \(상한\)/)
  })

  test('/sessions 표는 이 세션을 굵게 표시하고 상태 미기재를 드러낸다', async () => {
    const t = sessionsTable([session({ id: 'me', name: 'super', contextPercent: 41 })], 'me', NOW)
    expect(t).toContain('**super** (이 세션)')
    expect(t).toContain('41%')
    expect(t).toContain('상태 미기재')
  })
})

describe('긴 작업과 비용', () => {
  test('PROGRESS 의 마지막 값을 읽고 남은 시간을 비례로 셈한다', async () => {
    expect(parseProgress('PROGRESS 1/10\nfoo\nPROGRESS 4/10\n')).toEqual({ done: 4, total: 10 })
    expect(parseProgress('PROGRESS 11/10')).toBe(null)
    expect(parseProgress('nothing')).toBe(null)
    const job = { id: 'j', command: 'train', path: 'p', startedAt: NOW - 40 * 60_000, progress: { done: 4, total: 10 }, updatedAt: 0 }
    expect(remainingMs(job, NOW)).toBe(60 * 60_000)
  })

  test('왜 비싼가: 요청 수 × 평균 입력에 캐시 깨짐과 큰 결과를 붙인다', async () => {
    const w = whyCostly({
      kind: 'turn', at: NOW, prompt: 'p', steps: 12, avgInput: 180_000, costUsd: 4.1,
      cacheBreaks: 2, topTool: 'Read 61k', subagentSteps: 0, durationMs: 1,
    })
    expect(w).toBe('요청 12 × 평균 입력 180k · 캐시 깨짐 2회 · 큰 결과 Read 61k')
  })

  test('막대와 리셋 표기', async () => {
    expect(bar(150)).toBe('██████████')
    expect(untilReset('2026-10-07T03:31:00Z', NOW)).toBe('3h31m')
    expect(untilReset('2026-10-10T23:00:00Z', NOW)).toBe('3d23h')
    expect(untilReset(undefined, NOW)).toBe('')
  })
})

describe('/gauge 와 프롬프트 위 띠', () => {
  test('자동 compact 가 꺼진 세션은 창 기준으로 적는다', async ($, on) => {
    world(on)
    const r = await $.command.run(gauge())
    expect(r.text).toContain('780k / 1.0M window (78%) · auto-compact off')
    expect(r.text).toContain('5 hours: 10% used · resets in 3h31m')
    expect(r.text).toContain('total (this session) $3.20')
  })

  test('문턱이 있으면 문턱 기준 % 와 compact 까지 남은 양을 적고 띠도 그렇게 그린다', async ($, on) => {
    world(on, 600_000, 800_000)
    const r = await $.command.run(gauge())
    // 정리는 계기판이 문턱의 85 % 에서 건다. 남은 양도 그 자리까지 (800k 의 85 % = 680k)
    expect(r.text).toContain('mai-gauge compacts between turns at 85% (680k): 80.0k to go')
    const ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    const t = await ui.find({ type: 'Text', text: /^ +75%$/ })
    expect(t?.props.color).toBe('warning')
    // 턴 기록이 아직 없으면 몇 번 남았는지 대신 정리 지점을 말한다
    expect(await ui.find({ type: 'Text', text: /compact at 85%/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\[\$3.20\] *$/ })).toBeDefined()
    await ui.unmount()
  })

  test('문턱의 85 % 를 넘으면 경고색이다 (창 기준으로는 73 % 여도)', async ($, on) => {
    world(on, 728_000, 800_000)
    await $.command.run(gauge())
    const ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    const t = await ui.find({ type: 'Text', text: /91%/ })
    expect(t?.props.color).toBe('error')
    await ui.unmount()
  })

  test('/gauge hide 로 숨기면 띠가 사라지고 show 로 돌아온다', async ($, on) => {
    world(on)
    engineBeneath(on)
    await $.command.run(gauge())
    await $.command.run(gauge('hide'))
    let ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    expect(await ui.find({ type: 'Text', text: /^context +$/ })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: 'ENGINE' })).toBeDefined()
    await ui.unmount()
    await $.command.run(gauge('show'))
    ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    expect(await ui.find({ type: 'Text', text: /^context +$/ })).toBeDefined()
    await ui.unmount()
  })

  test('설문이 떠 있으면 비켜 준다', async ($, on) => {
    world(on)
    engineBeneath(on)
    await $.command.run(gauge())
    const ui = await $.ui.mount({
      plugin: 'mai-gauge',
      surface: 'terminal',
      component: 'AbovePrompt',
      props: { ...PROPS, hasSurvey: true },
    })
    expect(await ui.find({ type: 'Text', text: /^context +$/ })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: 'ENGINE' })).toBeDefined()
    await ui.unmount()
  })
})

describe('위험 명령 보류와 「이번 한 번 허용」', () => {
  test('보류 -> 띠의 단추 -> 같은 명령 한 번 통과 -> 다시 보류', async ($, on) => {
    world(on)
    permitBeneath(on)
    const cmd = { tool: 'Bash', input: { command: 'git reset --hard HEAD' } }

    const first = await $.tool.check(cmd as never)
    expect(first.decision).toBe('deny')
    expect(first.reason).toContain('git reset --hard')

    await $.command.run(gauge())
    const ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    expect(await ui.find({ type: 'Text', text: /git reset --hard: git reset --hard HEAD/ })).toBeDefined()
    await ui.press({ key: 'allow' })
    await ui.unmount()

    expect((await $.tool.check(cmd as never)).decision).toBe('allow')
    // 한 번뿐이다
    expect((await $.tool.check(cmd as never)).decision).toBe('deny')
  })

  test('단추를 못 누르는 화면에서는 /gauge allow 와 /gauge close 로 같은 일을 한다', async ($, on) => {
    world(on)
    permitBeneath(on)
    const cmd = { tool: 'Bash', input: { command: 'git stash -u' } }
    expect((await $.command.run(gauge('allow'))).text).toBe('보류된 명령이 없습니다.')
    expect((await $.tool.check(cmd as never)).decision).toBe('deny')
    expect((await $.command.run(gauge('close'))).text).toContain('계속 막혀')
    expect((await $.tool.check(cmd as never)).decision).toBe('deny')
    expect((await $.command.run(gauge('allow'))).text).toContain('한 번 허용')
    expect((await $.tool.check(cmd as never)).decision).toBe('allow')
    expect((await $.tool.check(cmd as never)).decision).toBe('deny')
  })

  test('허용은 같은 위험 종류에 한 번: 모델이 명령 끝을 바꿔도 통하고, 다른 종류에는 안 옮겨 간다', async ($, on) => {
    const clock = world(on)
    permitBeneath(on)
    const sent: string[] = []
    on('prompt.fill', async ($, e) => {
      sent.push(e.text)
      return { isFilled: true } as never
    })
    // 타이머는 session.start 에서 건다. 그 아래 엔진 몫을 대신 답한다.
    on('command.register', async () => ({ value: undefined }) as never)
    on('tool.register', async () => ({ value: undefined }) as never)
    on('session.start', async () => ({ cwd: 'C:/w' }) as never)
    await $.session.start({ source: 'startup', cwd: 'C:/w' } as never)
    await $.tool.check({ tool: 'Bash', input: { command: 'git clean -fd' } } as never)
    await $.command.run(gauge())
    const ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    await ui.press({ key: 'allow' })
    await ui.unmount()
    // 허용하면 팀장이 다시 쓰지 않아도 입력창에 다시 실행 문장이 채워진다 (보내는 것은 팀장의 Enter).
    // 계기판이 직접 보내면 자동 모드 분류기가 승인 우회로 막는다 (10/9 실측)
    expect(sent.length).toBe(1)
    await clock.advance(10_000)
    expect(sent.length).toBe(1)
    expect(sent.join(' ')).toContain('보류됐던 git clean -f 명령을 허용했다 (10 분 안 한 번). 아직 필요하면 다시 실행하고, ')
    expect(sent.join(' ')).toContain('끝냈으면 실행하지 말고 넘어가라: git clean -fd')
    expect(sent.join(' ')).not.toContain('그 명령을 다시 실행해')
    // 다른 종류는 그대로 막힌다
    expect((await $.tool.check({ tool: 'Bash', input: { command: 'git reset --hard' } } as never)).decision).toBe('deny')
    // 같은 종류는 끝을 바꿔도 한 번 통과, 두 번째는 막힘
    expect((await $.tool.check({ tool: 'Bash', input: { command: 'git clean -fd; echo "exit=$?"' } } as never)).decision).toBe('allow')
    expect((await $.tool.check({ tool: 'Bash', input: { command: 'git clean -fd' } } as never)).decision).toBe('deny')
    expect((await $.tool.check({ tool: 'Bash', input: { command: 'git status' } } as never)).decision).toBe('allow')
    expect((await $.tool.check({ tool: 'Read', input: { file_path: 'a' } } as never)).decision).toBe('allow')
  })
})

describe('작업 단위 기계 기록 (LLM 0 원)', () => {
  test('커밋 출력에서 해시와 제목을, 조용한 커밋이면 그 저장소 폴더를 찾는다', async () => {
    expect(commitFrom('[main 1e59544] mods: v0.2 반영\n 5 files changed')).toBe('1e59544 mods: v0.2 반영')
    expect(commitFrom('[fix/x (root-commit) abcdef0123] first')).toBe('abcdef0 first')
    expect(commitFrom('nothing to commit')).toBe(null)
    expect(commitDir('cd /c/w/repo && git add a && git commit -q -m "x"')).toBe('/c/w/repo')
    expect(commitDir('git -C "C:/a b/r" commit -m x')).toBe('C:/a b/r')
    expect(commitDir('git commit -q -m x')).toBe('')
    expect(commitDir('git status && git log -3')).toBe(null)
    // 「commit」 이 들어 있어도 커밋이 아니면 아니다 (결함 주입 M4 가 처음엔 통과했다)
    expect(commitDir('git log --oneline | grep commit')).toBe(null)
    expect(commitDir('echo "commit 하자"')).toBe(null)
  })

  test('남긴 글 링크와 고친 파일을 줍는다', async () => {
    const t = 'https://github.com/example/repo-a/issues/30#issuecomment-6037765057\nhttps://github.com/example/project-x/pull/530 x https://github.com/example/project-x/pull/530'
    expect(linksFrom(t)).toEqual([
      'https://github.com/example/repo-a/issues/30#issuecomment-6037765057',
      'https://github.com/example/project-x/pull/530',
    ])
    expect(fileOf('Edit', { file_path: 'C:\\w\\a.ts' })).toBe('C:/w/a.ts')
    expect(fileOf('Read', { file_path: 'a' })).toBe(null)
  })

  test('하는 일이 바뀌면 단위를 닫고 새로 열며, 첫 doing 은 지금 단위의 이름이 된다', async () => {
    let u = rollUnits([], undefined, undefined, NOW)
    expect(u.length).toBe(1)
    u = rollUnits(u, 'v0.3 기계 기록', ['mai-os#30'], NOW + 1)
    expect(u.length).toBe(1)
    expect(u[0]!.doing).toBe('v0.3 기계 기록')
    u = rollUnits(u, 'v0.3 기계 기록', undefined, NOW + 2)
    expect(u.length).toBe(1)
    u = rollUnits(u, '#526 수정', ['project-x#526'], NOW + 3)
    expect(u.length).toBe(2)
    expect(u[0]!.endedAt).toBe(NOW + 3)
    expect(u[1]!.issues).toEqual(['project-x#526'])
  })

  test('같은 사실은 두 번 넣지 않고, 안 바뀌면 같은 객체를 돌려준다', async () => {
    const u = addTo(newUnit('a', [], NOW), 'commits', ['1e59544 x'])
    expect(addTo(u, 'commits', ['1e59544 x'])).toBe(u)
    expect(addTo(u, 'commits', ['6ee7e05 y']).commits).toEqual(['1e59544 x', '6ee7e05 y'])
  })

  test('기록 글은 사실만 담고, 많으면 앞을 생략했다고 밝힌다', async () => {
    let u = newUnit('v0.3', ['mai-os#30'], NOW - 90 * 60_000)
    u = addTo(u, 'files', Array.from({ length: 13 }, (_, i) => `f${i}.ts`))
    u = { ...u, turns: 4, costUsd: 1.5 }
    const t = unitText(u, NOW)
    expect(t.split('\n')[0]).toBe('단위: v0.3 · mai-os#30 · 1h30m · 턴 4 · $1.50')
    expect(t).toContain('고친 파일 13개:')
    expect(t).toContain('…앞의 3개 생략')
    expect(t).toContain('- f12.ts')
  })

  test('주입 예산을 넘으면 줄 단위로 자르고 원문 자리를 밝힌다', async () => {
    const long = Array.from({ length: 100 }, (_, i) => `줄 ${i}`).join('\n')
    const b = budgeted(long, 200, 'C:/u/.mai/units/x.json')
    expect(b.length).toBeLessThan(260)
    expect(b).toContain('전부는 C:/u/.mai/units/x.json')
    expect(budgeted('짧다', 200, 'p')).toBe('짧다')
  })

  test('저장소 밖 판정: 경로 표기가 달라도 같은 자리는 안, 예외 자리는 뺀다', async () => {
    expect(normPath('/c/Users/a\\b/')).toBe('c:/Users/a/b')
    expect(isInside('C:\\w\\project-x\\sim\\a.py', 'c:/w/project-x')).toBe(true)
    expect(isInside('C:/w/project-x-old/a.py', 'C:/w/project-x')).toBe(false)
    const out = outsideOf(
      ['C:/w/project-x/a.py', 'C:/isaac/IsaacLab/x/gap.py', 'C:/Users/u/.mai/units/s.json', 'C:/Users/u/AppData/Local/Temp/t.txt'],
      'C:/w/project-x',
      ['C:/Users/u/.mai', 'C:/Users/u/AppData/Local/Temp'],
    )
    expect(out).toEqual(['c:/isaac/IsaacLab/x/gap.py'])
  })

  test('셸은 쓰는 명령일 때만 절대 경로를 줍는다', async () => {
    expect(shellWriteTargets('cp sim/a.py /c/isaac/IsaacLab/x/')).toEqual(['c:/isaac/IsaacLab/x'])
    expect(shellWriteTargets('Copy-Item .\\a.py C:\\isaac\\IsaacLab\\x\\a.py')).toEqual(['c:/isaac/IsaacLab/x/a.py'])
    expect(shellWriteTargets('python run.py > D:/logs/out.txt')).toEqual(['d:/logs/out.txt'])
    expect(shellWriteTargets('cat C:/isaac/IsaacLab/x/a.py')).toEqual([])
    expect(shellWriteTargets('git status')).toEqual([])
  })

  test('저장소 밖 자리는 기록 글 맨 앞에 온다', async () => {
    const u = addTo(addTo(newUnit('a', [], NOW), 'files', ['c:/w/r/a.ts']), 'outside', ['c:/isaac/x.py'])
    const lines = unitText(u, NOW).split('\n')
    expect(lines[1]).toContain('저장소 밖에 쓴 자리 1곳')
    expect(lines[2]).toBe('- c:/isaac/x.py')
  })

  test('50 % 는 알림 단계에만, 프롬프트 알림은 75 · 85 에만', async () => {
    expect(crossed(55, 0, [50, 75, 85])).toBe(50)
    expect(crossed(55, 50, [50, 75, 85])).toBe(0)
    expect(crossed(55, 0)).toBe(0)
    expect(thresholdNote(75, 76, 'T', 'C:/u/.mai/units/x.json')).toContain('C:/u/.mai/units/x.json 에 기계로 적혀')
  })
})

describe('세션 이름 (/rename)', () => {
  // 상태 파일을 진짜 ~/.mai 가 아니라 메모리에 쓴다.
  function disk(on: On) {
    const files = new Map<string, string>()
    mock.clock(on, { now: NOW })
    mock.env(on, { USERPROFILE: 'C:/u', ORCA_TERMINAL_HANDLE: 'term_abc' })
    on('session.id', async () => ({ value: 'sid1' }))
    on('session.cwd', async () => ({ value: 'C:/x/Claude' }))
    on('session.repo', async () => ({ value: null }))
    on('classic.SessionStart', async () => ({}))
    on('classic.UserPromptSubmit', async () => ({}))
    on('fs.exists', async ($, e) => ({ value: files.has(e.path) }))
    on('fs.read', async ($, e) => ({ value: files.get(e.path) ?? '' }))
    on('fs.write', async ($, e) => {
      files.set(e.path, e.text)
      return { value: undefined }
    })
    // 세션 id 는 시험 엔진이 정하므로 상태판 폴더의 파일 하나를 본다.
    return () => {
      // 엔진이 경로를 백슬래시로 바꿔 넘기므로 슬래시로 맞춰 본다.
      const keys = [...files.keys()].filter(k => k.replace(/\\/g, '/').startsWith('C:/u/.mai/sessions/'))
      expect(keys.length).toBeLessThanOrEqual(1)
      return keys[0] ? (JSON.parse(files.get(keys[0])!) as SessionFile) : null
    }
  }

  test('제목이 없으면 폴더 이름, /rename 하면 그 이름, 중간에 다시 바꾸면 다음 프롬프트에서 따라간다', async ($, on) => {
    const me = disk(on)
    await $.classic.UserPromptSubmit({ prompt: '첫 지시' })
    expect(me()).toBeNull()
    await $.classic.SessionStart({ source: 'startup', session_title: 'test' })
    expect(me()?.name).toBe('test')
    expect(me()?.titled).toBe(true)
    expect(me()?.handle).toBe('term_abc')
    await $.classic.UserPromptSubmit({ prompt: '다음 지시', session_title: '  test2 ' })
    expect(me()?.name).toBe('test2')
    await $.classic.UserPromptSubmit({ prompt: '그다음', session_title: '' })
    expect(me()?.name).toBe('test2')
  })
})

describe('상태판에 Orca 핸들', () => {
  test('표와 맥락 한 줄에 핸들이 나와 그 세션에 바로 말을 걸 수 있다', () => {
    const f: SessionFile = {
      id: 'a', name: 'lead', handle: 'term_9192d0e4-2d27', cwd: 'C:/l', repo: null, doing: '설계',
      issues: [], waiting: '', next: '', contextPercent: 40, startedAt: NOW, updatedAt: NOW, statusAt: NOW,
    }
    expect(sessionsTable([f], 'x', NOW)).toContain('| lead | term_9192d0e4-2d27 | 설계 |')
    expect(otherSessionsText([f], 'x', NOW)).toContain('- lead (term_9192d0e4) · 설계')
  })
})

describe('한도 속도와 85 % 턴 사이 compact', () => {
  test('지금 속도로 리셋 때 몇 % 인지, 리셋 전에 바닥나면 언제인지 낸다', () => {
    // 5시간 창에서 2시간 지나 60 %: 시간당 30 %. 리셋까지 3시간 남아 ~150 %, 1h20m 뒤 바닥
    const l = { kind: 'five_hour', percentUsed: 60, resetsAt: new Date(NOW + 3 * 3_600_000).toISOString() }
    expect(pace(l, NOW)).toEqual({ projected: 150, fullAt: NOW + 80 * 60_000, basis: 'window' })
    // 여유가 있으면 바닥 시각은 없다
    expect(pace({ ...l, percentUsed: 20 }, NOW)).toEqual({ projected: 50, fullAt: null, basis: 'window' })
    // 창이 막 열렸으면(10 % 미만 경과) 내놓지 않는다
    expect(pace({ ...l, resetsAt: new Date(NOW + 4.8 * 3_600_000).toISOString() }, NOW)).toBeNull()
    expect(pace({ kind: 'spend_limit', percentUsed: 50 }, NOW)).toBeNull()
  })

  test('/gauge 표에 리셋 때 예상치가 붙는다', async ($, on) => {
    world(on)
    const r = await $.command.run(gauge())
    // 5시간: 1h29m 동안 10 % 이면 리셋 때 ~34 %
    expect(r.text).toContain('5 hours: 10% used · resets in 3h31m · at the average pace of this window: ~34% at reset · ● enough')
  })

  test('턴이 끝난 자리에서 85 % 를 넘었으면 계기판이 직접 compact 를 한 번 건다', async ($, on) => {
    world(on, 870_000, 1_000_000)
    let compacts = 0
    on('session.compact', async () => {
      compacts += 1
      return { skip: '시험' } as never
    })
    on('turn.complete', async ($, e) => ({ text: e.answer }) as never)
    const done = { answer: '끝', durationMs: 10, isAborted: false, turnId: 't1', reason: 'answer' as const }
    await $.turn.complete(done as never)
    await new Promise(r => setTimeout(r, 0))
    expect(compacts).toBe(1)
    // 같은 고비에서 두 번 걸지 않는다
    await $.turn.complete({ ...done, turnId: 't2' } as never)
    await new Promise(r => setTimeout(r, 0))
    expect(compacts).toBe(1)
  })

  test('85 % 아래에서는 compact 를 걸지 않는다', async ($, on) => {
    world(on, 600_000, 1_000_000)
    let compacts = 0
    on('session.compact', async () => {
      compacts += 1
      return { skip: '시험' } as never
    })
    on('turn.complete', async ($, e) => ({ text: e.answer }) as never)
    await $.turn.complete({ answer: '끝', durationMs: 10, isAborted: false, turnId: 't1', reason: 'answer' } as never)
    await new Promise(r => setTimeout(r, 0))
    expect(compacts).toBe(0)
  })
})

describe('모델 요청 한 걸음마다 턴 집계', () => {
  // 1.3.2 에서 계정 함수와 이름이 겹쳐 이 집계가 사흘간 한 번도 안 돌았다 (10/12 비용 기록 실측)
  test('한 걸음이 끝나면 이번 턴의 요청 수와 토큰이 는다', async ($, on) => {
    world(on)
    on('turn.step', async function* () {
      return {
        turnId: 't1', index: 0, answer: '', toolUses: [],
        usage: { input_tokens: 10, output_tokens: 20, cache_read_input_tokens: 300, cache_creation_input_tokens: 40 },
      } as never
    })
    const s = $.turn.step({ turnId: 't1', index: 0, model: 'm', messageCount: 1 } as never)
    for await (const _ of s) void _
    await s.result
    const r = await $.command.run(gauge())
    expect(r.text).toContain('1 request · avg input 350 · new input 50 · cache read 300 · out 20')
  })
})

describe('compact 뒤 띠', () => {
  test('엔진 사용량이 다음 요청 전까지 옛 값이어도 띠는 compact 뒤 크기로 바로 바뀐다', async ($, on) => {
    world(on, 780_000)
    mock.env(on, { USERPROFILE: 'C:/u' })
    on('session.id', async () => ({ value: 'sid1' }))
    on('fs.exists', async () => ({ value: false }))
    on('fs.read', async () => ({ value: '' }))
    on('fs.write', async () => ({ value: undefined }))
    on('session.compact', async () =>
      ({ messages: [{ role: 'user', text: '요약', toolUses: [] }], tokensBefore: 780_000, tokensAfter: 14_000 }) as never)
    engineBeneath(on)
    // 시험에는 엔진이 없어 대화를 직접 넘긴다
    await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: '긴 대화', toolUses: [] }] } as never)
    const ui = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', ...BAND })
    expect(await ui.find({ type: 'Text', text: /^ +1%$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /78%/ })).toBeUndefined()
  })
})

describe('띠 그림 (B21)', () => {
  test('막대는 쓴 몫 · 이 속도로 더 쓸 몫 · 남은 칸 · 정리 눈금으로 나뉜다', () => {
    expect(segs(44, 20, null, 85)).toEqual([{ kind: 'used', n: 9 }, { kind: 'free', n: 8 }, { kind: 'mark', n: 1 }, { kind: 'free', n: 2 }])
    expect(segs(29, 10, 68)).toEqual([{ kind: 'used', n: 3 }, { kind: 'ahead', n: 4 }, { kind: 'free', n: 3 }])
    // 눈금을 넘어 차면 눈금은 쓴 칸에 묻힌다
    expect(segs(95, 10, null, 85)).toEqual([{ kind: 'used', n: 10 }])
  })

  test('한도 판정은 낱말과 기호를 함께 낸다 (색을 못 가려도 읽힌다)', () => {
    const at = (h: number) => new Date(NOW + h * 3_600_000).toISOString()
    expect(verdict({ kind: 'five_hour', percentUsed: 20, resetsAt: at(3) }, NOW)).toEqual({ word: 'enough', sign: '●', tone: 'success' })
    expect(verdict({ kind: 'five_hour', percentUsed: 40, resetsAt: at(3) }, NOW)).toEqual({ word: 'tight', sign: '▲', tone: 'warning' })
    expect(verdict({ kind: 'five_hour', percentUsed: 60, resetsAt: at(3) }, NOW)).toEqual({ word: 'short', sign: '✕', tone: 'error' })
    expect(verdict({ kind: 'five_hour', percentUsed: 1, resetsAt: at(4.9) }, NOW).word).toBe('measuring')
    expect(verdict({ kind: 'five_hour', percentUsed: 100, resetsAt: at(1) }, NOW).word).toBe('out')
  })

  test('정리까지 몇 번: 최근 턴의 평균 증가로 센다. compact 로 줄어든 자리는 뺀다', () => {
    expect(growthOf([100_000, 110_000, 130_000])).toBe(15_000)
    expect(growthOf([700_000, 20_000, 30_000, 40_000])).toBe(10_000)
    // 한 번 늘어난 것만으로는 내지 않는다
    expect(growthOf([700_000, 20_000, 30_000])).toBeNull()
    expect(growthOf([5_000])).toBeNull()
    expect(turnsLeft(500_000, 822_000, 40_000)).toBe(8)
    expect(turnsLeft(500_000, 822_000, null)).toBeNull()
  })

  test('좁은 화면에서는 막대와 오른쪽 칸을 빼고, 넓은 화면에서는 막대 · 예상치 · 비용', async ($, on) => {
    world(on, 600_000, 800_000)
    await $.command.run(gauge())
    const narrow = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', component: 'AbovePrompt', props: { ...PROPS, bodyColumns: 50 } })
    expect(await narrow.find({ type: 'Text', text: /● enough \(3h31m\)/ })).toBeDefined()
    expect(await narrow.find({ type: 'Text', text: /━/ })).toBeUndefined()
    await narrow.unmount()
    const wide = await $.ui.mount({ plugin: 'mai-gauge', surface: 'terminal', component: 'AbovePrompt', props: { ...PROPS, bodyColumns: 130 } })
    expect(await wide.find({ type: 'Text', text: /\[~34%\]/ })).toBeDefined()
    expect(await wide.find({ type: 'Text', text: /\[\$3.20\]/ })).toBeDefined()
    expect(await wide.find({ type: 'Text', text: /600k\/1.0M/ })).toBeDefined()
    await wide.unmount()
  })
})

describe('한도 예측의 한계 해결: 최근 30 분 기울기 (모든 세션 · 기기 합)', () => {
  const R = new Date(NOW + 3 * 3_600_000).toISOString()
  const M = 60_000
  test('같은 창의 최근 30 분 표본으로 속도를 낸다. 5 분 미만이거나 다른 창 표본은 안 쓴다', () => {
    const s = [
      { at: NOW - 60 * M, pct: 5, reset: R },
      { at: NOW - 20 * M, pct: 20, reset: R },
      { at: NOW, pct: 30, reset: R },
      { at: NOW - 10 * M, pct: 99, reset: 'other' },
    ]
    // 최근 30 분: 20 분 동안 10 % = 0.5 %/분
    expect(Math.round((recentRate(s, R, NOW) ?? 0) * M * 1000)).toBe(500)
    expect(recentRate([{ at: NOW - 2 * M, pct: 1, reset: R }, { at: NOW, pct: 2, reset: R }], R, NOW)).toBeNull()
  })

  test('창 평균은 느긋해도 최근에 몰아 쓰면 「모자람」으로 바뀐다 (창 평균만으로는 못 잡던 것)', () => {
    // 2 시간 동안 30 %: 창 평균이면 리셋(3 시간 뒤) 때 75 %, 넉넉
    const l = { kind: 'five_hour', percentUsed: 30, resetsAt: R }
    expect(verdict(l, NOW).word).toBe('enough')
    // 그런데 다른 세션이 최근 20 분에 15 % 를 썼다: 0.75 %/분이면 93 분 뒤 바닥
    const recent = recentRate([{ at: NOW - 20 * M, pct: 15, reset: R }, { at: NOW, pct: 30, reset: R }], R, NOW)
    expect(verdict(l, NOW, recent).word).toBe('short')
    expect(pace(l, NOW, recent)?.basis).toBe('recent')
    expect(pace(l, NOW, recent)?.fullAt).toBe(NOW + 93 * M + 20_000)
  })

  test('표본은 창마다 1 시간만 남기고, 같은 값이 5 분 안에 이어지면 더하지 않는다', () => {
    let s = addSample([], { at: NOW - 70 * M, pct: 1, reset: R })
    s = addSample(s, { at: NOW - 2 * M, pct: 3, reset: R })
    s = addSample(s, { at: NOW - M, pct: 3, reset: R })
    s = addSample(s, { at: NOW, pct: 4, reset: R })
    expect(s.map(x => x.pct)).toEqual([3, 4])
    // 리셋이 바뀌면(새 창) 지난 창 표본은 버린다
    expect(addSample(s, { at: NOW, pct: 0, reset: 'next' }).map(x => x.reset)).toEqual(['next'])
  })
})

describe('띠 배치는 어느 폭에서도 넘치지 않는다', () => {
  const v = (word: string, sign: string, tone: 'success' | 'warning' | 'error' | 'inactive') => ({ word, sign, tone })
  const full = {
    cp: 84, tokens: 812_000, window: 1_000_000, turnsTo: 2,
    limits: [
      { name: '5 hours', pct: 92, projected: 140, verdict: v('short', '✕', 'error'), reset: '3h59m', outIn: '1h20m' },
      { name: '7 days', pct: 38, projected: null, verdict: v('measuring', '…', 'inactive'), reset: '6d23h', outIn: null },
    ],
    totalCost: 1234.56,
    turn: { steps: 128, cost: 99.99, reads: 31_500_000, out: 24_400, fresh: 9_000, cacheWrite: 3_000 },
    job: 'progress 4/9 [1m]', current: 'Bash git status', outside: 3,
  }
  test('긴 값을 다 채워도 잘리지 않는 조각의 합이 폭 안에 든다 (모바일 40칸부터 넓은 화면 200칸까지)', () => {
    for (const cols of [40, 48, 56, 64, 80, 96, 110, 120, 160, 200]) {
      for (const r of bandRows(full, cols)) expect(fixedCells(r)).toBeLessThanOrEqual(cols)
    }
  })
  test('막대 · % · 판정이 줄마다 같은 칸에서 시작한다', () => {
    for (const cols of [64, 100, 140]) {
      const rows = bandRows(full, cols).slice(0, 3)
      const startOf = (r: typeof rows[number], test: (t: string) => boolean) => {
        let n = 0
        for (const p of r) { if (test(p.t)) return n; n += [...p.t].length }
        return -1
      }
      const pct = rows.map(r => startOf(r, t => /%$/.test(t.trim()) && !t.includes('[')))
      expect(new Set(pct).size).toBe(1)
    }
  })
  test('리셋 시각을 모르면 판정 뒤에 빈 괄호를 찍지 않는다', () => {
    const lim = [{ ...full.limits[1]!, reset: '' }]
    const text = bandRows({ ...full, limits: lim }, 120).map(r => r.map(p => p.t).join('')).join('\n')
    expect(text).toContain('… measuring')
    expect(text).not.toContain('()')
  })
  test('한도가 없는 계정(API 키)은 컨텍스트와 이번 턴만 그린다', () => {
    const rows = bandRows({ ...full, limits: [] }, 120)
    expect(rows.map(r => r[0]!.t.trim())).toEqual(['context', 'turn', 'now'])
  })
})

describe('낡은 Orca 핸들을 이름 줄로 다시 찾는다', () => {
  // 10/12 실측 화면의 아래쪽 (lead · super)
  const lead = [
    'turn     -                 [$3204.1]  … no turn yet',
    '                               new task? /clear to save 402.2k tokens',
    '──────────────────────────────────────────────────────────────── lead ─',
    '❯ 25916 하고 145356 둘 다 꺼도 돼',
    '───────────────────────────────────────────────────────────────────────',
    '  ⏵⏵ auto mode on · ← 1 agent · PR #481 · 6 shells · ⧉ 3',
  ]
  const superTail = [
    'now      ▲ outside repo 12',
    '────────────────────────────────────────────────── super ─',
    '❯',
    '──────────────────────────────────────────────────',
  ]
  test('이름 줄이 있는 터미널 하나를 고른다', () => {
    expect(handleByName('lead', [{ handle: 'term_s', tail: superTail }, { handle: 'term_l', tail: lead }])).toBe('term_l')
    expect(handleByName('super', [{ handle: 'term_s', tail: superTail }, { handle: 'term_l', tail: lead }])).toBe('term_s')
  })
  test('이름이 겹치거나 없으면 고르지 않는다', () => {
    expect(handleByName('lead', [{ handle: 'a', tail: lead }, { handle: 'b', tail: lead }])).toBeNull()
    expect(handleByName('rl', [{ handle: 'term_l', tail: lead }])).toBeNull()
  })
  test('위쪽에 읽어 온 다른 세션 화면이 있어도 속지 않는다', () => {
    const echoed = [...lead, ...Array(10).fill('…'), ...superTail]
    expect(handleByName('lead', [{ handle: 'term_s', tail: echoed }])).toBeNull()
  })
  test('이름 속 정규식 글자를 글자로 다룬다', () => {
    expect(handleByName('a.b', [{ handle: 'x', tail: ['──── axb ─'] }])).toBeNull()
    expect(handleByName('a.b', [{ handle: 'x', tail: ['──── a.b ─'] }])).toBe('x')
  })
})

describe('리셋이 지난 낡은 한도', () => {
  const N = Date.parse('2026-10-12T01:00:00Z')
  test('새 표본이 없으면 지난 창의 % 를 버린다', () => {
    const own = [{ kind: 'five_hour', percentUsed: 58, resetsAt: new Date(N - 60_000).toISOString() }]
    expect(freshLimits(own, {}, N)).toEqual([])
  })
  test('리셋 전이면 그대로 둔다', () => {
    const own = [{ kind: 'five_hour', percentUsed: 58, resetsAt: new Date(N + 60_000).toISOString() }]
    expect(freshLimits(own, {}, N)).toEqual(own)
  })
  test('다른 세션의 새 창 표본이 있으면 그 값을 쓴다', () => {
    const own = [{ kind: 'five_hour', percentUsed: 58, resetsAt: new Date(N - 60_000).toISOString() }]
    const r = new Date(N + 4 * 3_600_000).toISOString()
    expect(freshLimits(own, { five_hour: [{ at: N - 1000, pct: 1, reset: r }] }, N)).toEqual([{ kind: 'five_hour', percentUsed: 1, resetsAt: r }])
  })
})

describe('정리까지 남은 턴 수는 늘 숫자로', () => {
  const base = { cp: 40, tokens: 400_000, window: 1_000_000, limits: [], totalCost: null, turn: null, job: null, current: null, outside: 0 }
  const say = (turnsTo: number | null) => bandRows({ ...base, turnsTo }, 120)[0]!.map(p => p.t).join('')
  test('50 번 이하는 그 수, 넘으면 50+, 두 턴을 재기 전에는 정리 지점', () => {
    expect(say(6)).toContain('● compact in ~6 turns')
    expect(say(2)).toContain('▲ compact in ~2 turns')
    expect(say(120)).toContain('● compact in 50+ turns')
    expect(say(null)).toContain('● compact at 85%')
  })
})

describe('비용과 줄 수는 어느 폭 · 어느 세션에서도 같은 자리', () => {
  const v = (word: string, sign: string, tone: 'success' | 'warning' | 'error' | 'inactive') => ({ word, sign, tone })
  const m = {
    cp: 76, tokens: 737_000, window: 1_000_000, turnsTo: 2,
    limits: [
      { name: '5 hours', pct: 34, projected: 37, verdict: v('enough', '●', 'success'), reset: '22m', outIn: null },
      { name: '7 days', pct: 38, projected: 50, verdict: v('enough', '●', 'success'), reset: '1d16h', outIn: null },
    ],
    totalCost: 632.5,
    turn: { steps: 12, cost: 2.47, reads: 8_700_000, out: 14_800, fresh: 9_000, cacheWrite: 0 },
    job: null, current: null, outside: 3,
  }
  test('비용은 넷째 줄 맨 앞, 이름 칸 바로 뒤에서 시작한다 (40 ~ 200 칸)', () => {
    for (const cols of [40, 64, 80, 96, 120, 200]) {
      const turn = bandRows(m, cols).find(r => r[0]!.t.trim() === 'turn')!
      expect(turn[0]!.t).toBe('turn     ')
      // 이번 턴 비용은 늘 값 칸 맨 앞. 세션 합계는 넓으면 total 칸, 좁으면 [ ] 안
      expect(turn[1]!.t.trim().startsWith('$2.47')).toBe(true)
      expect(turn.map(p => p.t).join('')).toContain('[$632.5]')
      // 비용 · [합계] 는 안 잘린다 (잘릴 수 있는 것은 맨 뒤 내역뿐)
      expect(turn.slice(0, -1).every(p => !p.fill)).toBe(true)
    }
  })
  test('5 hours 값이 아직 없는 세션도 줄 수와 순서가 같다', () => {
    const only7 = { ...m, limits: [m.limits[1]!] }
    const rows = bandRows(only7, 100)
    expect(rows.map(r => r[0]!.t.trim())).toEqual(['context', '5 hours', '7 days', 'turn', 'now'])
    expect(rows[1]!.map(p => p.t).join('')).toContain('… no data yet')
  })
})

describe('형식은 세션마다 같다', () => {
  test('막대 길이는 터미널 폭과 상관없이 같고, 아주 좁을 때만 빠진다', () => {
    const m = { cp: 50, tokens: 500_000, window: 1_000_000, turnsTo: 9, limits: [], totalCost: 1, turn: null, job: null, current: null, outside: 0 }
    const barLen = (cols: number) => bandRows(m, cols)[0]!.filter(p => /^[━╍─┃]+$/.test(p.t)).reduce((n, p) => n + p.t.length, 0)
    expect(new Set([60, 80, 103, 140, 200].map(barLen))).toEqual(new Set([12]))
    expect(barLen(50)).toBe(0)
  })
})

describe('turn 줄: 어디에 썼나와 세로선', () => {
  const v = (word: string, sign: string, tone: 'success' | 'warning' | 'error' | 'inactive') => ({ word, sign, tone })
  const m = {
    cp: 76, tokens: 737_000, window: 1_000_000, turnsTo: 2,
    limits: [
      { name: '5 hours', pct: 39, projected: 40, verdict: v('enough', '●', 'success'), reset: '16m', outIn: null },
      { name: '7 days', pct: 38, projected: 38, verdict: v('enough', '●', 'success'), reset: '1d16h', outIn: null },
    ],
    totalCost: 2925.8,
    turn: { steps: 12, cost: 2.47, reads: 8_700_000, out: 14_800, fresh: 9_000, cacheWrite: 0 },
    job: null, current: null, outside: 0,
  }
  test('턴 비용을 읽기 · 출력 · 새 입력으로 나누면 합이 실제 비용이고 읽기가 가장 크다', () => {
    const c = splitCost(m.turn)
    expect(Math.round((c.reads + c.out + c.fresh) * 100) / 100).toBe(2.47)
    expect(c.reads).toBeGreaterThan(c.out)
    expect(c.out).toBeGreaterThan(c.fresh)
  })
  const startOf = (r: { t: string }[], test: (t: string) => boolean) => {
    let n = 0
    for (const p of r) { if (test(p.t)) return n; n += [...p.t].length }
    return -1
  }
  test('turn 줄도 위 줄과 같은 세로선: 비용은 막대 자리, [합계] 는 [~예상] 자리, ● 는 판정 점 자리', () => {
    for (const cols of [100, 140]) {
      const rows = bandRows(m, cols)
      const turn = rows.find(r => r[0]!.t.trim() === 'turn')!
      expect(startOf(turn, t => t.startsWith('$2.47'))).toBe(startOf(rows[1]!, t => /^[━╍─]/.test(t)))
      expect(startOf(turn, t => t.startsWith('[$'))).toBe(startOf(rows[1]!, t => t.startsWith('[~')))
      expect(startOf(turn, t => t.startsWith('●'))).toBe(startOf(rows[1]!, t => t.startsWith('●')))
      expect(turn.map(p => p.t).join('')).toContain('● 12 req · reads 8.7M $')
    }
  })
  test('좁으면 내역을 덜 중요한 것부터 통째로 빼고, 이번 턴 비용과 [합계] 는 끝까지 남는다', () => {
    const text = (cols: number) => bandRows(m, cols).find(r => r[0]!.t.trim() === 'turn')!.map(p => p.t).join('')
    // compact 직후 캐시를 다시 만드는 턴: 새 입력(캐시 쓰기)이 가장 비싸 맨 앞에 온다
    const rebuild = { ...m, turn: { steps: 1, cost: 0.59, reads: 0, out: 56, fresh: 400, cacheWrite: 89_000 } }
    const rt = bandRows(rebuild, 100).find(r => r[0]!.t.trim() === 'turn')!.map(p => p.t).join('')
    expect(rt.indexOf('new ')).toBeGreaterThan(-1)
    expect(rt.indexOf('new ')).toBeLessThan(rt.indexOf('out '))
    expect(text(130)).toContain('new ')
    expect(text(70)).not.toContain('new ')
    for (const cols of [40, 56, 70, 100]) {
      expect(text(cols)).toContain('$2.47')
      expect(text(cols)).toContain('[$2925.8]')
      expect(text(cols).length).toBeGreaterThan(0)
    }
  })
})

describe('한도 예측이 계단 한 칸에 부풀지 않는다', () => {
  const R = new Date(NOW + 40 * 3_600_000).toISOString()
  const M = 60_000
  test('7일: 30분 사이 1% 한 계단으로 993% 가 되던 것 (10/9 실측)', () => {
    const s = [{ at: NOW - 30 * M, pct: 38, reset: R }, { at: NOW, pct: 39, reset: R }]
    const rate = recentRate(s, R, NOW, 'seven_day')
    // 6 시간 창의 1/6(1시간) 보다 짧으면 내지 않는다
    expect(rate).toBeNull()
    const s2 = [{ at: NOW - 70 * M, pct: 38, reset: R }, { at: NOW, pct: 39, reset: R }]
    const r2 = recentRate(s2, R, NOW, 'seven_day')!
    // 짧은 구간은 3시간으로 늘려 나눈다: 1%/3h, 40시간 남으면 리셋 때 ~52%
    const p = pace({ kind: 'seven_day', percentUsed: 39, resetsAt: R }, NOW, r2)!
    expect(p.projected).toBe(52)
    expect(p.fullAt).toBeNull()
  })
})

describe('비용 기반 한도 예측 (가장 촘촘한 근거)', () => {
  const R = new Date(NOW + 2 * 3_600_000).toISOString()
  const M = 60_000
  // 지난 2시간 동안 % 가 10 → 30 (20 % 상승), 그동안 모든 세션이 $40 를 씀: 1 달러 = 0.5 %
  const samples = [{ at: NOW - 120 * M, pct: 10, reset: R }, { at: NOW, pct: 30, reset: R }]
  const steady = Array.from({ length: 24 }, (_, i) => ({ at: NOW - 120 * M + (i + 1) * 5 * M, cost: 40 / 24 }))
  test('1 달러가 몇 % 인지 배우고, 최근 15 분 쓴 돈으로 지금 속도를 낸다', () => {
    expect(Math.round(spendBetween(steady, NOW - 120 * M, NOW))).toBe(40)
    // 최근 15분에 $5 (3 건) = 2.5 % / 15분 = 10 %/시간 → 2시간 남으면 리셋 때 ~50 %
    const r = spendRate(samples, R, steady, NOW)!
    const p = pace({ kind: 'five_hour', percentUsed: 30, resetsAt: R }, NOW, r, 'spend')!
    expect(p.basis).toBe('spend')
    expect(p.projected).toBe(50)
  })
  test('막 몰아 쓰기 시작하면 % 가 아직 1 칸도 안 올라도 몇 분 만에 「모자람」', () => {
    const burst = [...steady, ...Array.from({ length: 5 }, (_, i) => ({ at: NOW - (i + 1) * 2 * M, cost: 12 }))]
    const r = spendRate(samples, R, burst, NOW)!
    const v = verdict({ kind: 'five_hour', percentUsed: 30, resetsAt: R }, NOW, r, 'spend')
    expect(v.word).toBe('short')
  })
  test('% 가 3 % 도 안 올랐거나 그동안 쓴 기록이 없으면 내지 않는다 (다른 근거로 넘어간다)', () => {
    expect(spendRate([{ at: NOW - 60 * M, pct: 10, reset: R }, { at: NOW, pct: 12, reset: R }], R, steady, NOW)).toBeNull()
    expect(spendRate(samples, R, [], NOW)).toBeNull()
  })
})

describe('비용 기반 예측의 최근 길이는 창마다', () => {
  test('7일은 15분 쉬어도 「이번 주 0」 으로 읽지 않는다 (최근 3시간)', () => {
    const R = new Date(NOW + 40 * 3_600_000).toISOString()
    const H = 3_600_000
    const samples = [{ at: NOW - 10 * H, pct: 20, reset: R }, { at: NOW, pct: 40, reset: R }]
    // 10시간 동안 $100 를 고르게 썼고 마지막 30분은 쉼
    const ev = Array.from({ length: 19 }, (_, i) => ({ at: NOW - 10 * H + (i + 1) * 30 * 60_000, cost: 100 / 19 }))
    expect(spendRate(samples, R, ev, NOW, 'five_hour')).toBe(0)
    expect(spendRate(samples, R, ev, NOW, 'seven_day')!).toBeGreaterThan(0)
  })
})

describe('계정이 섞여도 예측이 부풀지 않는다 (10/9 실측: 7일 >200%)', () => {
  const R = new Date(NOW + 40 * 3_600_000).toISOString()
  const M = 60_000
  test('% 가 줄어드는 자리부터 새로 센다 (같은 계정 · 같은 창의 % 는 줄지 않는다)', () => {
    const mixed = [
      { at: NOW - 90 * M, pct: 39, reset: R },
      { at: NOW - 60 * M, pct: 27, reset: R },
      { at: NOW - 30 * M, pct: 39, reset: R },
      { at: NOW, pct: 28, reset: R },
    ]
    expect(sameSource(mixed).map(x => x.pct)).toEqual([28])
    expect(spendRate(mixed, R, [{ at: NOW - M, cost: 50 }], NOW, 'seven_day')).toBeNull()
  })
})

describe('쉬던 세션도 가장 새 한도 값을 보인다 (10/9 실측: site 27 % · 실제 39 %)', () => {
  const R = new Date(NOW + 40 * 3_600_000).toISOString()
  const R5 = new Date(NOW + 3 * 3_600_000).toISOString()
  test('같은 창이면 더 큰 값, 내 창이 지났거나 없으면 다른 세션이 적은 값', () => {
    const own = [{ kind: 'seven_day', percentUsed: 27, resetsAt: R }]
    const samples = {
      seven_day: [{ at: NOW - 60_000, pct: 39, reset: R }],
      five_hour: [{ at: NOW - 60_000, pct: 3, reset: R5 }],
    }
    const f = freshLimits(own, samples, NOW)
    expect(f.find(l => l.kind === 'seven_day')!.percentUsed).toBe(39)
    // 이 세션은 5시간 값을 못 받았지만 다른 세션 표본으로 채운다
    expect(f.find(l => l.kind === 'five_hour')!.percentUsed).toBe(3)
    // 내 값이 더 새것(더 크면)이면 그대로
    expect(freshLimits([{ kind: 'seven_day', percentUsed: 45, resetsAt: R }], samples, NOW)[0]!.percentUsed).toBe(45)
    // 지난 창의 표본은 쓰지 않는다
    const past = { seven_day: [{ at: NOW - 60_000, pct: 90, reset: new Date(NOW - 1000).toISOString() }] }
    expect(freshLimits(own, past, NOW)[0]!.percentUsed).toBe(27)
  })
})

// 10/12 실제로 보류된 다섯 명령 (lead 넷 · super 하나). 맞게 잡은 셋은 그대로 잡고, 잘못 잡은 둘만 푼다.
describe('잘못 붙잡던 보류 (10/12 실측 다섯 건)', () => {
  const JOB = 'C:/u/.claude/jobs/09bbf294'
  const SCRATCH = 'C:/u/AppData/Local/Temp/claude/C--x-Claude/sid1/scratchpad'
  const ROOTS = [`${JOB}/tmp`, SCRATCH]
  const ENV = { CLAUDE_JOB_DIR: JOB }

  const superGrep =
    `cd "/c/u/.claude/projects/p" && f=$(ls -t *.jsonl | head -1); grep -o '"command":"[^"]*\\(taskkill\\|Stop-Process\\|kill \\)[^"]*"' $f | sort | uniq -c`
  const leadWeb = 'Stop-Process -Id 25916 -Confirm:$false; Stop-Process -Id 145356 -Confirm:$false; Start-Sleep -Seconds 3'
  const leadHttp =
    `foreach($p in 75936,12340){ $c=(Get-CimInstance Win32_Process -Filter "ProcessId=$p").CommandLine; if ($c -like '*http.server*') { Stop-Process -Id $p -Confirm:$false } }`
  const leadKorean =
    `$k = 'C:\\Users\\user\\Desktop\\work\\ext\\go2_rl_robotlab'; $st = git -C $k status --short; if ($st -eq '?? _smoke/') { Remove-Item -Recurse -Force $k }`
  const leadBrand =
    `cd "$CLAUDE_JOB_DIR/tmp" && rm -rf brand-check && git clone -q https://github.com/example/brand-repo.git brand-check 2>&1 | tail -1; cd brand-check && git fetch -q origin`

  test('따옴표 안 검색어는 명령이 아니다 (super grep 은 풀림)', () => {
    expect(dangerous(superGrep)).toBe(null)
    expect(dangerous(`grep -n 'git reset --hard' notes.md`)).toBe(null)
    expect(dangerous(`echo "rm -rf 는 쓰지 않는다"`)).toBe(null)
  })

  test('맞게 잡던 셋은 그대로 잡는다', () => {
    expect(dangerous(leadWeb)).toBe('프로세스 종료')
    expect(dangerous(leadHttp)).toBe('프로세스 종료')
    expect(dangerous(leadKorean)).toBe('Remove-Item -Recurse')
    expect(scratchTargets(leadKorean, ROOTS, ENV)).toBe(null)
  })

  test('따옴표 안을 실행하는 꼴은 따옴표를 벗기지 않는다', () => {
    expect(dangerous(`powershell -NoProfile -Command "Stop-Process -Id 104568 -Force"`)).toBe('프로세스 종료')
    expect(dangerous(`bash -c "rm -rf /c/w/out"`)).toBe('rm -r')
    expect(dangerous(`echo "$(taskkill /PID 1 /F)"`)).toBe('프로세스 종료')
    expect(dangerous(`& "taskkill" /PID 1`)).toBe('프로세스 종료')
    expect(dangerous(`rm -rf "$OUT"`)).toBe('rm -r')
  })

  test('자기 임시 자리 안 삭제는 풀린다 (lead brand-check)', () => {
    expect(dangerous(leadBrand)).toBe('rm -r')
    // 경로는 normPath 꼴 (드라이브 소문자)
    const n = (p: string) => p.replace(/^C:/, 'c:')
    expect(scratchTargets(leadBrand, ROOTS, ENV)).toEqual([n(`${JOB}/tmp/brand-check`)])
    expect(scratchTargets(`T="$CLAUDE_JOB_DIR/tmp/brk" && rm -rf "$T" && mkdir -p "$T"`, ROOTS, ENV)).toEqual([n(`${JOB}/tmp/brk`)])
    expect(scratchTargets(`$t = '${SCRATCH}\\old'; Remove-Item -Recurse -Force $t`, ROOTS, ENV)).toEqual([n(`${SCRATCH}/old`)])
  })

  test('조금이라도 못 푸는 대상은 그대로 잡는다', () => {
    for (const cmd of [
      `rm -rf "$CLAUDE_JOB_DIR/tmp/../x"`,
      `rm -rf "$CLAUDE_JOB_DIR/tmp"`,
      `cd "$CLAUDE_JOB_DIR/tmp" && rm -rf *`,
      `rm -rf $UNKNOWN/x`,
      `rm -rf brand-check`,
      `rm -rf "$CLAUDE_JOB_DIR/tmp/a" C:/w/repo`,
      `rm -rf "$CLAUDE_JOB_DIR/tmp/a" && git reset --hard`,
      `cd "$CLAUDE_JOB_DIR/tmp" && cd .. && rm -rf x`,
      `rm -rf ~/x`,
    ])
      expect(scratchTargets(cmd, ROOTS, ENV)).toBe(null)
    // 자리를 모르면 아무것도 풀지 않는다
    expect(scratchTargets(leadBrand, [], ENV)).toBe(null)
    expect(scratchTargets(leadBrand, ROOTS, {})).toBe(null)
  })

  // 10/12 팀장 결정 「보류 줄이기」: 막는 것은 git 기록 파괴뿐. 지우기 · 프로세스 종료는 통과시키고 단위 기록과 알림으로 남긴다.
  test('계기판에서: 다섯 건 모두 통과, 지우기 · 종료는 기록, 자기 임시 자리 삭제는 기록도 안 함, git 파괴는 막음', async ($, on) => {
    world(on)
    permitBeneath(on)
    const files = new Map<string, string>()
    const toasts: string[] = []
    mock.env(on, { USERPROFILE: 'C:/u', TEMP: 'C:/u/AppData/Local/Temp' })
    on('session.id', async () => ({ value: '09bbf294-fda0' }))
    on('session.cwd', async () => ({ value: 'C:/x/Claude' }))
    on('session.repo', async () => ({ value: null }))
    on('ui.toast', async ($, e) => {
      toasts.push(String((e as { text?: unknown }).text ?? e))
      return { value: undefined } as never
    })
    on('fs.exists', async ($, e) => ({ value: files.has(e.path) }))
    on('fs.read', async ($, e) => {
      if (/wt-a[\\/]\.git$/.test(e.path)) return { value: 'gitdir: C:/w/repo/.git/worktrees/wt-a' }
      if (files.has(e.path)) return { value: files.get(e.path)! }
      throw new Error('ENOENT')
    })
    on('fs.write', async ($, e) => {
      files.set(e.path, e.text)
      return { value: undefined }
    })
    const check = async (command: string) => (await $.tool.check({ tool: 'Bash', input: { command } } as never)).decision
    for (const c of [superGrep, leadBrand, leadWeb, leadHttp, leadKorean]) expect(await check(c)).toBe('allow')
    // 실제 사고가 났던 종류는 계속 막는다 (지우기와 섞여 있어도)
    expect(await check('git reset --hard HEAD')).toBe('deny')
    expect(await check(`rm -rf "$CLAUDE_JOB_DIR/tmp/a" && git checkout -- .`)).toBe('deny')
    expect(await check('git push --force origin main')).toBe('deny')
    // 기록: 종료 둘과 한글 경로 삭제만. 자기 임시 자리(brand-check)와 검색(grep)은 없다
    const unit = [...files.entries()].find(([p]) => /units/.test(p))?.[1] ?? ''
    expect(unit).toContain('프로세스 종료: Stop-Process -Id 25916')
    expect(unit).toContain('Remove-Item -Recurse: $k = ')
    expect(unit).not.toContain('brand-check')
    expect(unit).not.toContain('grep -o')
    expect(toasts.some(t => t.includes('기록함 (막지 않음)'))).toBe(true)
  })
})
