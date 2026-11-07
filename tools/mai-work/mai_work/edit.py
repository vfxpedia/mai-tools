"""The one way to change WORK.tsv: every command checks the move, updates the row and appends a line to WORK-events.tsv.

Commands: add · start · done · hold · resume · cancel · replace · change · lock · decide (and the read-only log · ask).
Rules the commands enforce (design 2 · 3 절):
- moves follow schema.TRANSITIONS (done from open records a start first); done needs evidence that opens
- cancel · replace · lock · decide and a later end_plan need a real decided_at (ISO time, not after now) and a decision line
- hold needs wait_for, replace needs an existing id, after needs existing ids
- `ts` is always the machine's clock; nobody types it
Writes go through a lock file and a temporary file renamed into place, retried when a reader holds the file (EX-41 T1).
"""
import datetime
import os
import time

from . import check as chk
from . import convert as conv
from . import schema


class EditError(ValueError):
    pass


EDITABLE = ('title', 'owner', 'priority', 'stage', 'start_plan', 'end_plan', 'after', 'evidence', 'source', 'wait_for')


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def events_path(path):
    return os.path.join(os.path.dirname(os.path.abspath(path)), 'WORK-events.tsv')


def real_time(value, now):
    t = chk.parse_ts(value)
    if t is None:
        raise EditError('decided_at %r is not a time (use ISO like 2026-11-06T17:19:44+09:00; a guess like 17:1x is refused)' % value)
    if t > now + 60:
        raise EditError('decided_at %s is in the future' % value)
    return value


def plan_value(value):
    if value in ('', '-') or value.startswith('iter:') and value[5:].isdigit() or chk.parse_at(value) is not None:
        return value
    raise EditError('%r is not at:YYYY-MM-DDTHH:MM, iter:N or -' % value)


class _Lock:
    def __init__(self, path):
        self.lock = os.path.abspath(path) + '.lock'

    def __enter__(self):
        for _ in range(50):
            try:
                os.close(os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock) > 60:     # a writer that died long ago
                        os.remove(self.lock)
                        continue
                except OSError:
                    pass
                time.sleep(0.2)
        raise EditError('the list is locked by another writer: %s' % self.lock)

    def __exit__(self, *exc):
        try:
            os.remove(self.lock)
        except OSError:
            pass


def _replace(tmp, path):
    for i in range(3):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 2:
                raise
            time.sleep(0.5)


def load(path):
    _, header, rows = conv.read_tsv(path)
    if header != schema.WORK_COLUMNS:
        raise EditError('%s is not a WORK.tsv (convert the old list first: python -m mai_work convert)' % path)
    ev = events_path(path)
    events = conv.read_tsv(ev)[2] if os.path.exists(ev) else []
    return rows, events


def save(path, rows, events):
    for p, cols, data in ((path, schema.WORK_COLUMNS, rows), (events_path(path), schema.EVENT_COLUMNS, events)):
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(conv.tsv_text(cols, data))
        _replace(tmp, p)


def apply(path, cmd, item, by, now=None, **kw):
    """Run one command; returns the new event lines. Nothing is written when a rule refuses."""
    now = time.time() if now is None else now
    ts = datetime.datetime.fromtimestamp(now).astimezone().isoformat(timespec='seconds')
    if not by:
        raise EditError('--by (who makes the change) is required')
    with _Lock(path):
        rows, events = load(path)
        by_id = {r['id']: r for r in rows}
        new = []

        def ev(event, field='', old='', to='', why='', decision='', decided_at='', decided_by=''):
            new.append({'ts': ts, 'decided_at': decided_at, 'decided_by': decided_by, 'id': item, 'event': event, 'field': field,
                        'from': old, 'to': to, 'why': why, 'decision': decision, 'by': by})

        def move(r, to, event, **extra):
            if to not in schema.TRANSITIONS[r['status']]:
                raise EditError('%s is %s; it cannot become %s' % (item, r['status'], to))
            ev(event, 'status', r['status'], to, **extra)
            r['status'] = to

        def need(name):
            v = (kw.get(name) or '').strip()
            if not v:
                raise EditError('%s needs --%s' % (cmd, name.replace('_', '-')))
            return v

        def decision_args():
            return {'why': need('why'), 'decision': need('decision'), 'decided_at': real_time(need('decided_at'), now),
                    'decided_by': kw.get('decided_by') or ''}

        if cmd == 'add':
            if item in by_id:
                raise EditError('%s already exists' % item)
            r = dict.fromkeys(schema.WORK_COLUMNS, '')
            r.update({'id': item, 'title': need('title'), 'owner': need('owner'), 'status': 'open',
                      'priority': need('priority'), 'end_plan': plan_value(need('end_plan')),
                      'start_plan': plan_value(kw.get('start_plan') or ''), 'stage': kw.get('stage') or '',
                      'after': kw.get('after') or '', 'evidence': kw.get('evidence') or '', 'source': kw.get('source') or ''})
            if r['priority'] not in chk.PRIORITY_ORDER:
                raise EditError('priority must be P0 to P3')
            for a in (x.strip() for x in r['after'].split(',') if x.strip()):
                if a not in by_id:
                    raise EditError('after %s: no such item' % a)
            rows.append(r)
            ev('add', 'status', '', 'open', why=kw.get('why') or '')
        else:
            if item not in by_id:
                raise EditError('%s is not in the list' % item)
            r = by_id[item]
            if cmd == 'start':
                move(r, 'doing', 'start')
                r['start_actual'] = ts
            elif cmd == 'done':
                if kw.get('evidence'):
                    r['evidence'] = kw['evidence']
                if not chk.evidence_present(r['evidence']):
                    raise EditError('done needs evidence that opens; %r does not' % r['evidence'])
                if r['status'] == 'open':
                    move(r, 'doing', 'start')
                    r['start_actual'] = ts
                move(r, 'done', 'done', why=kw.get('why') or '')
                r['end_actual'] = ts
            elif cmd == 'hold':
                r['wait_for'] = need('wait_for')
                move(r, 'hold', 'hold', why=kw.get('why') or '')
            elif cmd == 'resume':
                move(r, 'doing' if r['start_actual'] else 'open', 'resume', why=kw.get('why') or '')
            elif cmd == 'cancel':
                d = decision_args()
                move(r, 'cancelled', 'cancel', **d)
                r.update({'decision': d['decision'], 'decided_at': d['decided_at'], 'decided_by': d['decided_by']})
            elif cmd == 'replace':
                to = need('replaced_by')
                if to not in by_id or to == item:
                    raise EditError('replaced_by %s is not another item in the list' % to)
                d = decision_args()
                move(r, 'replaced', 'replace', **d)
                r.update({'replaced_by': to, 'decision': d['decision'], 'decided_at': d['decided_at'], 'decided_by': d['decided_by']})
            elif cmd == 'change':
                field, value = need('field'), kw.get('value') or ''
                if field not in EDITABLE:
                    raise EditError('change can edit %s; status has its own commands' % ', '.join(EDITABLE))
                if field in ('start_plan', 'end_plan'):
                    value = plan_value(value)
                extra = {'why': need('why')}
                a, b = chk.parse_at(r[field]), chk.parse_at(value)
                if field == 'end_plan' and (a is None or b is None or b > a) and r[field] not in ('', '-'):
                    extra = decision_args()          # a later (or no longer comparable) deadline is a decision
                if field == 'after':
                    for x in (s.strip() for s in value.split(',') if s.strip()):
                        if x not in by_id or x == item:
                            raise EditError('after %s: not another item in the list' % x)
                ev('change', field, r[field], value, **extra)
                r[field] = value
            elif cmd == 'lock':
                d = decision_args()
                topic = need('topic')
                other = next((x['id'] for x in rows if x['locked'] == topic and x['id'] != item), None)
                if other:
                    raise EditError('topic %s is already locked by %s' % (topic, other))
                ev('lock', 'locked', r['locked'], topic, **d)
                r.update({'locked': topic, 'decision': d['decision'], 'decided_at': d['decided_at'], 'decided_by': d['decided_by']})
            elif cmd == 'decide':
                d = decision_args()
                ev('decide', 'decision', r['decision'], d['decision'], **d)
                r.update({'decision': d['decision'], 'decided_at': d['decided_at'], 'decided_by': d['decided_by']})
            else:
                raise EditError('unknown command %s' % cmd)
        save(path, rows, events + new)
        return new


def log(path, item):
    rows, events = load(path)
    return [e for e in events if e['id'] == item]


def ask(path, topic):
    """Before raising a question to the owner: has this topic already been decided?"""
    rows, _ = load(path)
    return next((r for r in rows if r['locked'] == topic), None)
