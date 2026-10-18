"""Known-answer tests for notifications and the status command (DESIGN.md section 9g). Run: python -I tests/test_notify.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from mai_watch import live, notify, server  # noqa: E402

W = {'level': 'warn', 'kind': 'disk_space', 'subject': 'D:', 'text': 'D: has 37 GiB free'}
B = {'level': 'bad', 'kind': 'disk_space', 'subject': 'D:', 'text': 'D: has 7 GiB free'}
L = {'level': 'warn', 'kind': 'slow_link', 'subject': 'LAN', 'text': 'LAN (wired) is linked at 100 Mbps'}
I = {'level': 'info', 'kind': 'source_problem', 'subject': 'sampler', 'text': 'psutil is not installed'}


def subjects(r):
    return [[f['subject'] for f in part] for part in r]


class NotifierRules(unittest.TestCase):
    def test_hold_then_once_then_worse_then_cleared(self):
        n = notify.Notifier(hold_s=60)
        self.assertEqual(subjects(n.update([W], 0)), [[], [], []])          # not yet: must last 60 s
        self.assertEqual(subjects(n.update([W], 61)), [['D:'], [], []])     # announced
        self.assertEqual(subjects(n.update([W], 200)), [[], [], []])        # staying is not news
        self.assertEqual(subjects(n.update([B], 210)), [[], ['D:'], []])    # worse
        self.assertEqual(subjects(n.update([], 220)), [[], [], []])         # gone, but not for 60 s yet
        self.assertEqual(subjects(n.update([], 281)), [[], [], ['D:']])     # cleared
        self.assertEqual(subjects(n.update([], 400)), [[], [], []])

    def test_a_blip_is_never_announced_and_a_brief_gap_is_not_a_clear(self):
        n = notify.Notifier(hold_s=60)
        n.update([W], 0)
        self.assertEqual(subjects(n.update([], 30)), [[], [], []])          # gone before announcement: forgotten
        self.assertEqual(subjects(n.update([W], 40)), [[], [], []])         # back: the hold starts again
        self.assertEqual(subjects(n.update([W], 99)), [[], [], []])
        self.assertEqual(subjects(n.update([W], 101)), [['D:'], [], []])
        self.assertEqual(subjects(n.update([], 110)), [[], [], []])
        self.assertEqual(subjects(n.update([W], 120)), [[], [], []])        # back within the hold: no clear, no repeat
        self.assertEqual(subjects(n.update([], 130)), [[], [], []])
        self.assertEqual(subjects(n.update([], 191)), [[], [], ['D:']])

    def test_easing_is_quiet_and_level_filter(self):
        n = notify.Notifier(hold_s=0)
        self.assertEqual(subjects(n.update([B, I], 0)), [['D:'], [], []])   # info is below the default level
        self.assertEqual(subjects(n.update([W], 1)), [[], [], []])          # bad to warn: no message
        self.assertEqual(subjects(n.update([B], 2)), [[], ['D:'], []])      # and warn to bad again is worse again
        m = notify.Notifier(level='info', hold_s=0)
        self.assertEqual(subjects(m.update([I], 0)), [['sampler'], [], []])
        with self.assertRaises(ValueError):
            notify.Notifier(level='loud')

    def test_one_message_per_check_most_severe_first(self):
        text = notify.message([L, B], [], [dict(W, text='E: has 40 GiB free')], host='box')
        self.assertEqual(text, 'mai-watch box: 2 new, 1 cleared\nACT NOW  D: has 7 GiB free\nLOOK SOON  LAN (wired) is linked at 100 Mbps\n'
                               'cleared  E: has 40 GiB free\n')


class Sending(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_command_gets_the_text_on_stdin_and_in_the_file(self):
        got, box = os.path.join(self.d, 'got.txt'), os.path.join(self.d, 'outbox.txt')
        cmd = [sys.executable, '-c', 'import sys; open(sys.argv[1], "w", encoding="utf-8").write(sys.stdin.read()); print("sent ok")', got]
        ok, detail = notify.send(cmd, 'hello \uc548\ub155\n', box)
        self.assertEqual((ok, detail), (True, 'exit 0: sent ok'))
        with open(got, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'hello \uc548\ub155\n')
        with open(box, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'hello \uc548\ub155\n')

    def test_failures_are_reported_not_hidden(self):
        ok, detail = notify.send([sys.executable, '-c', 'import sys; print("boom"); sys.exit(3)'], 'x')
        self.assertEqual((ok, detail), (False, 'exit 3: boom'))
        ok, detail = notify.send([os.path.join(self.d, 'no-such-program')], 'x')
        self.assertFalse(ok)

    def test_split_cmd_keeps_backslashes_and_groups_quotes(self):
        self.assertEqual(notify.split_cmd('powershell -File "C:\\ssd logs\\tg-send.ps1"'), ['powershell', '-File', 'C:\\ssd logs\\tg-send.ps1'])
        self.assertEqual(notify.split_cmd("python 'a b.py' x"), ['python', 'a b.py', 'x'])
        with self.assertRaises(ValueError):
            notify.split_cmd('python "unclosed')


class FakeSampler:
    def __init__(self, found):
        self.found, self.notify_state = found, None

    def status(self):
        return {'judgments': self.found}

    def now_iso(self):
        return '2026-10-18T00:00:00Z'


class Loop(unittest.TestCase):
    def test_loop_sends_news_and_records_the_result(self):
        sent, stop = [], threading.Event()
        s = FakeSampler([W])

        def sender(cmd, text, nfile):
            sent.append(text)
            stop.set()
            return False, 'exit 1: no network'
        t = threading.Thread(target=notify.loop, args=(s, notify.Notifier(hold_s=0), ['x'], stop), kwargs={'every_s': 0.05, 'sender': sender})
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(sent), 1)
        self.assertIn('LOOK SOON  D: has 37 GiB free', sent[0])
        self.assertEqual(s.notify_state['ok'], False)                     # a failing sender is visible in status.json
        self.assertEqual(s.notify_state['detail'], 'exit 1: no network')


class StatusCommand(unittest.TestCase):
    def run_status(self, url, *extra):
        return subprocess.run([sys.executable, '-m', 'mai_watch', 'status', '--url', url] + list(extra), cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_exit_codes_and_lines(self):
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: '', paths=['.'], usage_on=False, disk_reader=lambda: {}, nic_reader=lambda: {})
        s.sample_once()
        srv = server.make_server(None, 0, live=s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = 'http://127.0.0.1:%d/status.json' % srv.server_address[1]
        p = self.run_status(url)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)            # only info findings (no psutil, no GPU): nothing at warn
        self.assertIn('0 act now, 0 look soon', p.stdout)
        self.assertIn('info  psutil is not installed', p.stdout)
        doc = json.loads(self.run_status(url, '--json').stdout)
        self.assertEqual(doc['schema'], 'mai-watch-status-v1')
        s.check_paths()                                                    # the folder's free space must be read before it can be judged
        s.thresholds = {'free_gib_warn': 10 ** 9}                          # every folder now counts as low on space
        p = self.run_status(url)
        self.assertEqual(p.returncode, 1)
        self.assertIn('warn  ', p.stdout)

    def test_unreachable_is_not_all_clear(self):
        p = self.run_status('http://127.0.0.1:9/status.json')
        self.assertEqual(p.returncode, 2)
        self.assertIn('is mai-watch running', p.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
