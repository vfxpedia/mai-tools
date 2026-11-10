"""inbox tab: names, addressee from the subject, newest first, errors as a document (python -m pytest tests/test_inbox.py)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mai_watch import inbox  # noqa: E402

TERMS = [{'handle': 'term_2e7579c1-aaaa', 'title': 'super-lx'}, {'handle': 'term_bf125aeb-bbbb', 'title': 'Linux plan | foothold-lab'},
         {'handle': 'term_f1f00218-cccc', 'title': 'bridge-claude'}]
TARGETS = '2e7579c1  # super-lx (claude)\nbf125aeb  # lead-lx (claude)\n'
MSGS = [{'sequence': 3, 'created_at': '2026-11-10T13:14:28Z', 'type': 'status', 'from_handle': 'term_bf125aeb-bbbb',
         'to_handle': 'run:run_x', 'subject': '[lead-lx → super-lx]  재부팅\n가능', 'body': 'a\nb', 'run_id': 'run_x'},
        {'sequence': 7, 'created_at': '2026-11-10T13:20:00Z', 'type': 'question', 'from_handle': 'term_2e7579c1-aaaa',
         'to_handle': 'term_bf125aeb-bbbb', 'subject': '질문', 'body': 'x' * (inbox.BODY + 5)},
        {'sequence': 5, 'created_at': 'bad', 'type': 'status', 'from_handle': 'term_f1f00218-cccc', 'to_handle': 'run:run_x',
         'subject': '[bridge-claude] 보고', 'body': ''}]


class InboxTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.targets = os.path.join(d, 'targets.txt')
        open(self.targets, 'w', encoding='utf-8').write(TARGETS)

    def runner(self, msgs):
        def run(orca, *args):
            if args[:2] == ('terminal', 'list'):
                return {'terminals': TERMS}
            if args[:2] == ('orchestration', 'inbox'):
                return {'messages': msgs}
            raise AssertionError(args)
        return run

    def test_names_and_addressee(self):
        doc = inbox.Inbox(runner=self.runner(MSGS), targets=self.targets, clock=lambda: 1.0).document()
        self.assertEqual([m['seq'] for m in doc['messages']], [7, 5, 3])                  # newest first
        m3 = doc['messages'][2]
        self.assertEqual((m3['from'], m3['to'], m3['to_run']), ('lead-lx', 'super-lx', True))   # name from targets.txt, addressee from subject
        self.assertEqual(m3['subject'], '[lead-lx → super-lx] 재부팅 가능')                  # one line
        m7 = doc['messages'][0]
        self.assertEqual((m7['from'], m7['to'], m7['cut'], len(m7['body'])), ('super-lx', 'lead-lx', True, inbox.BODY))
        m5 = doc['messages'][1]
        self.assertEqual((m5['from'], m5['to'], m5['at']), ('bridge-claude', 'run 전체', None))  # name from a one-word tab title
        self.assertEqual(doc['run'], 'run_x')
        self.assertIn('lead-lx', doc['people'])

    def test_error_is_a_document(self):
        def broken(orca, *args):
            raise RuntimeError('orca down')
        doc = inbox.Inbox(runner=broken, targets=self.targets, clock=lambda: 2.0).document()
        self.assertIn('orca down', doc['error'])
        self.assertEqual(doc['messages'], [])
        self.assertIn('못 읽음', inbox.text_view(doc))

    def test_text_view_newest_last(self):
        doc = inbox.Inbox(runner=self.runner(MSGS), targets=self.targets, clock=lambda: 1.0).document()
        text = inbox.text_view(doc)
        self.assertLess(text.index('#3'), text.index('#7'))
        self.assertIn('lead-lx → super-lx', text)


if __name__ == '__main__':
    unittest.main()
