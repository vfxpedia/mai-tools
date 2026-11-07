"""Write commands enforce the moves and decision times; notify sends once per item per 6 h and only with --send; ops_lines keep the
old operations view (soon WARN, next line) on top of the findings. Known answers throughout."""
import datetime
import json
import os
import tempfile
import unittest

from mai_work import check as chk
from mai_work import convert as conv
from mai_work import edit, notify, ops, schema

NOW = datetime.datetime(2026, 1, 10, 12, 0).timestamp()
REAL = '2026-01-10T11:00:00+09:00'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'WORK.tsv')
        conv.write_tsv(self.path, schema.WORK_COLUMNS, [])
        self.proof = os.path.join(self.tmp, 'proof.md')

    def do(self, cmd, item, **kw):
        return edit.apply(self.path, cmd, item, 'tester', now=NOW, **kw)

    def rows(self):
        return {r['id']: r for r in edit.load(self.path)[0]}


class EditTest(Base):
    def test_add_start_done_writes_rows_and_events(self):
        self.do('add', 'A', title='first', owner='bob', priority='P1', end_plan='at:2026-01-11T10:00')
        self.do('start', 'A')
        with self.assertRaises(edit.EditError):
            self.do('done', 'A', evidence=self.proof)               # evidence does not open yet: refused, nothing written
        self.assertEqual(self.rows()['A']['status'], 'doing')
        open(self.proof, 'w').close()
        self.do('done', 'A', evidence=self.proof)
        r = self.rows()['A']
        self.assertEqual((r['status'], r['evidence']), ('done', self.proof))
        self.assertTrue(r['start_actual'] and r['end_actual'])
        self.assertEqual([e['event'] for e in edit.log(self.path, 'A')], ['add', 'start', 'done'])
        with self.assertRaises(edit.EditError):
            self.do('start', 'A')                                   # done is final

    def test_done_from_open_records_the_start(self):
        open(self.proof, 'w').close()
        self.do('add', 'A', title='t', owner='bob', priority='P2', end_plan='-')
        self.do('done', 'A', evidence=self.proof)
        self.assertEqual([e['event'] for e in edit.log(self.path, 'A')], ['add', 'start', 'done'])

    def test_decisions_need_a_real_time(self):
        self.do('add', 'A', title='t', owner='bob', priority='P1', end_plan='at:2026-01-11T10:00')
        for guess in ('17:1x', '2026-01-10T17:5x', '2030-01-01T00:00:00+09:00'):
            with self.assertRaises(edit.EditError):
                self.do('cancel', 'A', why='w', decision='L1', decided_at=guess)
        self.do('cancel', 'A', why='owner changed plan', decision='decisions.tsv L9', decided_at=REAL, decided_by='owner')
        r = self.rows()['A']
        self.assertEqual((r['status'], r['decided_at'], r['decided_by']), ('cancelled', REAL, 'owner'))
        self.assertEqual(chk.check(list(self.rows().values()), edit.load(self.path)[1], NOW), [])

    def test_postponing_a_deadline_is_a_decision(self):
        self.do('add', 'A', title='t', owner='bob', priority='P1', end_plan='at:2026-01-11T10:00')
        with self.assertRaises(edit.EditError):
            self.do('change', 'A', field='end_plan', value='at:2026-01-12T10:00', why='late')       # no decision line / time
        self.do('change', 'A', field='end_plan', value='at:2026-01-11T08:00', why='earlier is fine')  # earlier needs only why
        self.do('change', 'A', field='end_plan', value='at:2026-01-12T10:00', why='GPU busy', decision='L12', decided_at=REAL)
        e = edit.log(self.path, 'A')[-1]
        self.assertEqual((e['field'], e['from'], e['to'], e['decided_at']), ('end_plan', 'at:2026-01-11T08:00', 'at:2026-01-12T10:00', REAL))
        with self.assertRaises(edit.EditError):
            self.do('change', 'A', field='status', value='done', why='x')                          # status has its own commands

    def test_hold_replace_lock_ask(self):
        for i in 'AB':
            self.do('add', i, title=i, owner='bob', priority='P1', end_plan='-')
        with self.assertRaises(edit.EditError):
            self.do('hold', 'A')
        self.do('hold', 'A', wait_for='팀장:disk-cleanup')
        self.do('resume', 'A')
        with self.assertRaises(edit.EditError):
            self.do('replace', 'A', replaced_by='Z', why='w', decision='L', decided_at=REAL)
        self.do('lock', 'B', topic='disk-cleanup', why='owner decided', decision='D164', decided_at=REAL)
        with self.assertRaises(edit.EditError):
            self.do('lock', 'A', topic='disk-cleanup', why='w', decision='L', decided_at=REAL)
        self.assertEqual(edit.ask(self.path, 'disk-cleanup')['id'], 'B')
        self.assertIsNone(edit.ask(self.path, 'other'))
        self.do('hold', 'A', wait_for='팀장:disk-cleanup')                      # asking again about a locked topic ...
        self.assertIn(('C6', 'A'), {(f['rule'], f['id']) for f in chk.check(list(self.rows().values()), [], NOW)})  # ... is caught

    def test_add_refuses_bad_values(self):
        for kw in ({'priority': 'P9'}, {'end_plan': 'tomorrow'}, {'after': 'nope'}):
            args = dict(title='t', owner='bob', priority='P1', end_plan='-')
            args.update(kw)
            with self.assertRaises(edit.EditError):
                self.do('add', 'A', **args)
        self.assertEqual(self.rows(), {})
        with self.assertRaises(edit.EditError):
            edit.apply(self.path, 'start', 'A', '', now=NOW)                    # who changed it is required


class NotifyTest(Base):
    def test_dry_run_send_once_and_unknown_owner(self):
        self.do('add', 'A', title='late one', owner='bob', priority='P1', end_plan='at:2026-01-10T10:00')
        self.do('add', 'B', title='late too', owner='amy', priority='P0', end_plan='at:2026-01-10T09:00')
        owners = os.path.join(self.tmp, 'owners.tsv')
        with open(owners, 'w', encoding='utf-8') as f:
            f.write('# owner\thandle\nbob\tterm_bob\n')
        state = os.path.join(self.tmp, 'state.json')
        sent = []
        sender = lambda h, t: (sent.append((h, t)) or (0, 'ok'))
        r = notify.run(self.path, owners, state, do_send=False, now=NOW, sender=sender)
        self.assertEqual(sent, [])                                             # dry run sends nothing
        by = {l['id']: l for l in r['lines']}
        self.assertEqual(by['A']['result'], 'dry run')
        self.assertIn('[mai-work] A P1 · 마감 2026-01-10 10:00 지남', by['A']['text'])
        self.assertEqual(by['B']['result'], 'no handle for owner amy')
        self.assertTrue(by['B']['telegram'])
        notify.run(self.path, owners, state, do_send=True, now=NOW, sender=sender)
        self.assertEqual([h for h, _ in sent], ['term_bob'])
        notify.run(self.path, owners, state, do_send=True, now=NOW + 3600, sender=sender)
        self.assertEqual(len(sent), 1)                                         # within 6 h: not again
        notify.run(self.path, owners, state, do_send=True, now=NOW + 7 * 3600, sender=sender)
        self.assertEqual(len(sent), 2)
        failing = lambda h, t: (3, 'busy')
        r = notify.run(self.path, owners, state + '2', do_send=True, now=NOW, sender=failing)
        self.assertTrue({l['id']: l for l in r['lines']}['A']['result'].startswith('send failed rc 3'))
        with open(state + '2', encoding='utf-8') as f:
            self.assertEqual(json.load(f), {})                                 # a failed send is not recorded


class OpsTest(Base):
    def test_old_operations_view_is_kept(self):
        """The same three items as the operations check's own test: overdue FAIL, iter within 50 WARN, no deadline silent."""
        legacy = os.path.join(self.tmp, 'WORKLIST.tsv')
        with open(legacy, 'w', encoding='utf-8', newline='') as f:
            f.write('\t'.join(schema.LEGACY_COLUMNS) + '\n'
                    'A\tx\tP1\tat:2026-01-10T10:00\tlead\t%s\topen\tstage report\n'
                    'B\tx\tP0\titer:6000\tlead\t%s::marker\topen\tfinal score\n'
                    'C\tx\tP3\t-\tlead\t-\topen\toptional\n' % (self.proof, self.proof))
        lv = {b: a for a, b, _ in ops.ops_lines(legacy, NOW, 5990)}
        self.assertEqual((lv['W A'], lv['W B'], 'W C' in lv), ('FAIL', 'WARN', False))
        lv = {b: a for a, b, _ in ops.ops_lines(legacy, NOW, 6000)}
        self.assertEqual(lv['W B'], 'FAIL')
        with open(self.proof, 'w', encoding='utf-8') as f:
            f.write('marker')
        lv = {b: a for a, b, _ in ops.ops_lines(legacy, NOW, 6000)}
        self.assertEqual((lv['W A'], lv['W B']), ('WARN', 'WARN'))           # evidence arrived: asks to close, no FAIL
        self.assertEqual(ops.ops_lines(os.path.join(self.tmp, 'gone.tsv'), NOW)[0][0], 'FAIL')
        self.assertTrue(ops.ops_lines(legacy, NOW, 6000)[-1][2].startswith('3 open · next: B P0'))


if __name__ == '__main__':
    unittest.main()
