"""Check a work list against rules C1 to C10 and build the document the mai-watch "작업" tab shows.

Input is either the new WORK.tsv (with WORK-events.tsv next to it, when present) or the eight-column WORKLIST.tsv still in use;
the old list is converted in memory with the same code as `convert`, so the tab follows the real list from today. The check only
reads: it never edits the list, never sends a message. Notifying the owner's window (C1 · C2) belongs to the operations check
that runs this.

Rules (design `os/worklist-tool-design.md` 4 절):
  C1 FAIL  open/doing, end_plan passed, no evidence          C6 FAIL  waits for the owner on a topic that is already locked
  C2 WARN  open, start_plan passed, not started              C7 WARN  evidence present but still open/doing
  C3 FAIL  doing/done while an `after` item is not done      C8 WARN  doing with no recorded change for 24 h
  C4 WARN  owner works P2/P3 while a ready P0/P1 waits       C9 INFO  waiting for the owner's decision over 12 h
  C5 FAIL  hold without wait_for, replaced without a valid   C10 FAIL a decision (locked, cancelled, replaced, postponed
           replaced_by, cancelled without decision, end_plan          end_plan) without a real decided_at, or decided after
           postponed without why and decision                         it was written down
  C11 FAIL done without evidence that opens, or without decided_at as ISO with a time zone offset (lead G25 · analyst W39
           counterexample 11/07: a done row pointing at a file that was never made passed every other rule)
"""
import datetime
import os
import time

from . import convert as conv
from . import schema

SCHEMA = 'mai-work-check-v1'
OWNER_WORDS = ('팀장', 'owner')        # wait_for that names the owner; topic after a colon: "팀장:d-drive-cleanup-timing"
LEVEL_ORDER = {'FAIL': 0, 'WARN': 1, 'INFO': 2}
PRIORITY_ORDER = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}


def parse_at(value):
    """`at:YYYY-MM-DDTHH:MM` (local time) -> epoch seconds; anything else -> None."""
    if not value or not value.startswith('at:'):
        return None
    try:
        return datetime.datetime.strptime(value[3:], '%Y-%m-%dT%H:%M').timestamp()
    except ValueError:
        return None


def parse_ts(value):
    """ISO time with or without zone (events) -> epoch seconds; `unknown`, empty or a guess like 19:3x -> None."""
    if not value or value == 'unknown':
        return None
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def iso_with_zone(value):
    """True for a full ISO time with a zone offset, e.g. 2026-11-06T17:19:44+09:00 (no zone, a date alone or 17:1x -> False)."""
    if not value or 'T' not in value:
        return False
    try:
        return datetime.datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


# Windows evidence paths read on Linux ai-lx01 (11/10): the Windows disks are mounted at /mnt/win-c (ro) and /mnt/win-d (rw),
# and the 11/09 D: cleanup moved these roots behind junctions that Linux may not follow, so their real folders come first.
# Longest prefix wins. Override with MAI_WORK_PATH_MAP="WIN=LINUX;WIN=LINUX". Windows itself never rewrites.
PATH_MAP = (('C:/Users/AI-WS01/s2_lab', '/mnt/win-d/mai/data/foothold/s2_lab'),
            ('D:/mai-wt-archive', '/mnt/win-d/mai/wt-archive'), ('D:/mai-wt', '/mnt/win-d/mai/wt'),
            ('D:/mai-tmp', '/mnt/win-d/mai/tmp'), ('D:/mai-cache', '/mnt/win-d/mai/cache'),
            ('D:/mai-video', '/mnt/win-d/mai/data/foothold/video'),
            ('C:', '/mnt/win-c'), ('D:', '/mnt/win-d'))


def local_path(path, os_name=None, env=None):
    """A Windows evidence path as this machine can open it (identity on Windows or for paths that are not Windows paths)."""
    os_name = os.name if os_name is None else os_name
    env = os.environ if env is None else env
    if os_name == 'nt' or len(path) < 2 or path[1] != ':':
        return path
    p = path.replace('\\', '/')
    pairs = [tuple(x.split('=', 1)) for x in (env.get('MAI_WORK_PATH_MAP') or '').split(';') if '=' in x] or PATH_MAP
    for win, lin in sorted(pairs, key=lambda kv: -len(kv[0])):
        if p.lower() == win.lower() or p.lower().startswith(win.lower().rstrip('/') + '/'):
            return lin.rstrip('/') + p[len(win.rstrip('/')):]
    return path


def evidence_present(spec):
    """Same meaning as the operations check: `path` exists, or `path::text` exists and contains text. '-' never counts."""
    if not spec or spec == '-':
        return False
    path, _, needle = spec.partition('::')
    path = local_path(path)
    if not os.path.exists(path):
        return False
    if not needle:
        return True
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return needle in f.read()
    except OSError:
        return False


def due_state(value, now, it):
    """('passed' | 'soon' | 'later' | 'iter-unknown' | 'none', minutes past (negative = minutes left) or updates past)."""
    t = parse_at(value)
    if t is not None:
        left = t - now
        return ('passed' if left <= 0 else 'soon' if left < 1800 else 'later'), round(-left / 60)
    if value and value.startswith('iter:'):
        try:
            n = int(value[5:])
        except ValueError:
            return 'none', None
        if it is None:
            return 'iter-unknown', None
        return ('passed' if it >= n else 'soon' if n - it <= 50 else 'later'), it - n
    return 'none', None


def owner_topic(wait_for):
    """'팀장:topic' -> (True, 'topic'); '팀장 결정 W41' -> (True, ''); other -> (False, '')."""
    w = (wait_for or '').strip()
    for word in OWNER_WORDS:
        if w.startswith(word):
            rest = w[len(word):]
            return True, rest[1:].strip() if rest.startswith(':') else ''
    return False, ''


def load(path):
    """Rows in the new columns and the events, from either format. Raises ConvertError on a list it cannot read safely."""
    text, header, rows = conv.read_tsv(path)
    if conv.legacy_extras(header) is not None:          # the old eight columns, maybe with some WORK.tsv columns already added
        work, _ = conv.convert_rows(header, rows, os.path.basename(path), '', '')
        return 'legacy', work, []
    if header != schema.WORK_COLUMNS:
        raise conv.ConvertError('columns are neither WORK.tsv nor the old WORKLIST.tsv: %s' % list(header))
    ev_path = os.path.join(os.path.dirname(path), 'WORK-events.tsv')
    events = conv.read_tsv(ev_path)[2] if os.path.exists(ev_path) else []
    return 'work', rows, events


def check(rows, events, now=None, it=None):
    now = time.time() if now is None else now
    by_id = {r['id']: r for r in rows}
    last_event = {}
    for e in events:
        t = parse_ts(e.get('ts'))
        if t is not None:
            last_event[e['id']] = max(last_event.get(e['id'], 0), t)
    locked = {r['locked']: r for r in rows if r.get('locked')}
    findings = []

    def add(rule, level, r, msg):
        findings.append({'rule': rule, 'level': level, 'id': r['id'], 'owner': r.get('owner', ''),
                         'priority': r.get('priority', ''), 'msg': msg})

    def deps_done(r):
        return all(by_id.get(a.strip(), {}).get('status') == 'done' for a in (r.get('after') or '').split(',') if a.strip())

    for r in rows:
        st, ev = r['status'], evidence_present(r.get('evidence'))
        live = st in ('open', 'doing')
        if st not in schema.STATUSES:
            add('C5', 'FAIL', r, '모르는 상태 %r' % st)
            continue
        end_state, end_by = due_state(r.get('end_plan'), now, it)
        if live and end_state == 'passed' and not ev:
            unit = '회' if (r.get('end_plan') or '').startswith('iter:') else '분'
            add('C1', 'FAIL', r, '마감 %s 이 %s %s 지남 · 증거 없음' % (r['end_plan'][3:] if r['end_plan'].startswith('at:') else r['end_plan'], end_by, unit))
        start_state, start_by = due_state(r.get('start_plan'), now, it)
        if st == 'open' and start_state == 'passed' and not r.get('start_actual'):
            add('C2', 'WARN', r, '시작 예정 %s 지남 · 아직 시작 안 함' % r['start_plan'])
        for a in (x.strip() for x in (r.get('after') or '').split(',') if x.strip()):
            dep = by_id.get(a)
            if dep is None:
                add('C3', 'FAIL', r, '선행 %s 이 목록에 없음' % a)
            elif st in ('doing', 'done') and dep['status'] != 'done':
                add('C3', 'FAIL', r, '%s 인데 선행 %s 는 %s' % (st, a, dep['status']))
        if st == 'hold' and not (r.get('wait_for') or '').strip():
            add('C5', 'FAIL', r, '보류인데 무엇을 기다리는지 없음')
        if st == 'replaced' and r.get('replaced_by') not in by_id:
            add('C5', 'FAIL', r, '대체 id %r 이 목록에 없음' % r.get('replaced_by'))
        if st == 'cancelled' and not r.get('decision'):
            add('C5', 'FAIL', r, '취소인데 근거 결정 줄 없음')
        waits, topic = owner_topic(r.get('wait_for'))
        if live or st == 'hold':
            if waits and topic and topic in locked and locked[topic]['id'] != r['id']:
                d = locked[topic]
                add('C6', 'FAIL', r, '팀장에게 %s 를 다시 물음 · 이미 %s 에서 확정 (%s · %s)'
                    % (topic, d['id'], d.get('decided_at') or '시각 모름', d.get('decision') or '근거 줄 없음'))
            if ev:
                add('C7', 'WARN', r, '증거가 있는데 아직 %s · 끝 처리' % st)
            if waits and r['id'] in last_event and now - last_event[r['id']] > 12 * 3600:
                add('C9', 'INFO', r, '팀장 결정 %d 시간째 기다림' % ((now - last_event[r['id']]) // 3600))
        if st == 'doing':
            since = last_event.get(r['id']) or parse_ts(r.get('start_actual'))
            if since and now - since > 24 * 3600:
                add('C8', 'WARN', r, '진행 중인데 %d 시간 동안 기록 없음' % ((now - since) // 3600))
        decided = parse_ts(r.get('decided_at'))
        if (r.get('locked') or st in ('cancelled', 'replaced')) and decided is None:
            add('C10', 'FAIL', r, '결정인데 결정 시각이 없음 (%s)' % (r.get('decided_at') or '빈칸'))
        if st == 'done' and not (ev and iso_with_zone(r.get('decided_at'))):
            add('C11', 'FAIL', r, '끝인데 %s' % ' · '.join(x for x in (
                '' if ev else '증거 파일이 안 열림 (%s)' % (r.get('evidence') or '빈칸'),
                '' if iso_with_zone(r.get('decided_at')) else '결정 시각이 시간대 있는 ISO 가 아님 (%s)' % (r.get('decided_at') or '빈칸')) if x))
    # C4: priority inversion per owner
    for owner in {r.get('owner') for r in rows}:
        mine = [r for r in rows if r.get('owner') == owner]
        low = [r for r in mine if r['status'] == 'doing' and PRIORITY_ORDER.get(r.get('priority'), 9) >= 2]
        ready = [r for r in mine if r['status'] == 'open' and PRIORITY_ORDER.get(r.get('priority'), 9) <= 1 and deps_done(r)]
        for r in low:
            if ready:
                add('C4', 'WARN', r, '%s 를 하는 동안 %s 가 기다림' % (r.get('priority'), ', '.join(x['id'] for x in ready[:3])))
    # C5 / C10 from the change records: end_plan postponed without reasons, decided after written
    for e in events:
        r = by_id.get(e.get('id'), {'id': e.get('id'), 'owner': '', 'priority': ''})
        if e.get('field') == 'end_plan' and e.get('event') == 'change':
            a, b = parse_at(e.get('from')), parse_at(e.get('to'))
            if a and b and b > a:
                if not e.get('why') or not e.get('decision'):
                    add('C5', 'FAIL', r, '마감을 %s -> %s 로 미룸 · 이유 · 근거 줄 없음' % (e['from'], e['to']))
                if parse_ts(e.get('decided_at')) is None:
                    add('C10', 'FAIL', r, '마감을 미뤘는데 결정 시각 없음')
        d, t = parse_ts(e.get('decided_at')), parse_ts(e.get('ts'))
        if d and t and d > t + 60:
            add('C10', 'FAIL', r, '결정 시각 %s 이 기록 시각 %s 보다 늦음' % (e['decided_at'], e['ts']))
    findings.sort(key=lambda f: (LEVEL_ORDER[f['level']], PRIORITY_ORDER.get(f['priority'], 9), f['id'], f['rule']))
    return findings


def document(path, now=None, it=None):
    """The JSON the tab draws. A list that cannot be read becomes an `error` document, never an exception."""
    now = time.time() if now is None else now
    try:
        fmt, rows, events = load(path)
    except (OSError, conv.ConvertError) as e:
        return {'schema': SCHEMA, 'now': now, 'error': '%s: %s' % (type(e).__name__, e), 'path': path}
    findings = check(rows, events, now, it)
    flagged = {}
    for f in findings:
        flagged.setdefault(f['id'], []).append(f['rule'])
    by_id = {r['id']: r for r in rows}
    items = []
    for r in rows:
        state, by = due_state(r.get('end_plan'), now, it)
        deps = [a.strip() for a in (r.get('after') or '').split(',') if a.strip()]
        items.append({k: r.get(k, '') for k in ('id', 'title', 'owner', 'priority', 'stage', 'status', 'start_plan', 'end_plan',
                                                 'wait_for', 'replaced_by', 'locked', 'decided_at', 'source')}
                     | {'due': state, 'due_by': by, 'evidence_ok': evidence_present(r.get('evidence')),
                        'ready': r['status'] == 'open' and all(by_id.get(a, {}).get('status') == 'done' for a in deps),
                        'after': deps, 'rules': flagged.get(r['id'], [])})
    count = lambda level: sum(1 for f in findings if f['level'] == level)
    return {'schema': SCHEMA, 'now': now, 'path': path, 'format': fmt, 'mtime': os.path.getmtime(path), 'iter': it,
            'counts': {'FAIL': count('FAIL'), 'WARN': count('WARN'), 'INFO': count('INFO'),
                       'owner_wait': sum(1 for r in rows if owner_topic(r.get('wait_for'))[0] and r['status'] in ('open', 'doing', 'hold')),
                       **{s: sum(1 for r in rows if r['status'] == s) for s in schema.STATUSES}},
            'findings': findings, 'items': items, 'events': events[-20:]}
