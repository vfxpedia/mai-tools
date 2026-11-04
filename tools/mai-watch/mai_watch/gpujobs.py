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
import json
import os
import sys
import re
import subprocess
import threading
import time

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
FAST_S = 1.0
SLOW_S = 10.0
IDLE_S = 30.0          # the worker stops when nobody asked for this long
FIRST_WAIT_S = 4.0     # the first reply after a start waits this long for the child's first reading
SCHEMA = 'mai-watch-gpu-jobs-v1'
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
    # every field read with .get, as the board itself does: it adds row kinds (a folded C-layer row has no queue id, 11/04), and one
    # missing field must not blank the whole tab
    for n, e in enumerate(d['entries'], 1):
        entries.append({'n': n, 'state': e.get('state', '-'), 'gpu': 'GPU%s' % e.get('gpu', '-'), 'priority': 'P%s' % e.get('priority', '-'),
                        'start': mod.clock(e.get('start'), now), 'end': mod.clock(e.get('end'), now),
                        'launcher': mod.launcher(e), 'title': e.get('title', '')})
        tag = '자동' if e.get('auto') else '대기열 %s' % e.get('id', '-')
        notes.append({'n': n, 'text': ' · '.join(x for x in (tag, e.get('owner'), e.get('condition'), e.get('source')) if x)})
    guards = [j for j in d['jobs'] if j['kind'] == 'guard']
    parked = [j for j in d['jobs'] if j['kind'] != 'guard' and not any(mod.on_gpu(j, i) for i in gpus)]
    return {'schema': 'mai-watch-gpu-jobs-v1', 'now': now, 'slow_read_at': slow.get('read_at'),
            'gpu_read_ok': bool(gpus), 'gpus': boxes, 'entries': entries, 'warnings': list(d['warnings']), 'notes': notes,
            'guards': ['%s %s' % (j['script'], j['pid']) for j in guards],
            'parked': ['%s %s %s (%s 시작)' % (j['kind'], j['script'], j['pid'], mod.clock(j['started'], now)) for j in parked]}


class GpuJobs:
    def __init__(self, path, clock=time.time, loader=load, background=False):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.clock, self.loader, self.background = clock, loader, background
        self.lock = threading.Lock()
        self.mod, self.slow, self.slow_at, self.doc, self.doc_at = None, None, 0.0, None, 0.0
        self.mtime = None
        self.asked_at, self.worker, self.proc, self.ready = 0.0, None, None, threading.Event()

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
        """With background=True (mai-watch live) the board is read in a child process and a reply never waits for a reading.

        Read inside mai-watch, the board's process list took 4 s and its evaluation files up to 10 s whenever the sampler's own process
        scan was running (measured 11/04; alone each takes 0.01 to 0.1 s), so one reply took 4 to 19 s. The child has its own interpreter
        and psutil; a worker thread here asks it for a fresh copy once a second while someone asked in the last IDLE_S seconds."""
        if not self.background:
            return self.refresh()
        self.asked_at = self.clock()
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._keep_fresh, name='gpu-jobs', daemon=True)
            self.worker.start()
        if self.doc is None:
            self.ready.wait(FIRST_WAIT_S)
        return self.doc if self.doc is not None else {'schema': SCHEMA, 'error': 'GPU 관리판을 아직 읽는 중', 'path': self.path}

    def _child(self):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen([sys.executable, '-m', 'mai_watch.gpujobs', self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         creationflags=NO_WINDOW, text=True, encoding='utf-8', bufsize=1)
        return self.proc

    def _keep_fresh(self):
        while self.clock() - self.asked_at < IDLE_S:
            try:
                proc = self._child()
                proc.stdin.write('\n'); proc.stdin.flush()
                line = proc.stdout.readline()        # blocking pipe read, so the rest of mai-watch keeps running meanwhile
                if not line:
                    raise OSError('the GPU board reader stopped')
                self.doc = json.loads(line)
            except (OSError, ValueError) as e:
                self.doc = {'schema': SCHEMA, 'error': '%s: %s' % (type(e).__name__, e), 'path': self.path}
                if self.proc is not None and self.proc.poll() is None:
                    self.proc.kill()
                self.proc = None
            self.ready.set()
            time.sleep(FAST_S)

    def refresh(self):
        with self.lock:
            now = self.clock()
            if self.doc is not None and now - self.doc_at < FAST_S:
                return self.doc
            try:
                # the board is still being changed (11/04): a new file is loaded again, so the tab never shows an old version's values
                mtime = os.path.getmtime(self.path) if os.path.exists(self.path) else None
                if self.mod is None or mtime != self.mtime:
                    self.mod, self.mtime, self.slow = self.loader(self.path), mtime, None
                if self.slow is None or now - self.slow_at >= SLOW_S:
                    self.slow, self.slow_at = self._run(self.mod.slow_data), now
                d = self._run(self.mod.board_data, slow=self.slow)
                self.doc = document(self.mod, d, self.slow)
            except Exception as e:      # the tab says what failed; mai-watch keeps serving the rest of the page
                self.mod = None if isinstance(e, (ImportError, OSError, SyntaxError)) else self.mod
                self.doc = {'schema': 'mai-watch-gpu-jobs-v1', 'error': '%s: %s' % (type(e).__name__, e), 'path': self.path}
            self.doc_at = now
            return self.doc


def child(path):
    """`python -m mai_watch.gpujobs PATH`: one line on stdin asks for a reading, one JSON line on stdout answers. Ends with stdin."""
    board = GpuJobs(path)
    for _ in sys.stdin:
        sys.stdout.write(json.dumps(board.refresh(), ensure_ascii=False, allow_nan=False, default=str) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    child(sys.argv[1])
