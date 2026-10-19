"""Decisions of mai-resume, with no I/O: given the time, the plan limits, the list of terminals and what each terminal
shows, return the messages to send and the new state. Everything outside (Orca, files, the clock) is passed in, so every
rule here is tested with known inputs (tests/test_core.py).

Rules (DESIGN.md):
  warn    when a plan window of an engine passes its warning percent before its reset, every live session of that engine
          gets one warning for that window (same reset time = same window). A session that appears later in the same
          window gets it too. When the limits file is stale, a lower percent is used so the warning is early, not late.
  hit     a session whose screen says "You've hit your ... limit . resets <time>" is stopped already; it is booked for a
          resume at that reset time even if the limits file never showed the window filling up.
  resume  after reset + grace, every session that was warned or seen stopped in that window gets one resume message.
  deliver a message is never typed into a prompt that already holds text (someone is typing); it waits and is retried.
          The same message id is never sent twice. Messages are one line (multi-line text was cut at the first line
          when sent through cmd, measured by lead on 10/20).
"""
import datetime as dt
import re

DEFAULTS = {
    'warn_pct': {'five_hour': 93, 'seven_day': 95},
    'stale_warn_pct': 85,          # used instead of warn_pct while the limits file is stale
    'limits_stale_s': 600,
    'resume_grace_s': 180,
    'poll_s': 60,
    'defer_give_up_s': 1800,       # a message that could not be delivered for this long is dropped (and logged)
    'engines': {'claude': {'account': 'default'}, 'codex': {'account_prefix': 'codex:'}},
    'messages': {
        'warn': '[mai-resume {now}] {engine} {window} limit at {pct}% (resets {reset}). Do not start new large work. '
                'Finish only up to a safe point (saved files, a committable unit), write your HANDOFF (what you did, '
                'where you stopped, the next step, uncommitted files) and stop. Do not touch running GPU jobs. '
                'mai-resume will send a resume message after the reset.',
        'resume': '[mai-resume {now}] The {engine} {window} limit has reset. Re-read your HANDOFF and the last '
                  'instruction, then continue the stopped work. If it was finished, go on with the next task.',
    },
}

HIT = re.compile(r"You['’]ve hit your (?P<what>.+?) limit\s*[·.]\s*resets\s+(?P<when>[^()\n]+?)\s*\((?P<tz>[^)\n]+)\)")
WHEN = re.compile(r'^(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),\s*)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)$', re.I)
MONTHS = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
FIXED_TZ = {'Asia/Seoul': 9, 'Asia/Tokyo': 9, 'UTC': 0, 'Etc/UTC': 0}   # used when the zoneinfo database is missing (Windows)
CLAUDE_PLACEHOLDER = re.compile(r'^Try "[^"]*"$')
SPINNER = re.compile(r'…\s*\(\d+(?:m \d+)?s|esc to interrupt', re.I)
CODEX_PLACEHOLDERS = ('ask codex to do anything', 'find and fix a bug', 'explain this codebase', 'summarize recent commits',
                      'implement {feature}', 'write tests for', 'improve documentation', 'run /review')


def merged(cfg):
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def one_line(text):
    """Collapse all whitespace runs (including newlines) to single spaces."""
    return ' '.join(str(text).split())


def _utc(ms):
    return dt.datetime.fromtimestamp(ms / 1000.0, dt.timezone.utc)


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_iso(s):
    return dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def windows_of(limits, engine, cfg, now):
    """Latest reading per plan window of one engine: {window: {pct, reset, age_s, stale}}. Unreadable entries are skipped."""
    eng = cfg['engines'].get(engine) or {}
    accounts = []
    if 'account' in eng:
        accounts = [eng['account']]
    elif 'account_prefix' in eng:
        accounts = [a for a in (limits or {}) if isinstance(a, str) and a.startswith(eng['account_prefix'])]
    out = {}
    for acc in accounts:
        wins = (limits or {}).get(acc)
        if not isinstance(wins, dict):
            continue
        for w, series in wins.items():
            if not isinstance(series, list):
                continue
            good = [e for e in series if isinstance(e, dict) and isinstance(e.get('at'), (int, float))
                    and isinstance(e.get('pct'), (int, float)) and isinstance(e.get('reset'), str)]
            if not good:
                continue
            e = max(good, key=lambda x: x['at'])
            try:
                reset = _parse_iso(e['reset'])
            except ValueError:
                continue
            age = (now - _utc(e['at'])).total_seconds()
            cur = {'pct': float(e['pct']), 'reset': reset, 'age_s': age, 'stale': age > cfg['limits_stale_s']}
            if w not in out or cur['pct'] > out[w]['pct']:
                out[w] = cur
    return out


def discover(terminals, only=None, exclude=None):
    """Live agent sessions from `orca terminal list --json`: claude and codex panes that are connected and writable.
    `only` (a list of handles) limits the guard to those panes, used for a real-pane test; `exclude` leaves panes out."""
    found = []
    for t in terminals or []:
        if not isinstance(t, dict):
            continue
        eng = t.get('agentIdentity')
        if only and t.get('handle') not in only or exclude and t.get('handle') in exclude:
            continue
        if eng in ('claude', 'codex') and t.get('connected') and t.get('writable') and t.get('handle'):
            found.append({'handle': t['handle'], 'engine': eng, 'title': t.get('title') or ''})
    return found


def parse_reset(when, tz, now):
    """'7:10pm' or 'Sep 19, 8pm' in zone tz -> aware datetime of the next such moment at or after now - 12 h."""
    m = WHEN.match(when.strip())
    if not m:
        return None
    hour = int(m.group('h')) % 12 + (12 if m.group('ap').lower() == 'pm' else 0)
    minute = int(m.group('m') or 0)
    zone = None
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz.strip())
    except Exception:
        if tz.strip() in FIXED_TZ:
            zone = dt.timezone(dt.timedelta(hours=FIXED_TZ[tz.strip()]))
    if zone is None:
        return None
    local_now = now.astimezone(zone)
    if m.group('mon'):
        mon = MONTHS.get(m.group('mon').title())
        if not mon:
            return None
        cand = local_now.replace(month=mon, day=int(m.group('day')), hour=hour, minute=minute, second=0, microsecond=0)
        if cand < local_now - dt.timedelta(days=180):
            cand = cand.replace(year=cand.year + 1)
        return cand
    cand = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if cand < local_now - dt.timedelta(hours=12):
        cand += dt.timedelta(days=1)
    return cand


def screen_state(engine, screen, now):
    """{'hit': (what, reset) or None, 'typing': bool, 'busy': bool} read from the visible screen of a pane.
    `screen` is the screen text, or a dict {'text': ..., 'prompt_trailing': n} where n is the trailing-space count of the
    last prompt row. Orca's screen read does not show text typed but not yet submitted into a Claude prompt (measured
    10/20: the row stays a bare marker), but that row's trailing space goes from 1 to 0 while text is there, so a bare
    marker with 0 trailing spaces counts as typing."""
    trailing = None
    if isinstance(screen, dict):
        trailing = screen.get('prompt_trailing')
        screen = screen.get('text')
    text = screen or ''
    hit = None
    for m in HIT.finditer(text):
        r = parse_reset(m.group('when'), m.group('tz'), now)
        if r is not None:
            hit = (m.group('what').strip().lower(), r)
    lines = [ln.replace(' ', ' ').rstrip() for ln in text.splitlines()]
    mark = '❯' if engine == 'claude' else '›'
    prompts = [ln.strip()[len(mark):].strip() for ln in lines if ln.strip().startswith(mark)]
    typed = prompts[-1] if prompts else ''
    if engine == 'codex' and typed.lower().startswith(CODEX_PLACEHOLDERS):
        typed = ''
    if engine == 'claude' and CLAUDE_PLACEHOLDER.match(typed):     # an empty prompt shows a hint: Try "fix typecheck errors"
        typed = ''
    if engine == 'claude' and prompts and not typed and trailing == 0:
        typed = '(hidden typed text)'
    return {'hit': hit, 'typing': bool(typed), 'busy': bool(SPINNER.search(text))}


def _fmt(cfg, kind, engine, window, pct, reset, now_local):
    t = cfg['messages'][kind].format(now=now_local.strftime('%m/%d %H:%M'), engine=engine, window=window,
                                     pct=int(round(pct)) if pct is not None else '?',
                                     reset=reset.astimezone(now_local.tzinfo).strftime('%m/%d %H:%M'))
    return one_line(t)


def tick(state, now, limits, terminals, screens, cfg, local_tz=None):
    """One decision round. Returns (state, sends, log_lines). sends = [(handle, text, message_id)].
    `screens` maps handle -> screen text (missing = could not read; such a pane is not typed into)."""
    cfg = merged(cfg)
    st = {'sent': dict(state.get('sent') or {}), 'windows': dict(state.get('windows') or {}),
          'pending': list(state.get('pending') or [])}
    logs = []
    now_local = now.astimezone(local_tz) if local_tz else now.astimezone()
    sessions = discover(terminals, cfg.get('only_handles'), cfg.get('exclude_handles'))
    by_engine = {}
    for s in sessions:
        by_engine.setdefault(s['engine'], []).append(s)
    live = {s['handle'] for s in sessions}

    def queue(handle, text, mid):
        if mid in st['sent'] or any(p['id'] == mid for p in st['pending']):
            return
        st['pending'].append({'handle': handle, 'text': text, 'id': mid, 'since': _iso(now)})

    # 1. plan windows from the limits file
    for engine, group in by_engine.items():
        for window, cur in windows_of(limits, engine, cfg, now).items():
            if now >= cur['reset']:
                continue
            limit_pct = cfg['stale_warn_pct'] if cur['stale'] else cfg['warn_pct'].get(window, 95)
            if cur['pct'] < limit_pct:
                continue
            key = '%s|%s|%s' % (engine, window, _iso(cur['reset']))
            w = st['windows'].setdefault(key, {'resume_at': _iso(cur['reset'] + dt.timedelta(seconds=cfg['resume_grace_s'])),
                                               'handles': [], 'resumed': False})
            if key not in state.get('windows', {}):
                logs.append('WARN %s pct=%s stale=%s' % (key, cur['pct'], cur['stale']))
            text = _fmt(cfg, 'warn', engine, window, cur['pct'], cur['reset'], now_local)
            for s in group:
                if s['handle'] not in w['handles']:
                    w['handles'].append(s['handle'])
                queue(s['handle'], text, 'warn|%s|%s' % (s['handle'], key))

    # 2. sessions whose screen already says the limit was hit
    for s in sessions:
        ss = screen_state(s['engine'], screens.get(s['handle']), now)
        if not ss['hit']:
            continue
        what, reset = ss['hit']
        key = '%s|%s|%s' % (s['engine'], 'hit:' + what, _iso(reset))
        w = st['windows'].setdefault(key, {'resume_at': _iso(reset + dt.timedelta(seconds=cfg['resume_grace_s'])),
                                           'handles': [], 'resumed': False})
        if s['handle'] not in w['handles']:
            w['handles'].append(s['handle'])
            logs.append('HIT %s %s' % (s['handle'], key))

    # 3. resume after reset + grace
    for key, w in st['windows'].items():
        if w['resumed'] or now < _parse_iso(w['resume_at']):
            continue
        engine, window, _ = key.split('|', 2)
        text = _fmt(cfg, 'resume', engine, window.replace('hit:', ''), None, _parse_iso(w['resume_at']), now_local)
        for h in w['handles']:
            if h in live:
                queue(h, text, 'resume|%s|%s' % (h, key))
        w['resumed'] = True
        logs.append('RESUME %s to %d' % (key, len([h for h in w['handles'] if h in live])))

    # 4. deliver what is pending, never into a prompt that holds text
    sends, keep = [], []
    for p in st['pending']:
        if p['handle'] not in live:
            logs.append('DROP %s (pane gone)' % p['id'])
            continue
        age = (now - _parse_iso(p['since'])).total_seconds()
        eng = next(s['engine'] for s in sessions if s['handle'] == p['handle'])
        scr = screens.get(p['handle'])
        if scr is None or screen_state(eng, scr, now)['typing']:
            if age > cfg['defer_give_up_s']:
                logs.append('DROP %s (prompt busy with typed text for %d s)' % (p['id'], age))
            else:
                keep.append(p)
            continue
        sends.append((p['handle'], one_line(p['text']), p['id']))
        st['sent'][p['id']] = _iso(now)
    st['pending'] = keep

    # forget windows and sent ids older than 8 days so the state file stays small
    cutoff = now - dt.timedelta(days=8)
    st['windows'] = {k: v for k, v in st['windows'].items() if _parse_iso(v['resume_at']) > cutoff}
    st['sent'] = {k: v for k, v in st['sent'].items() if _parse_iso(v) > cutoff}
    st['heartbeat'] = _iso(now)
    return st, sends, logs
