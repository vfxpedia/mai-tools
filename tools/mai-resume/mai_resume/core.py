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
    # stop: wrap up, write the HANDOFF and stop until the resume message. Only on a fresh reading (owner 10/20: a stop at
    # seven_day 85 % left codex idle for five days with 14 % unused).
    'warn_pct': {'five_hour': 93, 'seven_day': 98},
    # notice: keep working (owner 10/20). No stop, no hold, no resume. Sent once per window.
    'notice_pct': {'seven_day': 85},
    'stale_warn_pct': 85,          # a stale reading at or above this sends only the notice, never the stop
    'limits_stale_s': 600,
    'resume_grace_s': 180,
    'poll_s': 60,
    'defer_give_up_s': 1800,       # a message that could not be delivered for this long is dropped (and logged)
    'keepalive_stale_s': 300,      # a keep-alive not delivered within this is dropped; the next round decides afresh (owner 10/26)
    'keepalive_s': 3300,           # nudge an idle Claude session this often so its prompt cache (1 h) survives; 0 = off
    'engines': {'claude': {'account': 'default'}, 'codex': {'account_prefix': 'codex:'}},
    'messages': {
        'warn': '[mai-resume {now}] {engine} {window} limit at {pct}% (resets {reset}). Do not start new large work. '
                'Finish only up to a safe point (saved files, a committable unit), write your HANDOFF (what you did, '
                'where you stopped, the next step, uncommitted files) and stop. Do not touch running GPU jobs. '
                'mai-resume will send a resume message after the reset.',
        'notice': '[mai-resume {now}] {engine} {window} limit at {pct}%{note} (resets {reset}). Do not stop; keep doing '
                  'the current work. A wrap-up message comes only just before the limit runs out.',
        'stale_note': ' (reading is old)',
        'resume': '[mai-resume {now}] The {engine} {window} limit has reset. Re-read your HANDOFF and the last '
                  'instruction and continue only work the limit stopped. If it was finished, start nothing and reply '
                  'with the single word idle.',
        'keepalive': '[mai-resume {now}] Cache keep-alive. If you are in the middle of work, carry on with it unchanged. '
                     'If not, reply with the single word idle and start nothing new.',
    },
}

HIT = re.compile(r"You['’]ve hit your (?P<what>.+?) limit\s*[·.]\s*resets\s+(?P<when>[^()\n]+?)\s*\((?P<tz>[^)\n]+)\)")
WHEN = re.compile(r'^(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),\s*)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)$', re.I)
MONTHS = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
FIXED_TZ = {'Asia/Seoul': 9, 'Asia/Tokyo': 9, 'UTC': 0, 'Etc/UTC': 0}   # used when the zoneinfo database is missing (Windows)
# the line Claude Code leaves when a turn ends: "* Brewed for 2s . done 오전 12:42" (Korean locale, seen 10/20) or "done 12:42 am"
DONE_KO = re.compile('·\\s*done\\s+(오전|오후)\\s*(\\d{1,2}):(\\d{2})')
DONE_EN = re.compile(r'·\s*done\s+(\d{1,2}):(\d{2})\s*(am|pm)', re.I)
CLAUDE_PLACEHOLDER = re.compile(r'^Try "[^"]*"$')
MENU_ROW = re.compile(r'^\d+\.\s')
# a message sent while the pane works waits above the spinner with "ctrl+enter to send now" (seen 10/27); lead also saw
# "Press up to edit queued messages" in the prompt row
QUEUED = re.compile(r'^\s*ctrl\+enter to send now\s*$|Press up to edit queued messages', re.M)
SPINNER = re.compile(r'…\s*\(\d+(?:m \d+)?s|esc to interrupt|Compacting', re.I)
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


def picked(handle, ids):
    """True if handle is one of ids, written whole or as its start with or without 'term_' (e.g. 2580fc05)."""
    return any(i and (handle == i or handle.startswith(i) or handle.startswith('term_' + i)) for i in ids)


def read_targets(text):
    """The allow list file: one pane id per line (whole handle or its start), anything after # is a note."""
    out = []
    for line in (text or '').splitlines():
        tok = line.split('#', 1)[0].split()
        if tok:
            out.append(tok[0])
    return out


def discover(terminals, only=None, exclude=None):
    """Live agent sessions from `orca terminal list --json`: claude and codex panes that are connected and writable.
    `only` (pane ids, see picked) limits the guard to those panes; an empty list means no pane at all (owner 10/20:
    old sessions the owner no longer uses must get nothing). None means every pane. `exclude` leaves panes out."""
    found = []
    for t in terminals or []:
        if not isinstance(t, dict):
            continue
        eng = t.get('agentIdentity')
        h = t.get('handle') or ''
        if only is not None and not picked(h, only) or exclude and picked(h, exclude):
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


def _done_at(text, now, local_tz):
    """Time of the last 'done hh:mm' line on the screen (local wall clock), as an aware datetime, or None."""
    last = None
    for m in DONE_KO.finditer(text):
        h, mi = int(m.group(2)) % 12 + (12 if m.group(1) == '오후' else 0), int(m.group(3))
        last = (h, mi)
    for m in DONE_EN.finditer(text):
        h, mi = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0), int(m.group(2))
        last = (h, mi)
    if last is None:
        return None
    loc = now.astimezone(local_tz) if local_tz else now.astimezone()
    t = loc.replace(hour=last[0], minute=last[1], second=0, microsecond=0)
    if t > loc + dt.timedelta(minutes=1):
        t -= dt.timedelta(days=1)
    return t


def holds(mid, engine, ss):
    """Does this screen state hold back message `mid`? Used by tick and again by the runner right before typing.
    Only real typing holds (see screen_state: hidden typed text or a choice menu, never text Orca shows after the
    Claude marker), for keep, warn and resume alike (owner 10/26 20:3x). A keep-alive is also held by a working pane."""
    if mid.startswith('keep|') and ss['busy']:
        return True
    return ss['typing']


def prompt_key(engine, screen):
    """(last prompt row text, its trailing spaces): two reads of a pane whose keys differ mean someone is typing now."""
    trailing = None
    if isinstance(screen, dict):
        trailing = screen.get('prompt_trailing')
        screen = screen.get('text')
    mark = '❯' if engine == 'claude' else '›'
    rows = [ln.replace(' ', ' ').strip() for ln in (screen or '').splitlines()]
    rows = [ln for ln in rows if ln.startswith(mark)]
    return (rows[-1] if rows else None, trailing)


def screen_state(engine, screen, now, local_tz=None):
    """{'hit': (what, reset) or None, 'typing': bool, 'busy': bool} read from the visible screen of a pane.
    `screen` is the screen text, or a dict {'text': ..., 'prompt_trailing': n} where n is the trailing-space count of the
    last prompt row. Orca's screen read does not show text typed but not yet submitted into a Claude prompt (measured
    10/20, and again 10/27 on Claude Code 2.1.310 with Orca 1.4.241: the row stays a bare marker), but that row's
    trailing space goes from 1 to 0 while text is there, so a bare marker with 0 trailing spaces counts as typing.
    Text Orca does show after the Claude marker is never typing: a gray suggestion, the empty-prompt hint, or the queue
    hint. Two bare-marker-0 cases are not typing either (real screens in tests/screens): the Try hint row of a new pane
    (10/27 a fresh pane read as typing forever, send rc 4) and the prompt under a queued message, which Orca shows as
    the same bare marker with 0 whether or not text is typed (sending there queues one more message, as the owner's own
    Enter would). A numbered choice row ('❯ 1. Yes', a permission menu) is held as typing."""
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
    tail = '\n'.join(lines[-14:])
    menu = shown = queued = False
    if engine == 'claude':
        hint = bool(CLAUDE_PLACEHOLDER.match(typed))  # an empty prompt shows a hint: Try "fix typecheck errors"
        queued = bool(QUEUED.search(tail))
        # The input row sits in a box: the row right under it is a ──── rule (every real capture in tests/screens).
        # A marker row outside that box is a choice cursor ('❯ 1. Yes', '❯ No, exit' in the folder trust dialog).
        rows = [ln.strip() for ln in lines]
        last = max((i for i, r in enumerate(rows) if r.startswith(mark)), default=None)
        boxed = last is not None and last + 1 < len(rows) and rows[last + 1].startswith('─')
        menu = bool(typed) and not hint and (bool(MENU_ROW.match(typed)) or not boxed)
        shown = bool(typed) and not hint and not menu  # text Orca shows in the input row: suggestion or queue hint
        hidden = bool(prompts) and not typed and trailing == 0 and not queued
        typed = '(choice menu)' if menu else '(hidden typed text)' if hidden else ''
    return {'hit': hit, 'typing': bool(typed), 'busy': bool(SPINNER.search(tail)), 'done_at': _done_at(tail, now, local_tz),
            'shown_text': shown, 'menu': menu, 'queued': queued}


def _fmt(cfg, kind, engine, window, pct, reset, now_local, note=''):
    t = cfg['messages'][kind].format(now=now_local.strftime('%m/%d %H:%M'), engine=engine, window=window, note=note,
                                     pct=int(round(pct)) if pct is not None else '?',
                                     reset=reset.astimezone(now_local.tzinfo).strftime('%m/%d %H:%M'))
    return one_line(t)


def tick(state, now, limits, terminals, screens, cfg, local_tz=None):
    """One decision round. Returns (state, sends, log_lines). sends = [(handle, text, message_id)].
    `screens` maps handle -> screen text (missing = could not read; such a pane is not typed into)."""
    cfg = merged(cfg)
    st = {'sent': dict(state.get('sent') or {}), 'windows': dict(state.get('windows') or {}),
          'pending': list(state.get('pending') or []), 'keepalive': dict(state.get('keepalive') or {})}
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
            key = '%s|%s|%s' % (engine, window, _iso(cur['reset']))
            stop_pct = cfg['warn_pct'].get(window, 95)
            notice_pct = (cfg.get('notice_pct') or {}).get(window)
            if cur['stale']:   # an old reading never stops anyone; at most the notice
                notice_pct = min(p for p in (notice_pct, cfg['stale_warn_pct']) if p is not None)
            if cur['stale'] or cur['pct'] < stop_pct:
                # a window already stopped keeps its stop: a later stale reading must not tell those panes to carry on
                if key in st['windows'] or notice_pct is None or cur['pct'] < notice_pct:
                    continue
                note = cfg['messages'].get('stale_note', '') if cur['stale'] else ''
                text = _fmt(cfg, 'notice', engine, window, cur['pct'], cur['reset'], now_local, note)
                for s in group:
                    mid = 'notice|%s|%s' % (s['handle'], key)
                    if mid not in st['sent'] and not any(p['id'] == mid for p in st['pending']):
                        logs.append('NOTICE %s %s pct=%s stale=%s' % (s['handle'], key, cur['pct'], cur['stale']))
                    queue(s['handle'], text, mid)
                continue
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
        engine, window, reset = key.split('|', 2)
        text = _fmt(cfg, 'resume', engine, window.replace('hit:', ''), None, _parse_iso(w['resume_at']), now_local)
        for h in w['handles']:
            if h in live:   # one resume per pane per reset, even if both the limits file and the screen booked it
                queue(h, text, 'resume|%s|%s|%s' % (h, engine, reset))
        w['resumed'] = True
        logs.append('RESUME %s to %d' % (key, len([h for h in w['handles'] if h in live])))

    # 3b. cache keep-alive (owner 10/20): an idle Claude session is nudged once per keepalive_s so its prompt cache lives.
    #     Not while a limit window of the engine is held (warned, before its resume) or the pane shows the limit line:
    #     requests are refused then, so a nudge keeps no cache and only spends the limit. A working pane keeps its own
    #     cache, so its clock just restarts. A first-seen pane only starts its clock. Unknown state: nothing is sent.
    period = cfg.get('keepalive_s') or 0
    held = {k.split('|', 1)[0] for k, w in st['windows'].items() if not w['resumed'] and now < _parse_iso(w['resume_at'])}
    ka = st['keepalive']
    for s in sessions:
        if not period or s['engine'] != 'claude':
            continue
        h = s['handle']
        if h not in ka:
            ka[h] = _iso(now)
            continue
        ss = screen_state('claude', screens.get(h), now, local_tz) if h in screens else None
        if ss is None:
            continue
        clock = _parse_iso(ka[h])
        if ss['busy']:
            ka[h] = _iso(now)
            continue
        if ss['done_at'] and ss['done_at'] > clock:
            clock = ss['done_at']
            ka[h] = _iso(clock)
        if (now - clock).total_seconds() < period or 'claude' in held or ss['hit'] or not ss['done_at']:
            continue
        queue(h, _fmt(cfg, 'keepalive', 'claude', '', None, now, now_local), 'keep|%s|%s' % (h, ka[h]))
        ka[h] = _iso(now)
        logs.append('KEEPALIVE %s' % h)

    # 4. deliver what is pending, never into a prompt that holds text
    sends, keep = [], []
    for p in st['pending']:
        if p['handle'] not in live:
            logs.append('DROP %s (pane gone)' % p['id'])
            continue
        age = (now - _parse_iso(p['since'])).total_seconds()
        eng = next(s['engine'] for s in sessions if s['handle'] == p['handle'])
        scr = screens.get(p['handle'])
        # A keep-alive is true only for the idle moment it was decided in. If it waited (someone typing) and the pane is
        # now working, or finished a newer turn, it would land in the middle of work and read as an order to stop
        # (10/26: decided 15:46, delivered 16:13 into a working reviewer pane, which replied idle and stopped). Drop it.
        ss = screen_state(eng, scr, now, local_tz) if scr is not None else None
        if p['id'].startswith('keep|') and ss is not None:
            # owner 10/26: keep-alive only for a pane that is resting after a finished turn, never into work in progress,
            # and a nudge that waited longer than keepalive_stale_s is dropped so the next round decides afresh
            why = ('is working' if ss['busy'] else
                   'finished a newer turn' if ss['done_at'] and ss['done_at'] > _parse_iso(p['since']) else
                   'waited %d s' % age if age > cfg['keepalive_stale_s'] else None)
            if why:
                logs.append('DROP %s (keep-alive stale: pane %s since it was decided)' % (p['id'], why))
                st['sent'][p['id']] = _iso(now)
                if why.startswith('waited'):   # still resting: let the next round decide again instead of waiting a period
                    st['keepalive'][p['handle']] = _iso(now - dt.timedelta(seconds=cfg['keepalive_s']))
                continue
        # Text shown after a resting Claude marker is the gray suggestion, not typing (see holds). 10/26: site waited
        # 17 times behind one for its keep-alive, and the owner saw a warning marked held behind one too.
        typing = ss is None or holds(p['id'], eng, ss)
        if typing:
            if age > cfg['defer_give_up_s']:
                logs.append('DROP %s (prompt busy with typed text for %d s)' % (p['id'], age))
                st['sent'][p['id']] = _iso(now)   # given up for good: without this step 1 queued it again (10/20 12:27, 13:07)
            else:
                keep.append(p)
            continue
        sends.append((p['handle'], one_line(p['text']), p['id']))
        st['sent'][p['id']] = _iso(now)
        st['keepalive'][p['handle']] = _iso(now)          # any message delivered also renews that pane's cache
    st['pending'] = keep
    st['keepalive'] = {h: v for h, v in st['keepalive'].items() if h in live}

    # forget windows and sent ids older than 8 days so the state file stays small
    cutoff = now - dt.timedelta(days=8)
    st['windows'] = {k: v for k, v in st['windows'].items() if _parse_iso(v['resume_at']) > cutoff}
    st['sent'] = {k: v for k, v in st['sent'].items() if _parse_iso(v) > cutoff}
    st['heartbeat'] = _iso(now)
    return st, sends, logs


def is_gauge_pane(t):
    """A pane that already shows the codex gauge: titled Mods, or its preview holds the gauge's own row names."""
    pv = t.get('preview') or ''
    return 'mods' in (t.get('title') or '').lower() or ('5 hours' in pv and '7 days' in pv and 'turn ' in pv)


def need_companion(terminals, sessions, codex_ids, done, only=None):
    """Codex panes that should get a gauge pane now: [(handle, codex session id)]. A pane needs one when it is a live
    codex pane (and in `only`, the allow list), no other pane in its Orca tab is titled with Mods, its codex session id is
    known (codex_ids: handle -> id, from the gauge's ~/.mai/sessions files) and no gauge pane was opened for this
    incarnation yet (done: handle -> incarnationId). A gauge pane the owner closes is not opened again (owner 10/20: the
    gauge must come by itself, not keep coming back)."""
    live = {s['handle'] for s in sessions if s['engine'] == 'codex'}
    tabs = {}
    for t in terminals or []:
        if isinstance(t, dict) and t.get('tabId'):
            tabs.setdefault(t['tabId'], []).append(t)
    out = []
    for t in terminals or []:
        if not isinstance(t, dict) or t.get('handle') not in live:
            continue
        h = t['handle']
        if only is not None and not picked(h, only):
            continue
        if done.get(h) == t.get('incarnationId', ''):
            continue
        mates = [m for m in tabs.get(t.get('tabId'), []) if m.get('handle') != h]
        if any(is_gauge_pane(m) for m in mates):
            continue
        if codex_ids.get(h):
            out.append((h, codex_ids[h]))
    return out
