"""Notifications from the judgment list (DESIGN.md section 9g, stage 4 of direction B on vfxpedia/mai-os#43).

mai-watch never holds a messaging token. It hands each message to a command the owner chose: the text is written to a file (when
notify_file is set) and also given on standard input, then the command runs. On the reference machine that command is the existing
Telegram sender, which reads its own outbox file and its own credentials.

What is sent, decided by a pure function (Notifier.update) so every rule has a known-answer test:
- a finding at or above the chosen level is announced once it has been present for hold_s (a one-sample blip is not news)
- a finding that rises from warn to bad is announced again
- a finding that has been gone for hold_s is announced as cleared
- changes found in the same check go out as one message; nothing is repeated while a finding just stays
A finding is identified by kind and subject, so a changing number inside the same finding is not a new finding.
"""
import os
import socket
import subprocess
import time

LEVELS = {'info': 2, 'warn': 1, 'bad': 0}
LABEL = {'bad': 'ACT NOW', 'warn': 'LOOK SOON', 'info': 'NOTE'}


def key(f):
    return '%s|%s' % (f.get('kind'), f.get('subject'))


class Notifier:
    def __init__(self, level='warn', hold_s=60):
        if level not in LEVELS:
            raise ValueError('notify level must be one of bad, warn, info')
        self.level = level
        self.hold_s = float(hold_s)
        self.seen = {}        # key -> {'first': t, 'last': t, 'level': lvl, 'text': text}
        self.announced = {}   # key -> level announced
        self.gone = {}        # key -> time it was last missing from an announced state

    def update(self, findings, now):
        """Feed the current findings at time now. Returns (new, raised, cleared) lists of findings to announce."""
        current = {}
        for f in findings:
            if LEVELS.get(f.get('level'), 9) <= LEVELS[self.level]:
                current[key(f)] = f
        new, raised, cleared = [], [], []
        for k, f in current.items():
            s = self.seen.get(k)
            if s is None:
                s = self.seen[k] = {'first': now, 'level': f['level'], 'text': f['text']}
            s.update(last=now, level=f['level'], text=f['text'])
            self.gone.pop(k, None)
            if now - s['first'] < self.hold_s:
                continue
            was = self.announced.get(k)
            if was is None:
                new.append(f)
                self.announced[k] = f['level']
            elif LEVELS[f['level']] < LEVELS[was]:
                raised.append(f)
                self.announced[k] = f['level']
            elif LEVELS[f['level']] > LEVELS[was]:
                self.announced[k] = f['level']          # eased from bad to warn: remembered quietly, cleared when it goes
        for k in list(self.seen):
            if k in current:
                continue
            if k not in self.announced:
                del self.seen[k]                       # gone before it was ever announced: a blip, forget it
                continue
            since = self.gone.setdefault(k, now)
            if now - since >= self.hold_s:
                cleared.append({'level': self.announced[k], 'kind': k.split('|', 1)[0], 'subject': k.split('|', 1)[1], 'text': self.seen[k]['text']})
                del self.seen[k], self.announced[k], self.gone[k]
        return new, raised, cleared


def message(new, raised, cleared, host=None):
    host = host or socket.gethostname()
    parts = []
    if new:
        parts.append('%d new' % len(new))
    if raised:
        parts.append('%d worse' % len(raised))
    if cleared:
        parts.append('%d cleared' % len(cleared))
    lines = ['mai-watch %s: %s' % (host, ', '.join(parts))]
    for f in sorted(new + raised, key=lambda f: LEVELS[f['level']]):
        lines.append('%s  %s' % (LABEL[f['level']], f['text']))
    for f in cleared:
        lines.append('cleared  %s' % f['text'])
    return '\n'.join(lines) + '\n'


def send(cmd, text, notify_file=None, timeout=30, run=subprocess.run):
    """Writes text to notify_file (when given), runs cmd with text on standard input. Returns (ok, detail)."""
    try:
        if notify_file:
            with open(notify_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
        p = run(list(cmd), input=text, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, '%s: %s' % (type(e).__name__, e)
    out = ((p.stdout or '') + (p.stderr or '')).strip().splitlines()
    return p.returncode == 0, 'exit %d%s' % (p.returncode, (': ' + out[-1][:200]) if out else '')


def split_cmd(s):
    """A command line as a list without a shell. Quotes group words; backslashes are kept (Windows paths)."""
    out, cur, quote = [], '', None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in '"\'':
            quote = ch
        elif ch.isspace():
            if cur:
                out.append(cur)
                cur = ''
        else:
            cur += ch
    if quote:
        raise ValueError('unclosed quote in notify command')
    if cur:
        out.append(cur)
    return out


def loop(sampler, notifier, cmd, stop, notify_file=None, every_s=30, clock=time.time, sender=send, log=None):
    """Checks the judgment list every every_s seconds and sends what Notifier.update says is news. Records the last result on the
    sampler (status.json shows it), so a sender that keeps failing is visible instead of silent."""
    while not stop.is_set():
        try:
            new, raised, cleared = notifier.update(sampler.status()['judgments'], clock())
            if new or raised or cleared:
                ok, detail = sender(cmd, message(new, raised, cleared), notify_file)
                sampler.notify_state = {'last_at': sampler.now_iso(), 'ok': ok, 'detail': detail,
                                        'sent': len(new) + len(raised) + len(cleared)}
                if log and not ok:
                    log('notify command failed: %s' % detail)
        except Exception as e:                       # a broken sender must not stop the live view
            sampler.notify_state = {'last_at': sampler.now_iso(), 'ok': False, 'detail': 'notify loop: %s' % type(e).__name__, 'sent': 0}
        stop.wait(every_s)
