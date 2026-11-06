"""Conversion keeps every cell (round trip), refuses what it does not understand, and the round trip catches a changed cell."""
import os
import tempfile
import unittest

from mai_work import convert as conv
from mai_work import schema

HEADER = '\t'.join(schema.LEGACY_COLUMNS)
ROWS = [
    'A1\tchat 10:00\tP1\tat:2026-01-02T03:04\tbob\tdocs/a.md::ok\topen\tfirst item, with a comma',
    'A2\tA1 follow-up\tP0\titer:500\tamy\t-\tdone\tsecond · 둘째',
    'A3\tchat 11:00\tP3\t-\tbob\t\tdropped\tthird "quoted"',
]


def write(tmp, text):
    p = os.path.join(tmp, 'WORKLIST.tsv')
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return p


class ConvertTest(unittest.TestCase):
    def test_round_trip_keeps_every_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = conv.convert(write(tmp, HEADER + '\n' + '\n'.join(ROWS) + '\n'), os.path.join(tmp, 'out'), now='T')
            self.assertEqual(r['rows'], 3)
            self.assertEqual(r['diffs'], [])
            self.assertTrue(r['same_text'])                      # the rebuilt old file equals the original byte for byte
            _, _, w0 = conv.read_tsv(os.path.join(tmp, 'out', 'WORK.tsv'))
            self.assertEqual(w0[2]['title'], 'third "quoted"')   # quotes stay ordinary characters
            _, _, work = conv.read_tsv(os.path.join(tmp, 'out', 'WORK.tsv'))
            self.assertEqual([w['status'] for w in work], ['open', 'done', 'cancelled'])
            self.assertEqual(work[0]['end_plan'], 'at:2026-01-02T03:04')
            self.assertEqual(work[1]['title'], 'second · 둘째')
            self.assertEqual(work[2]['decided_at'], 'unknown')     # a decision without a known time is marked, not guessed
            self.assertEqual(work[0]['decided_at'], '')
            _, header, events = conv.read_tsv(os.path.join(tmp, 'out', 'WORK-events.tsv'))
            self.assertEqual(header, schema.EVENT_COLUMNS)
            self.assertEqual([(e['from'], e['to']) for e in events], [('open', 'open'), ('done', 'done'), ('dropped', 'cancelled')])

    def test_changed_cell_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write(tmp, HEADER + '\n' + '\n'.join(ROWS) + '\n')
            _, _, legacy = conv.read_tsv(src)
            conv.convert(src, os.path.join(tmp, 'out'), now='T')
            _, _, work = conv.read_tsv(os.path.join(tmp, 'out', 'WORK.tsv'))
            work[1]['owner'] = 'someone else'
            self.assertEqual(conv.round_trip(legacy, work), [('A2', 'owner', 'amy', 'someone else')])
            work[1]['owner'] = 'amy'
            self.assertEqual(conv.round_trip(legacy, work[:2]), [('*', 'rows', 3, 2)])   # a lost row is caught too

    def test_refuses_unknown_status_extra_column_and_repeated_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            for text, word in ((HEADER + '\nB1\ts\tP1\t-\tx\t-\tparked\tw\n', 'status'),
                               (HEADER + '\tmore\nB1\ts\tP1\t-\tx\t-\topen\tw\tz\n', 'columns'),
                               (HEADER + '\nB1\ts\tP1\t-\tx\t-\topen\tw\nB1\ts\tP1\t-\tx\t-\topen\tw\n', 'repeats'),
                               (HEADER + '\nB1\ts\tP1\t-\tx\t-\topen\n', 'number of cells')):
                with self.assertRaises(conv.ConvertError) as e:
                    conv.convert(write(tmp, text), os.path.join(tmp, 'out'), now='T')
                self.assertIn(word, str(e.exception))


if __name__ == '__main__':
    unittest.main()
