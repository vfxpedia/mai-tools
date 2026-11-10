"""Optional "받은편지함" tab (owner 11/10): Orca orchestration messages between agent sessions, served as inbox.json.

Who wrote to whom and what, newest first. Sender and receiver are shown by session name, not by terminal handle: names come from
mai-resume's targets.txt ('2e7579c1  # super-lx (...)') and from Orca tab titles that are a single word. A message filed to the whole
run carries its addressee in the subject ('[lead-lx → super-lx] ...'); that name is used, else it reads as 'run 전체'.
Read-only: nothing here sends, marks read or edits. If Orca cannot be reached the tab says so; the page keeps serving.

The same document drives `mai-watch inbox` (a terminal view for an Orca tab).
"""
import datetime
import json
import os
import re
import subprocess
import threading
import time

SCHEMA = 'mai-watch-inbox-v1'
FAST_S = 4.0
NAMES_S = 60.0
KEEP = 300
BODY = 4000
ARROW = re.compile(r'(?:→|->)\s*([A-Za-z][\w-]*)')
TARGETS = os.path.expanduser('~/.mai/resume/targets.txt')


def default_orca():
    return os.environ.get('ORCA_CLI_COMMAND') or '/usr/bin/orca-ide'


def run_orca(orca, *args):
    out = subprocess.run([orca, *args, '--json'], capture_output=True, text=True, timeout=15).stdout
    d = json.loads(out)
    if not d.get('ok'):
        raise RuntimeError('orca %s %s refused' % args[:2])
    return d['result']


def names_from(terminals, targets_text):
    """handle -> session name."""
    prefix = {t['handle'][5:13]: t['handle'] for t in terminals if str(t.get('handle', '')).startswith('term_')}
    out = {}
    for line in targets_text.splitlines():
        m = re.match(r'\s*([0-9a-f]{8})\s+#\s*([A-Za-z][\w-]*)', line)
        if m and m.group(1) in prefix:
            out[prefix[m.group(1)]] = m.group(2)
    for t in terminals:
        title = (t.get('title') or '').strip()
        if t.get('handle') not in out and re.fullmatch(r'[A-Za-z][\w-]*', title):
            out[t['handle']] = title
    return out


def epoch(text):
    try:
        return datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def who(handle, names):
    if not handle:
        return '?'
    if handle in names:
        return names[handle]
    if handle.startswith('run:'):
        return 'run 전체'
    return handle[:13]


def shape(msgs, names, now):
    rows = []
    for m in sorted(msgs, key=lambda x: x.get('sequence') or 0, reverse=True)[:KEEP]:
        subject = re.sub(r'\s+', ' ', m.get('subject') or '').strip()
        to = m.get('to_handle') or ''
        to_name = who(to, names)
        if to.startswith('run:'):
            a = ARROW.search(subject)
            to_name = a.group(1) if a else 'run 전체'
        body = (m.get('body') or '').strip()
        rows.append({'seq': m.get('sequence'), 'at': epoch(m.get('created_at')), 'type': m.get('type') or '',
                     'from': who(m.get('from_handle'), names), 'to': to_name, 'to_run': to.startswith('run:'),
                     'subject': subject, 'body': body[:BODY], 'cut': len(body) > BODY})
    people = sorted({r['from'] for r in rows} | {r['to'] for r in rows})
    return {'schema': SCHEMA, 'now': now, 'messages': rows, 'people': people,
            'run': next((m.get('run_id') for m in msgs if m.get('run_id')), None)}


class Inbox:
    def __init__(self, orca=None, clock=time.time, runner=run_orca, targets=TARGETS):
        self.orca = orca or default_orca()
        self.clock, self.runner, self.targets = clock, runner, targets
        self.lock = threading.Lock()
        self.doc, self.doc_at, self.names, self.names_at = None, 0.0, {}, -1e9

    def _names(self, now):
        if now - self.names_at >= NAMES_S:
            r = self.runner(self.orca, 'terminal', 'list')
            terms = r.get('terminals', r) if isinstance(r, dict) else r
            text = open(self.targets, encoding='utf-8').read() if os.path.exists(self.targets) else ''
            self.names, self.names_at = names_from(terms, text), now
        return self.names

    def document(self):
        with self.lock:
            now = self.clock()
            if self.doc is not None and now - self.doc_at < FAST_S:
                return self.doc
            try:
                r = self.runner(self.orca, 'orchestration', 'inbox', '--full', '--limit', str(KEEP))   # Orca's default is the last 20
                msgs = r.get('messages', r) if isinstance(r, dict) else r
                self.doc = shape(msgs, self._names(now), now)
            except Exception as e:          # the tab says what failed; the rest of the page keeps serving
                self.doc = {'schema': SCHEMA, 'now': now, 'error': '%s: %s' % (type(e).__name__, e), 'messages': [], 'people': []}
            self.doc_at = now
            return self.doc


def text_view(doc, width=100, limit=40):
    """Plain text for a terminal tab: one block per message, newest at the bottom so the eye ends on it."""
    if doc.get('error'):
        return '받은편지함을 못 읽음: ' + doc['error']
    out = []
    for r in reversed(doc['messages'][:limit]):
        t = time.strftime('%m-%d %H:%M', time.localtime(r['at'])) if r['at'] else '--'
        out.append('\033[2m#%s  %s  %s\033[0m  \033[1m%s → %s\033[0m' % (r['seq'], t, r['type'], r['from'], r['to']))
        out.append('  ' + r['subject'][:width * 2])
        first = [ln for ln in r['body'].splitlines() if ln.strip()][:2]
        for ln in first:
            out.append('  \033[2m' + ln[:width] + '\033[0m')
        out.append('')
    stamp = time.strftime('%H:%M:%S', time.localtime(doc['now']))
    out.append('\033[2m최근 %d 통 · %s 갱신 · 전문: orca-ide orchestration inbox --full · 읽기만\033[0m' % (min(limit, len(doc['messages'])), stamp))
    return '\n'.join(out)
