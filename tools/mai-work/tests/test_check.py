"""Each rule C1 to C10 fires on an input made to break it, and a clean list gives no finding (known answers)."""
import datetime
import os
import tempfile
import unittest

from mai_work import check as chk
from mai_work import convert as conv
from mai_work import schema

NOW = datetime.datetime(2026, 1, 10, 12, 0).timestamp()
PAST = 'at:2026-01-10T10:00'
FUTURE = 'at:2026-01-11T10:00'


def row(**kw):
    r = dict.fromkeys(schema.WORK_COLUMNS, '')
    r.update({'owner': 'bob', 'priority': 'P1', 'status': 'open', 'end_plan': FUTURE})
    r.update(kw)
    return r


def rules(rows, events=(), it=None):
    return sorted({(f['rule'], f['id']) for f in chk.check(rows, list(events), NOW, it)})


class CheckTest(unittest.TestCase):
    def test_clean_list_has_no_finding(self):
        rows = [row(id='A', status='done', evidence='-'), row(id='B', after='A'), row(id='C', status='doing', start_actual='2026-01-10T11:00:00')]
        self.assertEqual(rules(rows), [])

    def test_c1_overdue_without_evidence(self):
        self.assertEqual(rules([row(id='A', end_plan=PAST)]), [('C1', 'A')])
        self.assertEqual(rules([row(id='A', end_plan='iter:500')], it=600), [('C1', 'A')])
        self.assertEqual(rules([row(id='A', end_plan='iter:500')], it=None), [])          # no update count: not judged
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'proof.md')
            open(p, 'w').close()
            self.assertEqual(rules([row(id='A', end_plan=PAST, evidence=p)]), [('C7', 'A')])   # evidence: not C1, but mark done

    def test_c2_start_passed(self):
        self.assertEqual(rules([row(id='A', start_plan=PAST)]), [('C2', 'A')])

    def test_c3_order(self):
        rows = [row(id='A'), row(id='B', status='doing', after='A'), row(id='C', after='Z')]
        self.assertEqual(rules(rows), [('C3', 'B'), ('C3', 'C')])

    def test_c4_priority_inversion(self):
        rows = [row(id='A', status='doing', priority='P3'), row(id='B', priority='P0')]
        self.assertEqual(rules(rows), [('C4', 'A')])
        rows[1]['after'] = 'A'                                    # B cannot start yet: no inversion
        self.assertEqual(rules(rows), [])

    def test_c5_records(self):
        rows = [row(id='A', status='hold'), row(id='B', status='replaced', replaced_by='Q', decided_at='2026-01-09T10:00:00+09:00'),
                row(id='C', status='cancelled', decided_at='2026-01-09T10:00:00+09:00')]
        self.assertEqual(rules(rows), [('C5', 'A'), ('C5', 'B'), ('C5', 'C')])
        ev = [{'ts': '2026-01-10T09:00:00+09:00', 'decided_at': '2026-01-10T08:00:00+09:00', 'id': 'D', 'event': 'change',
               'field': 'end_plan', 'from': 'at:2026-01-10T10:00', 'to': 'at:2026-01-12T10:00', 'why': '', 'decision': ''}]
        self.assertEqual(rules([row(id='D')], ev), [('C5', 'D')])

    def test_c6_owner_asked_again_about_a_locked_topic(self):
        rows = [row(id='A', status='done', locked='disk-cleanup', decided_at='2026-01-03T02:10:00+09:00', decision='L149'),
                row(id='B', wait_for='팀장:disk-cleanup')]
        found = chk.check(rows, [], NOW)
        self.assertEqual([(f['rule'], f['id']) for f in found], [('C6', 'B')])
        self.assertIn('이미 A 에서 확정', found[0]['msg'])
        rows[1]['wait_for'] = '팀장:another-topic'
        self.assertEqual(rules(rows), [])

    def test_c8_doing_without_change(self):
        self.assertEqual(rules([row(id='A', status='doing', start_actual='2026-01-08T10:00:00')]), [('C8', 'A')])

    def test_c9_owner_wait_age(self):
        ev = [{'ts': '2026-01-09T08:00:00', 'id': 'A', 'event': 'hold', 'decided_at': ''}]
        self.assertEqual(rules([row(id='A', status='hold', wait_for='팀장 결정')], ev), [('C9', 'A')])

    def test_c10_decision_time(self):
        rows = [row(id='A', status='done', locked='t', decided_at='19:3x', decision='L1')]       # a guess is not a time
        self.assertEqual(rules(rows), [('C10', 'A')])
        rows[0]['decided_at'] = '2026-01-09T19:35:00+09:00'
        self.assertEqual(rules(rows), [])
        ev = [{'ts': '2026-01-09T10:00:00+09:00', 'decided_at': '2026-01-09T18:00:00+09:00', 'id': 'A', 'event': 'decide'}]
        self.assertEqual(rules(rows, ev), [('C10', 'A')])                                         # decided after it was written

    def test_document_reads_the_old_list_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'WORKLIST.tsv')
            with open(p, 'w', encoding='utf-8', newline='') as f:
                f.write('\t'.join(schema.LEGACY_COLUMNS) + '\nA1\ts\tP1\t' + PAST + '\tbob\t-\topen\tlate item\n'
                        'A2\ts\tP2\t-\tamy\t-\tdropped\tgone\n')
            d = chk.document(p, now=NOW)
            self.assertEqual(d['format'], 'legacy')
            self.assertEqual(sorted((f['rule'], f['id']) for f in d['findings']), [('C1', 'A1'), ('C10', 'A2'), ('C5', 'A2')])
            self.assertEqual(d['counts']['FAIL'], 3)
            # 11/07: the old list with WORK.tsv columns added at the end is still read; a real decision time clears C10
            with open(p, 'w', encoding='utf-8', newline='') as f:
                f.write('\t'.join(schema.LEGACY_COLUMNS) + '\tdecision\tdecided_at\n'
                        'A2\ts\tP2\t-\tamy\t-\tdropped\tgone\tdecisions.tsv line 9\t2026-01-09T17:19:44+09:00\n'
                        'A3\ts\tP2\t-\tamy\t-\tdropped\tgone\t\t\n')
            d = chk.document(p, now=NOW)
            self.assertEqual(sorted((f['rule'], f['id']) for f in d['findings']), [('C10', 'A3'), ('C5', 'A3')])
            with open(p, 'w', encoding='utf-8') as f:
                f.write('\t'.join(schema.LEGACY_COLUMNS) + '\tnot_a_column\nA\ts\tP1\t-\tx\t-\topen\tw\tz\n')
            self.assertIn('error', chk.document(p, now=NOW))      # an unknown extra column is refused, not guessed
            with open(p, 'w', encoding='utf-8') as f:
                f.write('id\tsomething\nA\tb\n')
            self.assertIn('error', chk.document(p, now=NOW))
            self.assertIn('error', chk.document(os.path.join(tmp, 'missing.tsv'), now=NOW))


if __name__ == '__main__':
    unittest.main()
