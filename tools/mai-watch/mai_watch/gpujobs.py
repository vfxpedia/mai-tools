"""Optional "GPU jobs" tab (owner 11/03): a board module that lives in a project repo, named with `--gpu-jobs PATH`, served as gpu_jobs.json.

mai-watch does not copy the board's logic. It loads that file and calls its own functions (`slow_data`, `board_data`, `gpu_box`, `clock`,
`launcher`, `on_gpu`), so the web tab and the terminal board show the same values. Only the text frame of each GPU box is taken apart for
the web: the border is dropped and a `[███░░]` bar becomes a fraction for a real meter.

Timing matches the terminal board: the GPU reading at most once a second, process command lines and files every 10 s. Work happens only
while someone has the tab open; every reply is cached for a second so several viewers cost one reading.

The board's nvidia-smi call does not pass CREATE_NO_WINDOW. mai-watch runs under pythonw, where that opens a console window every second,
so the calls run with that flag added when the caller did not set one (mai-os os/tool-hazards.md). The board's code is not changed.

A file that is missing or fails to load is reported in the tab and retried on the next request, never a crash of mai-watch.
"""
import importlib.util
import os
import re
import subprocess
import threading
import time

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
FAST_S = 1.0
SLOW_S = 10.0
NEEDED = ('slow_data', 'board_data', 'gpu_box', 'clock', 'launcher', 'on_gpu', 'Paint')
BOX_WIDTH = 160          # wide enough that the board's own fit() never cuts a line with …
BAR = re.compile(r'^\[([█░]+)\]\s*(.*)$')


def load(path):
    spec = importlib.util.spec_from_file_location('mai_watch_gpu_board', path)
    if spec is None or spec.loader is None:
        raise ImportError('cannot load %s' % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    missing = [n for n in NEEDED if not hasattr(mod, n)]
    if missing:
        raise ImportError('%s has no %s' % (path, ', '.join(missing)))
    return mod


def box_lines(lines):
    """The board's text box -> title and body lines; a bar line becomes {'bar': fraction, 'text': tail}."""
    title = lines[0].strip().lstrip('┌─ ').rstrip('─┐ ').strip()
    body = []
    for raw in lines[1:-1]:
        line = raw.strip()
        if line.startswith('│'):
            line = line[1:]
        if line.endswith('│'):
            line = line[:-1]
        line = line.strip()
        if not line:
            continue
        m = BAR.match(line)
        if m:
            cells = m.group(1)
            body.append({'bar': cells.count('█') / len(cells), 'text': m.group(2)})
        else:
            body.append({'text': line})
    return {'title': title, 'lines': body}


def document(mod, d, slow):
    now = d['now']
    gpus = sorted(d['smi']['gpus'])
    boxes = [box_lines(mod.gpu_box(d, i, BOX_WIDTH, mod.Paint(False))) for i in gpus]
    entries, notes = [], []
    for n, e in enumerate(d['entries'], 1):
        entries.append({'n': n, 'state': e['state'], 'gpu': 'GPU%s' % e['gpu'], 'priority': 'P%s' % e['priority'],
                        'start': mod.clock(e.get('start'), now), 'end': mod.clock(e.get('end'), now),
                        'launcher': mod.launcher(e), 'title': e['title']})
        tag = '자동' if e['auto'] else '대기열 %s' % e['id']
        notes.append({'n': n, 'text': ' · '.join(x for x in (tag, e.get('owner'), e.get('condition'), e.get('source')) if x)})
    guards = [j for j in d['jobs'] if j['kind'] == 'guard']
    parked = [j for j in d['jobs'] if j['kind'] != 'guard' and not any(mod.on_gpu(j, i) for i in gpus)]
    return {'schema': 'mai-watch-gpu-jobs-v1', 'now': now, 'slow_read_at': slow.get('read_at'),
            'gpu_read_ok': bool(gpus), 'gpus': boxes, 'entries': entries, 'warnings': list(d['warnings']), 'notes': notes,
            'guards': ['%s %s' % (j['script'], j['pid']) for j in guards],
            'parked': ['%s %s %s (%s 시작)' % (j['kind'], j['script'], j['pid'], mod.clock(j['started'], now)) for j in parked]}


class GpuJobs:
    def __init__(self, path, clock=time.time, loader=load):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.clock, self.loader = clock, loader
        self.lock = threading.Lock()
        self.mod, self.slow, self.slow_at, self.doc, self.doc_at = None, None, 0.0, None, 0.0

    def _run(self, fn, *args, **kw):
        run = subprocess.run

        def quiet(*a, **k):
            if NO_WINDOW and 'creationflags' not in k:
                k['creationflags'] = NO_WINDOW
            return run(*a, **k)
        subprocess.run = quiet
        try:
            return fn(*args, **kw)
        finally:
            subprocess.run = run

    def document(self):
        with self.lock:
            now = self.clock()
            if self.doc is not None and now - self.doc_at < FAST_S:
                return self.doc
            try:
                if self.mod is None:
                    self.mod = self.loader(self.path)
                if self.slow is None or now - self.slow_at >= SLOW_S:
                    self.slow, self.slow_at = self._run(self.mod.slow_data), now
                d = self._run(self.mod.board_data, slow=self.slow)
                self.doc = document(self.mod, d, self.slow)
            except Exception as e:      # the tab says what failed; mai-watch keeps serving the rest of the page
                self.mod = None if isinstance(e, (ImportError, OSError, SyntaxError)) else self.mod
                self.doc = {'schema': 'mai-watch-gpu-jobs-v1', 'error': '%s: %s' % (type(e).__name__, e), 'path': self.path}
            self.doc_at = now
            return self.doc
