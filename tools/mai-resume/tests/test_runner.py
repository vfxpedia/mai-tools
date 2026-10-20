"""Tests for mai_resume.runner with a fake Orca: retry after a failed send, one instance only, restart alert, status."""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from mai_resume import core, runner  # noqa: E402

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 20, 0, 0, tzinfo=UTC)


class FakeOrca:
    exe = 'fake'

    def __init__(self, terms, screens, fail_sends=0, list_error=False):
        self.terms, self.screens, self.fail_sends, self.list_error = terms, screens, fail_sends, list_error
        self.sent = []

    def terminals(self):
        if self.list_error:
            raise RuntimeError('orca down')
        return self.terms

    def screen(self, handle):
        if handle not in self.screens:
            raise RuntimeError('cannot read')
        return self.screens[handle]

    def send(self, handle, text):
        if self.fail_sends > 0:
            self.fail_sends -= 1
            return False
        self.sent.append((handle, text))
        return True


def limits_file(d, pct):
    p = os.path.join(d, 'limits.json')
    reset = (T0 + dt.timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump({'default': {'five_hour': [{'at': int(T0.timestamp() * 1000), 'pct': pct, 'reset': reset}]}}, f)
    return p


def wj(path, doc):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def rj(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def rt(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


NOSLEEP = lambda s: None  # noqa: E731


TERMS = [{'handle': 'a', 'agentIdentity': 'claude', 'connected': True, 'writable': True}]
IDLE = {'a': '❯ \n'}


TWO = [{'handle': 'term_2580fc05-aaaa', 'agentIdentity': 'claude', 'connected': True, 'writable': True},
       {'handle': 'term_bdb042be-bbbb', 'agentIdentity': 'claude', 'connected': True, 'writable': True}]
TWO_IDLE = {t['handle']: '❯ \n' for t in TWO}


class Targets(unittest.TestCase):
    """The allow list file (owner 10/20: old sessions got resume and keep-alive and restarted long-finished work)."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lim = limits_file(self.d, 94)
        self.log = runner.Log(os.path.join(self.d, 'resume.log'))
        self.cfg = dict(core.merged({}), targets_file=os.path.join(self.d, 'targets.txt'))
        runner._targets_seen.clear()

    def sent_to(self, cfg=None):
        orca = FakeOrca(TWO, TWO_IDLE)
        runner.round_once(orca, {}, cfg or self.cfg, self.lim, T0, self.log)
        return sorted(h for h, _ in orca.sent)

    def test_only_listed_panes_get_anything(self):
        with open(self.cfg['targets_file'], 'w', encoding='utf-8') as f:
            f.write('# lead keeps this list\n2580fc05   # lead\n')
        self.assertEqual(self.sent_to(), ['term_2580fc05-aaaa'])

    def test_empty_list_sends_nothing(self):
        with open(self.cfg['targets_file'], 'w', encoding='utf-8') as f:
            f.write('# nobody for now\n')
        self.assertEqual(self.sent_to(), [])

    def test_list_is_read_again_every_round(self):
        with open(self.cfg['targets_file'], 'w', encoding='utf-8') as f:
            f.write('2580fc05\n')
        orca = FakeOrca(TWO, TWO_IDLE)
        st = runner.round_once(orca, {}, self.cfg, self.lim, T0, self.log)
        with open(self.cfg['targets_file'], 'w', encoding='utf-8') as f:
            f.write('2580fc05\nbdb042be\n')
        runner.round_once(orca, st, self.cfg, self.lim, T0 + dt.timedelta(minutes=1), self.log)
        self.assertEqual(sorted(h for h, _ in orca.sent), ['term_2580fc05-aaaa', 'term_bdb042be-bbbb'])

    def test_missing_file_watches_every_pane_and_says_so(self):
        self.assertEqual(self.sent_to(), ['term_2580fc05-aaaa', 'term_bdb042be-bbbb'])
        self.assertIn('missing: every pane is watched', rt(os.path.join(self.d, 'resume.log')))


class Runner(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lim = limits_file(self.d, 94)
        self.log = runner.Log(os.path.join(self.d, 'resume.log'))

    def test_failed_send_is_retried_next_round_and_sent_once(self):
        orca = FakeOrca(TERMS, IDLE, fail_sends=1)
        st = runner.round_once(orca, {}, core.merged({}), self.lim, T0, self.log)
        self.assertEqual(orca.sent, [])
        self.assertEqual(len(st['pending']), 1)
        self.assertEqual(st['sent'], {})
        st = runner.round_once(orca, st, core.merged({}), self.lim, T0 + dt.timedelta(minutes=1), self.log)
        self.assertEqual([h for h, _ in orca.sent], ['a'])
        st = runner.round_once(orca, st, core.merged({}), self.lim, T0 + dt.timedelta(minutes=2), self.log)
        self.assertEqual(len(orca.sent), 1, 'no duplicate after the retry')

    def test_typing_that_starts_right_before_sending_defers(self):
        class LateTyper(FakeOrca):
            reads = 0

            def screen(self, handle):
                self.reads += 1
                return {'text': '❯', 'prompt_trailing': 1 if self.reads == 1 else 0}
        orca = LateTyper(TERMS, IDLE)
        st = runner.round_once(orca, {}, core.merged({}), self.lim, T0, self.log)
        self.assertEqual(orca.sent, [], 'second look found typed text, nothing typed in')
        self.assertEqual(len(st['pending']), 1)
        self.assertEqual(st['sent'], {})
        self.assertIn('DEFER', rt(os.path.join(self.d, 'resume.log')))

    def test_dry_run_sends_nothing(self):
        orca = FakeOrca(TERMS, IDLE)
        runner.round_once(orca, {}, core.merged({}), self.lim, T0, self.log, dry=True)
        self.assertEqual(orca.sent, [])
        self.assertIn('DRY send a', rt(os.path.join(self.d, 'resume.log')))

    def test_run_once_writes_state_and_survives_a_bad_round(self):
        home = os.path.join(self.d, 'home')
        rc = runner.run(home=home, limits_path=self.lim, once=True, orca=FakeOrca(TERMS, IDLE, list_error=True),
                        clock=lambda: T0)
        self.assertEqual(rc, 0)
        st = rj(os.path.join(home, 'state.json'))
        self.assertEqual(st['heartbeat'], '2026-10-20T00:00:00Z')
        self.assertIn('ROUND error', rt(os.path.join(home, 'resume.log')))

    def test_only_one_instance_can_hold_the_lock(self):
        port = 28799
        first = runner.take_lock(port)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(runner.take_lock(port))
        finally:
            first.close()
        again = runner.take_lock(port)
        self.assertIsNotNone(again, 'the lock is free again once the holder is gone')
        again.close()

    def test_second_run_exits_when_the_lock_is_held(self):
        home = os.path.join(self.d, 'home2')
        os.makedirs(home)
        wj(os.path.join(home, 'config.json'), {'lock_port': 28798})
        held = runner.take_lock(28798)
        try:
            self.assertEqual(runner.run(home=home, limits_path=self.lim, orca=FakeOrca(TERMS, IDLE), clock=lambda: T0), 3)
        finally:
            held.close()

    def test_restart_after_a_crash_sends_an_alert(self):
        home = os.path.join(self.d, 'home3')
        os.makedirs(home)
        marker = os.path.join(self.d, 'alert.txt')
        cfg = {'lock_port': 28797, 'poll_s': 60,
               'notify_cmd': [sys.executable, '-c', 'import sys; open(sys.argv[1], "w", encoding="utf-8").write(sys.stdin.read())', marker]}
        wj(os.path.join(home, 'config.json'), cfg)
        wj(os.path.join(home, 'state.json'), {'heartbeat': '2026-10-19T23:40:00Z', 'clean_exit': False})

        class Stop(Exception):
            pass

        def clock_then_stop(calls=[0]):
            calls[0] += 1
            if calls[0] > 2:
                raise KeyboardInterrupt
            return T0

        rc = runner.run(home=home, limits_path=self.lim, orca=FakeOrca(TERMS, IDLE), clock=clock_then_stop, sleep=NOSLEEP)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(marker), 'restart alert must be sent')
        self.assertIn('no watch for 20 min', rt(marker))
        st = rj(os.path.join(home, 'state.json'))
        self.assertTrue(st['clean_exit'], 'an interrupted stop is a clean exit')

    def test_clean_previous_exit_sends_no_alert(self):
        home = os.path.join(self.d, 'home4')
        os.makedirs(home)
        marker = os.path.join(self.d, 'alert4.txt')
        cfg = {'lock_port': 28796, 'notify_cmd': [sys.executable, '-c', 'open(r"%s", "w").write("x")' % marker]}
        wj(os.path.join(home, 'config.json'), cfg)
        wj(os.path.join(home, 'state.json'), {'heartbeat': '2026-10-19T20:00:00Z', 'clean_exit': True})

        def clock_then_stop(calls=[0]):
            calls[0] += 1
            if calls[0] > 1:
                raise KeyboardInterrupt
            return T0
        runner.run(home=home, limits_path=self.lim, orca=FakeOrca(TERMS, IDLE), clock=clock_then_stop, sleep=NOSLEEP)
        self.assertFalse(os.path.exists(marker))

    def test_status_exit_codes(self):
        home = os.path.join(self.d, 'home5')
        os.makedirs(home)
        wj(os.path.join(home, 'state.json'), {'heartbeat': '2026-10-20T00:00:00Z', 'pid': 1})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(runner.status(home=home, clock=lambda: T0 + dt.timedelta(seconds=90)), 0)
            self.assertEqual(runner.status(home=home, clock=lambda: T0 + dt.timedelta(seconds=181)), 1)
            self.assertEqual(runner.status(home=os.path.join(self.d, 'nothing'), clock=lambda: T0), 1)


EMPTY = {'text': 'out\n❯ \n', 'prompt_trailing': 1}


class ScreenSeq(FakeOrca):
    """Each read of the pane returns the next screen; the last one repeats."""
    def __init__(self, seq):
        super().__init__([{'handle': 'L', 'agentIdentity': 'claude', 'connected': True, 'writable': True}], {})
        self.seq = list(seq)

    def screen(self, handle):
        return self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]


class SafeSend(unittest.TestCase):
    """10/20 17:0x: a report was sent into the lead pane while the owner was typing there."""
    def send(self, seq, wait_s=30):
        orca = ScreenSeq(seq)
        rc = runner.safe_send(orca, 'L', 'report', wait_s=wait_s, step_s=5, sleep=NOSLEEP, log=lambda *_: None)
        return rc, orca.sent

    def test_owner_typing_in_the_lead_pane_gets_nothing(self):
        typing = [{'text': 'out\n❯ 지금 ' + 'x' * n + '\n', 'prompt_trailing': 0} for n in range(40)]
        self.assertEqual(self.send(typing), (4, []))

    def test_hidden_typed_text_is_not_overwritten(self):
        self.assertEqual(self.send([{'text': 'out\n❯\n', 'prompt_trailing': 0}]), (4, []))

    def test_screen_still_changing_is_not_quiet(self):
        moving = [{'text': 'out %d\n❯ \n' % n, 'prompt_trailing': 1} for n in range(40)]
        self.assertEqual(self.send(moving), (4, []))

    def test_quiet_empty_prompt_is_sent_once(self):
        self.assertEqual(self.send([EMPTY]), (0, [('L', 'report')]))

    def test_sent_after_the_owner_stops_and_submits(self):
        typed = {'text': 'out\n❯ 안녕\n', 'prompt_trailing': 0}
        self.assertEqual(self.send([typed, typed, typed, EMPTY]), (0, [('L', 'report')]))

    def test_unknown_pane_is_an_error(self):
        orca = ScreenSeq([EMPTY])
        self.assertEqual(runner.safe_send(orca, 'nope', 'r', sleep=NOSLEEP, log=lambda *_: None), 2)
        self.assertEqual(orca.sent, [])


if __name__ == '__main__':
    unittest.main()
