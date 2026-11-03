"""GPU jobs tab: the board's text box is taken apart without changing its values, slow reads are cached, a load failure is reported."""
import types
import unittest

from mai_watch import gpujobs


def fake_board(calls):
    m = types.SimpleNamespace()
    m.Paint = lambda color: None
    m.clock = lambda ts, now: '-' if not ts else 'T%d' % ts
    m.launcher = lambda e: '자동' if e['auto'] else '손'
    m.on_gpu = lambda j, i: j.get('gpu') == i

    def slow_data():
        calls.append('slow')
        return {'read_at': 5.0}
    m.slow_data = slow_data

    def board_data(slow=None):
        calls.append('board')
        return {'now': 100.0, 'smi': {'gpus': {0: {}}}, 'warnings': ['경고 하나'],
                'entries': [{'state': '실행', 'gpu': 0, 'priority': 1, 'start': 90, 'title': '평가', 'auto': True, 'owner': 'w'},
                            {'state': '실행', 'gpu': 1, 'priority': 4, 'title': 'C층 남은 칸', 'auto': False}],
                'jobs': [{'kind': 'guard', 'script': 'g.py', 'pid': 7}]}
    m.board_data = board_data
    m.gpu_box = lambda d, i, w, p: ['┌─ GPU0 · RTX ──┐', '│ EX-41 학습 · S2a   │',
                                    '│ [██░░░░░░] 25 % · 4/16 GB │', '└──┘']
    return m


class GpuJobsTest(unittest.TestCase):
    def test_box_and_rows_keep_board_values(self):
        calls = []
        g = gpujobs.GpuJobs('board.py', clock=lambda: 1000.0, loader=lambda p: fake_board(calls))
        d = g.document()
        self.assertEqual(d['gpus'][0]['title'], 'GPU0 · RTX')
        self.assertEqual(d['gpus'][0]['lines'][0], {'text': 'EX-41 학습 · S2a'})
        self.assertEqual(d['gpus'][0]['lines'][1], {'bar': 0.25, 'text': '25 % · 4/16 GB'})
        self.assertEqual(d['entries'][0]['start'], 'T90')
        self.assertEqual(d['entries'][0]['launcher'], '자동')
        self.assertEqual(d['notes'][0]['text'], '자동 · w')
        self.assertEqual(d['notes'][1]['text'], '대기열 -')     # a folded row without a queue id (11/04)
        self.assertEqual(d['guards'], ['g.py 7'])
        self.assertEqual(d['warnings'], ['경고 하나'])

    def test_slow_read_every_ten_seconds_and_one_second_cache(self):
        calls, now = [], [1000.0]
        g = gpujobs.GpuJobs('board.py', clock=lambda: now[0], loader=lambda p: fake_board(calls))
        g.document(); now[0] += 0.5; g.document()
        self.assertEqual(calls, ['slow', 'board'])
        now[0] += 1.0; g.document()
        self.assertEqual(calls, ['slow', 'board', 'board'])
        now[0] += 10.0; g.document()
        self.assertEqual(calls.count('slow'), 2)

    def test_load_failure_is_reported_and_retried(self):
        tries = []

        def broken(path):
            tries.append(path)
            raise ImportError('no such board')
        now = [0.0]
        g = gpujobs.GpuJobs('missing.py', clock=lambda: now[0], loader=broken)
        self.assertIn('no such board', g.document()['error'])
        now[0] += 2.0
        g.document()
        self.assertEqual(len(tries), 2)


if __name__ == '__main__':
    unittest.main()
