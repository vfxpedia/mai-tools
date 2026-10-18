"""AI coding session usage as a resource (DESIGN.md section 9e): plan limits and per-session spend of Claude Code and Codex.

The source is what the session gauges (mods/mai-gauge, mods/mai-codex-gauge) already record under the gauge home, by default ~/.mai:
  limits.json                    plan limit use in percent with the reset time, per account
  sessions/<id>.json             session name, what it says it is doing, context use
  costlog/<local date>/<id>.json  one record per turn
The gauges read these from the signed-in CLIs themselves, so a user who is logged in sees them without any key.

Boundary (review R1): a file is read only when its real path stays inside the real gauge home (a junction or link that leads out is
refused), it is a regular file with one link (a hard link to a file elsewhere is refused), and it is at most MAX_BYTES. Directories are
read up to MAX_FILES entries. What leaves this module is rebuilt field by field with fixed types: short strings for the session id,
name and "doing" line, finite numbers in range for the rest. Nothing is passed on as it was read, so neither credential content nor
prompt text can travel through. Unknown stays None: a missing token or cost field is never counted as 0, and every sum says how many
turns it covers. Without a gauge home the answer is "no usage source", never zero.
"""
import datetime
import json
import math
import os
import stat
import time

DAY = 86400
MAX_BYTES = 4 * 2 ** 20
MAX_FILES = 500


class Refused(Exception):
    pass


def _inside(root_real, path):
    real = os.path.realpath(path)
    try:
        return os.path.commonpath([root_real, real]) == root_real
    except ValueError:                     # different drives
        return False


def _load(root_real, path):
    """JSON from a regular, single-link file inside the gauge home, or None. Raises Refused for a file that breaks the boundary."""
    if not _inside(root_real, path):
        raise Refused('leads outside the gauge home: %s' % os.path.basename(path))
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise Refused('not a regular file: %s' % os.path.basename(path))
    if st.st_nlink > 1:
        raise Refused('has more than one hard link: %s' % os.path.basename(path))
    if st.st_size > MAX_BYTES:
        raise Refused('larger than %d bytes: %s' % (MAX_BYTES, os.path.basename(path)))
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _list(root_real, d, problems):
    if not os.path.isdir(d):
        return []
    if not _inside(root_real, d):
        problems.append('refused: %s leads outside the gauge home' % os.path.basename(d))
        return []
    names = sorted(n for n in os.listdir(d) if n.endswith('.json'))
    if len(names) > MAX_FILES:
        problems.append('%s has %d files; read the first %d' % (os.path.basename(d), len(names), MAX_FILES))
    return names[:MAX_FILES]


def _num(v, lo=None, hi=None):
    """A finite number in range, else None. Booleans are not numbers here."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return None
    return v


def _text(v, n):
    return v[:n] if isinstance(v, str) else None


def _iso(ms):
    ms = _num(ms, 0)
    if ms is None:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _last(series):
    """Latest reading of a list as (at_ms, pct, reset), or None."""
    good = []
    for x in series if isinstance(series, list) else []:
        if isinstance(x, dict) and _num(x.get('pct'), 0, 100) is not None and _num(x.get('at'), 0) is not None:
            good.append(x)
    return max(good, key=lambda x: x['at']) if good else None


def engine_of(account):
    return 'codex' if isinstance(account, str) and account.startswith('codex') else 'claude'


def limits(root_real, now_ms, problems):
    try:
        d = _load(root_real, os.path.join(root_real, 'limits.json'))
    except Refused as e:
        problems.append('refused limits.json: %s' % e)
        return None
    if not isinstance(d, dict):
        return None
    out = []
    for account, windows in list(d.items())[:50]:
        if not isinstance(windows, dict) or account in ('five_hour', 'seven_day'):   # the old flat layout of early gauges: skipped
            continue
        row = {'account': _text(account, 80), 'engine': engine_of(account)}
        for w in ('five_hour', 'seven_day'):
            last = _last(windows.get(w))
            if last is None:
                row[w] = None
                continue
            reset, reset_ms = _text(last.get('reset'), 40), None
            if reset:
                try:
                    reset_ms = datetime.datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp() * 1000
                except ValueError:
                    reset = None
            expired = reset_ms is not None and reset_ms <= now_ms
            # after the reset time the recorded percent belongs to a window that is over: unknown until the gauge reads it again
            row[w] = {'pct': None if expired else last['pct'], 'reset': reset, 'read_at': _iso(last['at']),
                      'note': 'window reset since last reading' if expired else None}
        out.append(row)
    return sorted(out, key=lambda r: (r['engine'], r['account'] or ''))


def _turn_cost(e, engine):
    """Cost of one turn in USD or None. The Codex gauge writes costUsd null when it has no price; its older versions wrote 0 for the
    same meaning, so a Codex 0 without a costSource is unknown (mods/mai-codex-gauge/src/store.mjs). A Claude 0 is a real 0."""
    c = _num(e.get('costUsd'), 0)
    if engine == 'codex' and c == 0 and not e.get('costSource'):
        c = None
    if c is None:
        c = _num(e.get('estimatedCostUsd'), 0)
    return c


def _turn_tokens(e):
    t = _num(e.get('totalTokens'), 0)
    if t is not None:
        return t
    i, o = _num(e.get('inputTokens'), 0), _num(e.get('outputTokens'), 0)
    return i + o if i is not None and o is not None else None       # one side missing: the turn's total is unknown


def sessions(root_real, now_ms, problems, today=None, max_age_s=DAY):
    """Sessions updated within max_age_s, with today's turns, cost and tokens from the cost log. turns_today is None when there is no
    cost log for the session today (not 0); cost and tokens carry how many of those turns they cover."""
    sdir = os.path.join(root_real, 'sessions')
    rows = {}
    for name in _list(root_real, sdir, problems):
        try:
            d = _load(root_real, os.path.join(sdir, name))
        except Refused as e:
            problems.append('refused session file: %s' % e)
            continue
        if not isinstance(d, dict):
            continue
        upd = _num(d.get('updatedAt'), 0)
        if upd is None or (now_ms - upd) / 1000 > max_age_s:
            continue
        sid = _text(d.get('id'), 64) or name[:-5][:64]
        rows[sid] = {'id': sid, 'name': _text(d.get('name'), 40), 'doing': _text(d.get('doing'), 160) or '',
                     'context_pct': _num(d.get('contextPercent'), 0, 100), 'last_active_s': round(max(0, now_ms - upd) / 1000),
                     'engine': None, 'turns_today': None, 'cost_usd_today': None, 'cost_turns': 0, 'tokens_today': None, 'token_turns': 0}
    today = today or datetime.date.today().isoformat()
    cdir = os.path.join(root_real, 'costlog', today)
    for name in _list(root_real, cdir, problems):
        try:
            d = _load(root_real, os.path.join(cdir, name))
        except Refused as e:
            problems.append('refused cost log file: %s' % e)
            continue
        if not isinstance(d, dict):
            continue
        sid = _text(d.get('sessionId'), 64) or name[:-5][:64]
        events = d.get('events') if isinstance(d.get('events'), list) else []
        turns = [e for e in events if isinstance(e, dict) and e.get('kind') == 'turn']
        r = rows.get(sid)
        if r is None:
            last = max((_num(e.get('at'), 0) or 0 for e in turns), default=0)
            if not last or (now_ms - last) / 1000 > max_age_s:
                continue
            r = rows[sid] = {'id': sid, 'name': _text(d.get('name'), 40), 'doing': '', 'context_pct': None,
                             'last_active_s': round(max(0, now_ms - last) / 1000), 'engine': None, 'turns_today': None,
                             'cost_usd_today': None, 'cost_turns': 0, 'tokens_today': None, 'token_turns': 0}
        engine = engine_of(d.get('account'))
        costs = [c for c in (_turn_cost(e, engine) for e in turns) if c is not None]
        toks = [t for t in (_turn_tokens(e) for e in turns) if t is not None]
        r.update(engine=engine, turns_today=len(turns),
                 cost_usd_today=round(sum(costs), 2) if costs else None, cost_turns=len(costs),
                 tokens_today=int(sum(toks)) if toks else None, token_turns=len(toks))
    return sorted(rows.values(), key=lambda r: r['last_active_s'])


def read(home=None, clock=time.time):
    home = os.path.expanduser(home or os.environ.get('MAI_HOME') or '~/.mai')
    now_ms = clock() * 1000
    if not os.path.isdir(home):
        return {'available': False, 'home': home, 'reason': 'no usage source: the session gauges have not written %s' % home}
    root_real = os.path.realpath(home)
    problems = []
    lim = limits(root_real, now_ms, problems)
    ses = sessions(root_real, now_ms, problems)
    return {'available': True, 'home': home, 'limits': lim, 'limits_problem': None if lim is not None else 'limits.json missing or unreadable',
            'sessions': ses, 'problems': problems, 'read_at': _iso(now_ms)}
