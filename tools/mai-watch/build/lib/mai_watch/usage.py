"""AI coding session usage as a resource (DESIGN.md section 9e): plan limits and per-session spend of Claude Code and Codex.

The source is what the session gauges (mods/mai-gauge, mods/mai-codex-gauge) already record under the gauge home, by default ~/.mai:
  limits.json                    plan limit use in percent with the reset time, per account
  sessions/<id>.json             session name, what it is doing, context use
  costlog/<local date>/<id>.json  one record per turn
The gauges read these from the signed-in CLIs themselves, so a user who is logged in sees them without any key. This module opens only
those three places. It never opens credential files (for example ~/.codex/auth.json), and it never passes on prompt text from the cost
log: only counts and sums leave this module. Without a gauge home the answer is "no usage source", never zero.
"""
import datetime
import json
import os
import time

DAY = 86400


def _load(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _iso(ms):
    if not isinstance(ms, (int, float)):
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _last(series):
    """Latest {at, pct, reset} of a list, or None."""
    good = [x for x in series or [] if isinstance(x, dict) and isinstance(x.get('pct'), (int, float)) and isinstance(x.get('at'), (int, float))]
    return max(good, key=lambda x: x['at']) if good else None


def engine_of(account):
    return 'codex' if str(account).startswith('codex') else 'claude'


def limits(home, now_ms):
    d = _load(os.path.join(home, 'limits.json'))
    if not isinstance(d, dict):
        return None
    out = []
    for account, windows in d.items():
        if not isinstance(windows, dict) or account in ('five_hour', 'seven_day'):   # old flat layout kept by early gauges: skipped
            continue
        row = {'account': account, 'engine': engine_of(account)}
        for w in ('five_hour', 'seven_day'):
            last = _last(windows.get(w))
            if last is None:
                row[w] = None
                continue
            reset = last.get('reset')
            expired = False
            if isinstance(reset, str):
                try:
                    expired = datetime.datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp() * 1000 <= now_ms
                except ValueError:
                    reset = None
            # after the reset time the recorded percent belongs to a window that is over: unknown until the gauge reads it again
            row[w] = {'pct': None if expired else last['pct'], 'reset': reset, 'read_at': _iso(last['at']),
                      'read_age_s': round((now_ms - last['at']) / 1000), 'note': 'window reset since last reading' if expired else None}
        out.append(row)
    return sorted(out, key=lambda r: (r['engine'], r['account']))


def sessions(home, now_ms, today=None, max_age_s=DAY):
    """Sessions updated within max_age_s, with today's turn count and spend from the cost log."""
    sdir = os.path.join(home, 'sessions')
    rows = {}
    if os.path.isdir(sdir):
        for name in os.listdir(sdir):
            if not name.endswith('.json'):
                continue
            d = _load(os.path.join(sdir, name))
            if not isinstance(d, dict) or not isinstance(d.get('updatedAt'), (int, float)):
                continue
            age = (now_ms - d['updatedAt']) / 1000
            if age > max_age_s:
                continue
            rows[d.get('id') or name[:-5]] = {'id': d.get('id') or name[:-5], 'name': d.get('name'), 'doing': (d.get('doing') or '')[:160],
                                              'context_pct': d.get('contextPercent'), 'last_active_s': round(age), 'engine': None,
                                              'turns_today': 0, 'cost_usd_today': None, 'tokens_today': None}
    today = today or datetime.date.today().isoformat()
    cdir = os.path.join(home, 'costlog', today)
    if os.path.isdir(cdir):
        for name in os.listdir(cdir):
            if not name.endswith('.json'):
                continue
            d = _load(os.path.join(cdir, name))
            if not isinstance(d, dict):
                continue
            sid = d.get('sessionId') or name[:-5]
            turns = [e for e in d.get('events') or [] if isinstance(e, dict) and e.get('kind') == 'turn']
            r = rows.get(sid)
            if r is None:
                last = max((e.get('at') for e in turns if isinstance(e.get('at'), (int, float))), default=None)
                if last is None or (now_ms - last) / 1000 > max_age_s:
                    continue
                r = rows[sid] = {'id': sid, 'name': d.get('name'), 'doing': '', 'context_pct': None, 'last_active_s': round((now_ms - last) / 1000),
                                 'engine': None, 'turns_today': 0, 'cost_usd_today': None, 'tokens_today': None}
            r['engine'] = engine_of(d.get('account', ''))
            r['turns_today'] = len(turns)
            cost = [e.get('costUsd') or e.get('estimatedCostUsd') for e in turns]
            cost = [c for c in cost if isinstance(c, (int, float))]
            r['cost_usd_today'] = round(sum(cost), 2) if cost else None
            tok = [sum(e.get(k) or 0 for k in ('inputTokens', 'outputTokens')) for e in turns if 'inputTokens' in e or 'outputTokens' in e]
            r['tokens_today'] = sum(tok) if tok else None
    return sorted(rows.values(), key=lambda r: r['last_active_s'])


def read(home=None, clock=time.time):
    home = os.path.expanduser(home or os.environ.get('MAI_HOME') or '~/.mai')
    now_ms = clock() * 1000
    if not os.path.isdir(home):
        return {'available': False, 'home': home, 'reason': 'no usage source: the session gauges have not written %s' % home}
    lim = limits(home, now_ms)
    return {'available': True, 'home': home, 'limits': lim, 'limits_problem': None if lim is not None else 'limits.json missing or unreadable',
            'sessions': sessions(home, now_ms)}
