"""Notifications from the judgment list (DESIGN.md section 9g, stage 4 of direction B on vfxpedia/mai-os#43).

mai-watch never holds a messaging token. It hands each message to a command the owner chose: the text goes to the command's standard
input as UTF-8 (and into notify_file first when set), then the command runs. On the reference machine that command is the existing
Telegram sender, which reads its own outbox file and its own credentials.

What is announced is decided by Notifier, kept apart from whether it was delivered (review R13):
- update() looks at the current findings and proposes events: a finding at or above the level that has been observed continuously
  for hold_s (new), one that rose from warn to bad (worse), and one that has been observed absent for hold_s (cleared)
- commit() records events as delivered. Nothing is marked announced or cleared until the command succeeded, so a failed send is
  proposed again at the next check, together with anything newer, and one success never hides an earlier failure
- a finding whose source cannot be read right now (the GPU source broke, a folder not checked yet, the usage file missing) is not
  "absent": its clear timer stops, because not seeing a problem is not seeing it gone (review R14)
- time only counts while observed: a gap between checks longer than max_gap_s restarts the hold and the clear timer (review R15)
A finding is identified by kind and subject, so a changing number inside the same finding is not a new finding.
"""
import math
import os
import socket
import subprocess
import time

LEVELS = {'info': 2, 'warn': 1, 'bad': 0}
LABEL = {'bad': 'ACT NOW', 'warn': 'LOOK SOON', 'info': 'NOTE'}

# which source each kind of finding comes from, as named in the status document's "blind" list (judge.blind)
SOURCE = {'gpu_clock_limited': 'gpu', 'gpu_hot': 'gpu', 'gpu_vram_idle': 'gpu', 'slow_link': 'network', 'ram_high': 'host',
          'disk_space': 'path', 'path_unreachable': 'path', 'plan_limit': 'usage', 'usage_source': 'usage', 'source_problem': 'sampler'}


def key(f):
    return '%s|%s' % (f.get('kind'), f.get('subject'))


def is_blind(f, blind):
    src = SOURCE.get(f.get('kind'), 'unknown')
    return src in blind or ('%s:%s' % (src, f.get('subject'))) in blind


def _check_seconds(name, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise ValueError('%s must be a finite number of seconds, 0 or more (got %r)' % (name, v))
    return float(v)


class Notifier:
    def __init__(self, level='warn', hold_s=60, max_gap_s=90):
        if level not in LEVELS:
            raise ValueError('notify level must be one of bad, warn, info')
        self.level = level
        self.hold_s = _check_seconds('notify hold', hold_s)          # review R17: negative, NaN and infinity are refused
        self.max_gap_s = _check_seconds('notify gap', max_gap_s)
        self.seen = {}          # key -> {'first': t, 'last': t, 'level': lvl, 'finding': f}  (observed present)
        self.announced = {}     # key -> level delivered
        self.gone = {}          # key -> time it was first observed absent, for announced keys
        self.last_update = None

    def update(self, findings, now, blind=()):
        """Current findings at time now (monotonic seconds), and the sources that could not be read. Returns the events to send:
        a list of {'event': new|worse|cleared, 'key': k, 'finding': f}. Does not mark anything delivered."""
        gap = self.last_update is not None and now - self.last_update > self.max_gap_s
        self.last_update = now
        current = {}
        for f in findings:
            if LEVELS.get(f.get('level'), 9) <= LEVELS[self.level]:
                current[key(f)] = f
        events = []
        for k, f in current.items():
            s = self.seen.get(k)
            if s is None or gap:
                s = self.seen[k] = {'first': now}
            s.update(last=now, level=f['level'], finding=f)
            self.gone.pop(k, None)
            if now - s['first'] < self.hold_s:
                continue
            was = self.announced.get(k)
            if was is None:
                events.append({'event': 'new', 'key': k, 'finding': f})
            elif LEVELS[f['level']] < LEVELS[was]:
                events.append({'event': 'worse', 'key': k, 'finding': f})
            elif LEVELS[f['level']] > LEVELS[was]:
                self.announced[k] = f['level']            # eased from bad to warn: no message; cleared when it goes
        for k in list(self.seen):
            if k in current:
                continue
            f = self.seen[k]['finding']
            if is_blind(f, blind):
                self.gone.pop(k, None)                    # cannot see it: neither present nor gone, the timer waits
                continue
            if k not in self.announced:
                del self.seen[k]                          # gone before it was ever announced: a blip, forget it
                continue
            if k not in self.gone or gap:
                self.gone[k] = now
            if now - self.gone[k] >= self.hold_s:
                events.append({'event': 'cleared', 'key': k, 'finding': dict(f, level=self.announced[k])})
        return events

    def commit(self, events):
        """The command succeeded for these events: record them as delivered."""
        for e in events:
            k = e['key']
            if e['event'] in ('new', 'worse'):
                self.announced[k] = e['finding']['level']
            elif e['event'] == 'cleared':
                for d in (self.seen, self.announced, self.gone):
                    d.pop(k, None)


def message(events, host=None):
    host = host or socket.gethostname()
    by = {'new': [], 'worse': [], 'cleared': []}
    for e in events:
        by[e['event']].append(e['finding'])
    parts = ['%d %s' % (len(by[k]), k) for k in ('new', 'worse', 'cleared') if by[k]]
    lines = ['mai-watch %s: %s' % (host, ', '.join(parts))]
    for f in sorted(by['new'] + by['worse'], key=lambda f: LEVELS[f['level']]):
        lines.append('%s  %s' % (LABEL[f['level']], f['text']))
    for f in by['cleared']:
        lines.append('cleared  %s' % f['text'])
    return '\n'.join(lines) + '\n'


def send(cmd, text, notify_file=None, timeout=30, run=subprocess.run):
    """Writes text to notify_file (when given), runs cmd with text on standard input as UTF-8 bytes. Returns (ok, detail).
    A receiver that decodes stdin with the system code page (cp1252, cp949 on Windows) would break Korean text, so Python receivers
    are also told to use UTF-8 (PYTHONIOENCODING, PYTHONUTF8); any other receiver should read stdin as UTF-8 bytes. A command that
    times out counts as failed and is tried again later, so a slow sender may deliver the same message twice."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    try:
        if notify_file:
            with open(notify_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
        p = run(list(cmd), input=text, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return False, '%s: %s' % (type(e).__name__, e)
    out = ((p.stdout or '') + (p.stderr or '')).strip().splitlines()
    return p.returncode == 0, 'exit %d%s' % (p.returncode, (': ' + out[-1][:200]) if out else '')


def split_cmd(s):
    """A command line as a list without a shell. Quotes group words (an empty "" is an argument); backslashes are kept (Windows
    paths). Nothing is interpreted: ; & | > $( ) are plain characters."""
    out, cur, quote, quoted = [], '', None, False
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in '"\'':
            quote, quoted = ch, True
        elif ch.isspace():
            if cur or quoted:
                out.append(cur)
            cur, quoted = '', False
        else:
            cur += ch
    if quote:
        raise ValueError('unclosed quote in notify command')
    if cur or quoted:
        out.append(cur)
    return out


def loop(sampler, notifier, cmd, stop, notify_file=None, every_s=30, clock=time.monotonic, sender=send, log=None, max_backoff_s=1800):
    """Checks the judgment list every every_s seconds and sends what Notifier.update proposes. A failed send is kept and tried again
    after a growing wait (every_s doubled per failure, at most max_backoff_s). While the samples are stale nothing is judged.
    The state is recorded on the sampler and shown in status.json."""
    delivered, fails, next_try = 0, 0, 0.0
    state = sampler.notify_state = {'last_attempt_at': None, 'ok': None, 'detail': 'no message needed yet', 'delivered': 0,
                                    'pending': 0, 'failures_in_row': 0}
    while not stop.is_set():
        try:
            st = sampler.status()
            if not st.get('fresh', False):
                state.update(detail='samples are stale: nothing judged until they resume (%s)' % st.get('stale_reason'))
            else:
                events = notifier.update(st['judgments'], clock(), set(st.get('blind') or ()))
                state['pending'] = len(events)
                if events and clock() >= next_try:
                    ok, detail = sender(cmd, message(events), notify_file)
                    state.update(last_attempt_at=sampler.now_iso(), ok=ok, detail=detail)
                    if ok:
                        notifier.commit(events)
                        delivered += len(events)
                        fails, next_try = 0, 0.0
                        state['pending'] = 0
                    else:
                        fails += 1
                        next_try = clock() + min(every_s * 2 ** fails, max_backoff_s)
                        if log:
                            log('notify command failed (%d in a row, %d waiting): %s' % (fails, len(events), detail))
                    state.update(delivered=delivered, failures_in_row=fails)
        except Exception as e:                       # a broken sender or status must not stop the live view
            state.update(ok=False, detail='notify loop: %s' % type(e).__name__)
        stop.wait(every_s)
