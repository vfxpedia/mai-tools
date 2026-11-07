"""Optional "작업" tab (owner 11/06 · W42): the project's work list, named with `--worklist PATH`, served as work.json.

mai-watch keeps no rules of its own here: it calls mai-work's check (tools/mai-work in this repository), so the tab and
`python -m mai_work check` show the same findings. The list may be the new WORK.tsv or the eight-column WORKLIST.tsv still in use.
Read-only: nothing here edits the list or sends a message. A list that cannot be read is reported in the tab, never a crash.

The document is rebuilt at most every FAST_S seconds; that is enough to follow deadlines by the minute and cheap for 50 rows.
"""
import os
import sys
import threading
import time

SCHEMA = 'mai-work-check-v1'
FAST_S = 2.0
TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'mai-work')


def _checker():
    if TOOL not in sys.path:
        sys.path.insert(0, TOOL)
    from mai_work import check
    return check


class Worklist:
    def __init__(self, path, clock=time.time):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.clock = clock
        self.lock = threading.Lock()
        self.doc, self.doc_at = None, 0.0

    def document(self):
        with self.lock:
            now = self.clock()
            if self.doc is not None and now - self.doc_at < FAST_S:
                return self.doc
            try:
                self.doc = _checker().document(self.path, now=now)
            except Exception as e:          # the tab says what failed; mai-watch keeps serving the rest of the page
                self.doc = {'schema': SCHEMA, 'now': now, 'error': '%s: %s' % (type(e).__name__, e), 'path': self.path}
            self.doc_at = now
            return self.doc
