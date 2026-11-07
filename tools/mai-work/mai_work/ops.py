"""The work list as rows for a project's operations check: (level, name, detail), level OK | WARN | FAIL.

A project check that used to read WORKLIST.tsv itself calls `ops_lines(path, now, it)` instead, so the operations check, the
mai-watch tab and `mai_work check` agree. On top of the findings it keeps the operations view the old check had: a WARN when an
open deadline is within 30 minutes or 50 updates, and an OK line with the next three open items.
"""
from . import check as chk

PRIORITY_ORDER = chk.PRIORITY_ORDER


def ops_lines(path, now, it=None):
    d = chk.document(str(path), now=now, it=it)
    if 'error' in d:
        return [('FAIL', 'W worklist', 'worklist unreadable: %s' % d['error'])]
    out = []
    for f in d['findings']:
        out.append(('FAIL' if f['level'] == 'FAIL' else 'WARN', 'W %s' % f['id'], '%s %s %s %s · %s'
                    % (f['rule'], f['priority'], f['owner'], f['msg'], _title(d, f['id'])[:60])))
    flagged = {f['id'] for f in d['findings']}
    todo = [i for i in d['items'] if i['status'] in ('open', 'doing')]
    for i in todo:
        if i['due'] == 'soon' and i['id'] not in flagged:
            out.append(('WARN', 'W %s' % i['id'], 'soon %s %s due %s · %s' % (i['priority'], i['owner'], i['end_plan'], i['title'][:60])))
    todo.sort(key=lambda i: (PRIORITY_ORDER.get(i['priority'], 9), i['end_plan']))
    top = ' | '.join('%s %s %s' % (i['id'], i['priority'], i['title'][:40]) for i in todo[:3])
    out.append(('OK', 'W next', '%d open · next: %s' % (len(todo), top)))
    return out


def _title(d, item_id):
    for i in d['items']:
        if i['id'] == item_id:
            return i['title']
    return ''
