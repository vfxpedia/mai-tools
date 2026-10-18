"""Known-answer tests for notifications and the status command (DESIGN.md section 9g). Run: python -I tests/test_notify.py
Each review finding R13 to R18 has its reproduction here as a regression test."""
import http.server
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
from mai_watch import collector, live, notify, server  # noqa: E402

W = {'level': 'warn', 'kind': 'disk_space', 'subject': 'D:', 'text': 'D: has 37 GiB free'}
B = {'level': 'bad', 'kind': 'disk_space', 'subject': 'D:', 'text': 'D: has 7 GiB free'}
L = {'level': 'warn', 'kind': 'slow_link', 'subject': 'LAN', 'text': 'LAN (wired) is linked at 100 Mbps'}
I = {'level': 'info', 'kind': 'source_problem', 'subject': 'sampler', 'text': 'psutil is not installed'}
HOT = {'level': 'warn', 'kind': 'gpu_hot', 'subject': 'GPU 0', 'text': 'GPU 0 is at 90 C'}


def ev(events):
    return [(e['event'], e['finding']['subject']) for e in events]


def step(n, findings, t, blind=()):
    """update and, as a working sender would, commit what it proposed."""
    e = n.update(findings, t, blind)
    n.commit(e)
    return ev(e)


class NotifierRules(unittest.TestCase):
    def test_hold_then_once_then_worse_then_cleared(self):
        n = notify.Notifier(hold_s=60)
        self.assertEqual(step(n, [W], 0), [])
        self.assertEqual(step(n, [W], 30), [])
        self.assertEqual(step(n, [W], 61), [('new', 'D:')])
        self.assertEqual(step(n, [W], 90), [])                       # staying is not news
        self.assertEqual(step(n, [B], 120), [('worse', 'D:')])
        self.assertEqual(step(n, [], 150), [])                       # gone, but not for 60 s yet
        self.assertEqual(step(n, [], 180), [])
        self.assertEqual(step(n, [], 210), [('cleared', 'D:')])
        self.assertEqual(step(n, [], 240), [])

    def test_a_blip_is_never_announced_and_a_brief_gap_is_not_a_clear(self):
        n = notify.Notifier(hold_s=60)
        step(n, [W], 0)
        self.assertEqual(step(n, [], 30), [])                        # gone before announcement: forgotten
        self.assertEqual(step(n, [W], 60), [])                       # back: the hold starts again
        self.assertEqual(step(n, [W], 90), [])
        self.assertEqual(step(n, [W], 120), [('new', 'D:')])
        self.assertEqual(step(n, [], 150), [])
        self.assertEqual(step(n, [W], 180), [])                      # back within the hold: no clear, no repeat
        self.assertEqual(step(n, [], 210), [])
        self.assertEqual(step(n, [], 240), [])
        self.assertEqual(step(n, [], 270), [('cleared', 'D:')])

    def test_easing_is_quiet_and_level_filter(self):
        n = notify.Notifier(hold_s=0)
        self.assertEqual(step(n, [B, I], 0), [('new', 'D:')])        # info is below the default level
        self.assertEqual(step(n, [W], 1), [])                        # bad to warn: no message
        self.assertEqual(step(n, [B], 2), [('worse', 'D:')])
        m = notify.Notifier(level='info', hold_s=0)
        self.assertEqual(step(m, [I], 0), [('new', 'sampler')])
        with self.assertRaises(ValueError):
            notify.Notifier(level='loud')

    def test_r13_nothing_is_delivered_until_commit(self):
        n = notify.Notifier(hold_s=0)
        self.assertEqual(ev(n.update([W], 0)), [('new', 'D:')])      # the send failed: no commit
        self.assertEqual(ev(n.update([W], 30)), [('new', 'D:')])     # proposed again
        both = n.update([W, L], 60)                                  # a newer finding does not hide the undelivered one
        self.assertEqual(sorted(ev(both)), [('new', 'D:'), ('new', 'LAN')])
        n.commit(both)
        self.assertEqual(ev(n.update([W, L], 90)), [])
        self.assertEqual(ev(n.update([], 120)), [('cleared', 'D:'), ('cleared', 'LAN')])   # hold 0
        self.assertEqual(ev(n.update([], 150)), [('cleared', 'D:'), ('cleared', 'LAN')])   # clear not sent: still pending

    def test_r14_a_finding_that_cannot_be_seen_is_not_cleared(self):
        n = notify.Notifier(hold_s=60)
        for t in (0, 30, 60):
            step(n, [HOT], t)
        self.assertIn('gpu_hot|GPU 0', n.announced)
        for t in (90, 120, 150, 180, 400):                           # the GPU source broke: nothing about temperature is known
            self.assertEqual(step(n, [], t, blind={'gpu'}), [])
        self.assertEqual(step(n, [], 430), [])                       # readable again and absent: the clear timer starts now
        self.assertEqual(step(n, [], 460), [])
        self.assertEqual(step(n, [], 490), [('cleared', 'GPU 0')])
        p = notify.Notifier(hold_s=0)
        step(p, [W], 0)
        self.assertEqual(step(p, [], 10, blind={'path:D:'}), [])     # one folder not checked: its finding waits
        self.assertEqual(step(p, [], 20, blind={'path:E:'}), [('cleared', 'D:')])

    def test_r14_recheck_a_missing_measurement_is_not_a_clear_real_sampler(self):
        # the real path: sample_once -> status -> Notifier; only the nvidia-smi text is made up
        rows = {'hot': '0, GPU-a, RTX A, 50, 9000, 16303, 90, 200\n', 'na': '0, GPU-a, RTX A, 50, 9000, 16303, [N/A], 200\n',
                'cool': '0, GPU-a, RTX A, 50, 9000, 16303, 60, 200\n'}
        cur = ['hot']
        c = [1800000000.0]
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: rows[cur[0]], paths=['.'], usage_on=False, disk_reader=lambda: {},
                             nic_reader=lambda: {}, clock=lambda: c[0])
        n = notify.Notifier(hold_s=60)
        got = []
        for t, phase in ((0, 'hot'), (30, 'hot'), (60, 'hot'), (90, 'na'), (120, 'na'), (150, 'na'), (180, 'na'), (210, 'cool'),
                         (240, 'cool'), (270, 'cool')):
            cur[0] = phase
            c[0] = 1800000000.0 + t
            s.sample_once()
            st = s.status()
            e = n.update(st['judgments'], t, set(st['blind']), set(st['observable']))
            n.commit(e)
            got += [(t, x['event'], x['key']) for x in e if x['key'].startswith('gpu_hot')]
        # announced at 60; temperature unknown from 90 to 180: no clear; readable and cool from 210: cleared 60 s later
        self.assertEqual(got, [(60, 'new', 'gpu_hot|GPU 0'), (270, 'cleared', 'gpu_hot|GPU 0')])

    def test_r14_recheck_an_unreachable_folder_does_not_clear_its_space_warning(self):
        n = notify.Notifier(hold_s=0)
        step(n, [W], 0)
        unreachable = {'level': 'bad', 'kind': 'path_unreachable', 'subject': 'D:', 'text': 'D: does not answer'}
        e = n.update([unreachable], 10, (), {'path_unreachable|D:', 'source_problem|sampler'})      # free space not observable now
        n.commit(e)
        self.assertEqual(ev(e), [('new', 'D:')])                             # the new problem is told; the old one is not cleared
        self.assertEqual(e[0]['finding']['kind'], 'path_unreachable')
        self.assertIn('disk_space|D:', n.announced)

    def test_r14_recheck_observable_keys_from_the_judge(self):
        from mai_watch import judge
        slow = {'paths': [{'path': 'D:\\', 'label': 'D:', 'state': 'unreachable', 'free_gib': None, 'used_pct': None},
                          {'path': 'E:\\', 'label': 'E:', 'state': 'ok', 'free_gib': 900.0, 'used_pct': 80.0},
                          {'path': 'F:\\', 'label': 'F:', 'state': 'not checked yet', 'free_gib': None, 'used_pct': None},
                          # a folder that stopped answering keeps its last numbers on the page; they are not a current reading
                          {'path': 'G:\\', 'label': 'G:', 'state': 'no answer', 'free_gib': 50.0, 'used_pct': 99.0}]}
        last = {'t': '2026-10-18T00:00:00.00Z', 'ram_pct': None, 'nics': [{'nic': 'LAN', 'link_mbps': None}],
                'gpus': [{'index': 0, 'temperature_c': None, 'throttle': [], 'util_pct': 5, 'vram_used_mib': 10}]}
        obs = set(judge.observable([last], slow))
        self.assertIn('path_unreachable|D:', obs)
        self.assertNotIn('disk_space|D:', obs)            # it does not answer: its free space is not known
        self.assertIn('disk_space|E:', obs)
        self.assertNotIn('path_unreachable|F:', obs)
        self.assertNotIn('disk_space|G:', obs)
        self.assertIn('path_unreachable|G:', obs)
        self.assertNotIn('gpu_hot|GPU 0', obs)            # no temperature
        self.assertIn('gpu_clock_limited|GPU 0', obs)
        self.assertNotIn('slow_link|LAN', obs)
        self.assertNotIn('ram_high|RAM', obs)

    def test_r15_unobserved_time_is_not_hold_time(self):
        n = notify.Notifier(hold_s=60, max_gap_s=90)
        self.assertEqual(step(n, [W], 0), [])
        self.assertEqual(step(n, [W], 3600), [])                     # an hour without checks: the hold starts again
        self.assertEqual(step(n, [W], 3630), [])
        self.assertEqual(step(n, [W], 3660), [('new', 'D:')])
        self.assertEqual(step(n, [], 3690), [])
        self.assertEqual(step(n, [], 7290), [])                      # a gap restarts the clear timer too
        self.assertEqual(step(n, [], 7350), [('cleared', 'D:')])

    def test_r17_bad_hold_values_are_refused(self):
        for v in (-1, float('nan'), float('inf'), True, '60'):
            with self.assertRaises(ValueError, msg=repr(v)):
                notify.Notifier(hold_s=v)
        self.assertEqual(notify.Notifier(hold_s=0).hold_s, 0.0)      # 0 is a deliberate "announce at once"

    def test_one_message_per_check_most_severe_first(self):
        events = [{'event': 'new', 'key': 'a', 'finding': L}, {'event': 'new', 'key': 'b', 'finding': B},
                  {'event': 'cleared', 'key': 'c', 'finding': dict(W, text='E: has 40 GiB free')}]
        self.assertEqual(notify.message(events, host='box'), 'mai-watch box: 2 new, 1 cleared\nACT NOW  D: has 7 GiB free\n'
                                                              'LOOK SOON  LAN (wired) is linked at 100 Mbps\ncleared  E: has 40 GiB free\n')


class Sending(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_command_gets_the_text_on_stdin_and_in_the_file(self):
        got, box = os.path.join(self.d, 'got.txt'), os.path.join(self.d, 'outbox.txt')
        cmd = [sys.executable, '-c', 'import sys; open(sys.argv[1], "w", encoding="utf-8").write(sys.stdin.read()); print("sent ok")', got]
        # without the variables a developer machine may set: a plain Windows receiver decodes stdin with its code page
        saved = {k: os.environ.pop(k) for k in ('PYTHONIOENCODING', 'PYTHONUTF8') if k in os.environ}
        self.addCleanup(os.environ.update, saved)
        ok, detail = notify.send(cmd, 'hello \uc548\ub155\n', box)
        self.assertEqual((ok, detail), (True, 'exit 0: sent ok'))
        for p in (got, box):
            with open(p, encoding='utf-8') as f:
                self.assertEqual(f.read(), 'hello \uc548\ub155\n')

    def test_failures_are_reported_not_hidden(self):
        ok, detail = notify.send([sys.executable, '-c', 'import sys; print("boom"); sys.exit(3)'], 'x')
        self.assertEqual((ok, detail), (False, 'exit 3: boom'))
        ok, detail = notify.send([os.path.join(self.d, 'no-such-program')], 'x')
        self.assertFalse(ok)

    def test_split_cmd(self):
        self.assertEqual(notify.split_cmd('powershell -File "C:\\ssd logs\\tg-send.ps1"'), ['powershell', '-File', 'C:\\ssd logs\\tg-send.ps1'])
        self.assertEqual(notify.split_cmd("python 'a b.py' x"), ['python', 'a b.py', 'x'])
        self.assertEqual(notify.split_cmd('python sender.py "" tail'), ['python', 'sender.py', '', 'tail'])
        self.assertEqual(notify.split_cmd('echo a;b & c | d > e $(f)'), ['echo', 'a;b', '&', 'c', '|', 'd', '>', 'e', '$(f)'])
        with self.assertRaises(ValueError):
            notify.split_cmd('python "unclosed')


class FakeSampler:
    def __init__(self, found, fresh=True, blind=()):
        self.found, self.fresh, self.blind, self.notify_state = found, fresh, list(blind), None

    def status(self):
        return {'judgments': self.found, 'fresh': self.fresh, 'stale_reason': None if self.fresh else 'stopped', 'blind': self.blind}

    def now_iso(self):
        return '2026-10-18T00:00:00Z'


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Loop(unittest.TestCase):
    def run_loop(self, sampler, sender, checks, every_s=30, c=None):
        """Runs loop for a fixed number of checks with a fake clock advancing every_s per check."""
        c, stop, n = c or Clock(), threading.Event(), [0]

        class Stop:
            def is_set(self_):
                return n[0] >= checks

            def wait(self_, s):
                n[0] += 1
                c.t += s
        notify.loop(sampler, notify.Notifier(hold_s=0), ['x'], Stop(), every_s=every_s, clock=c, sender=sender)
        return sampler.notify_state

    def test_r13_failed_send_is_retried_with_backoff_and_counted_honestly(self):
        calls, at, c = [], [], Clock()

        def sender(cmd, text, nfile):
            calls.append(text)
            at.append(c.t)
            return (len(calls) >= 3), 'exit %d' % (0 if len(calls) >= 3 else 1)
        st = self.run_loop(FakeSampler([W]), sender, checks=8, c=c)
        # tried at 0 s (fails, wait 30), 30 s (fails, wait 60), 90 s (succeeds); the checks in between do not send
        self.assertEqual(at, [0.0, 30.0, 90.0])
        self.assertTrue(all('D: has 37 GiB free' in t for t in calls))
        self.assertEqual((st['ok'], st['delivered'], st['pending'], st['failures_in_row']), (True, 1, 0, 0))

    def test_r13_a_later_success_carries_the_earlier_failure(self):
        sampler, calls = FakeSampler([W]), []

        def sender(cmd, text, nfile):
            calls.append(text)
            if len(calls) == 1:
                sampler.found = [W, L]                     # a new finding appears after the first failure
                return False, 'exit 1'
            return True, 'exit 0'
        st = self.run_loop(sampler, sender, checks=5)
        self.assertIn('D: has 37 GiB free', calls[1])
        self.assertIn('LAN (wired)', calls[1])
        self.assertEqual(st['delivered'], 2)

    def test_r13_recheck_a_due_finding_that_went_away_is_still_delivered(self):
        # recheck input: W held 60 s and its send failed at 60; W gone at 90; L held from 120; L sent at 180
        seq = {0: [W], 30: [W], 60: [W], 90: [], 120: [L], 150: [L], 180: [L], 210: [L]}
        sampler, calls, c = FakeSampler([W]), [], Clock()

        def sender(cmd, text, nfile):
            calls.append((c.t, text))
            return c.t != 60, 'exit %d' % (1 if c.t == 60 else 0)
        orig = sampler.status
        sampler.status = lambda: dict(orig(), judgments=seq.get(c.t, []))
        n, k = notify.Notifier(hold_s=60), [0]

        class Stop:
            def is_set(self_):
                return k[0] >= 8

            def wait(self_, s):
                k[0] += 1
                c.t += s
        notify.loop(sampler, n, ['x'], Stop(), every_s=30, clock=c, sender=sender)
        self.assertEqual(calls[0][0], 60.0)
        self.assertIn('came and went  D: has 37 GiB free', calls[1][1])      # retried at 90: W is told, not dropped
        self.assertTrue(any('LOOK SOON  LAN' in t for _, t in calls))
        self.assertEqual(sampler.notify_state['delivered'], 2)

    def test_r15_recheck_a_short_stale_stretch_restarts_the_hold(self):
        n = notify.Notifier(hold_s=60)
        self.assertEqual(step(n, [W], 0), [])
        n.interrupt()                                                        # t=30: stale, not observed
        self.assertEqual(step(n, [W], 60), [])                               # the hold restarted at 60
        self.assertEqual(step(n, [W], 90), [])
        self.assertEqual(step(n, [W], 120), [('new', 'D:')])

    def test_recheck_b_a_due_finding_survives_a_stale_stretch(self):
        # pipeline input B: W due at 60 and its send failed; stale at 90; W back at 120; gone and observable from 150
        seq = {0: [W], 30: [W], 60: [W], 90: [W], 120: [W], 150: [], 180: [], 210: []}
        fresh = {90: False}
        sampler, calls, c, k = FakeSampler([W]), [], Clock(), [0]
        orig = sampler.status
        sampler.status = lambda: dict(orig(), judgments=seq.get(c.t, []), fresh=fresh.get(c.t, True), observable=['disk_space|D:'])

        class Stop:
            def is_set(self_):
                return k[0] >= 8

            def wait(self_, s):
                k[0] += 1
                c.t += s

        def sender(cmd, text, nfile):
            calls.append((c.t, text))
            return c.t != 60, 'x'
        notify.loop(sampler, notify.Notifier(hold_s=60), ['x'], Stop(), every_s=30, clock=c, sender=sender)
        self.assertEqual(calls[0][0], 60.0)
        # the debt from 60 is paid at the first fresh check after the retry wait, as the warning it was (W is back at 120)
        self.assertEqual(calls[1][0], 120.0)
        self.assertIn('LOOK SOON  D: has 37 GiB free', calls[1][1])
        self.assertEqual(calls[2][0], 210.0)                                 # observed gone from 150, cleared after the 60 s hold
        self.assertIn('cleared  D: has 37 GiB free', calls[2][1])
        self.assertEqual(sampler.notify_state['delivered'], 2)

    def test_recheck_a_an_unreadable_due_finding_is_not_called_gone(self):
        rows = {'hot': '0, GPU-a, RTX A, 50, 9000, 16303, 90, 200\n', 'na': '0, GPU-a, RTX A, 50, 9000, 16303, [N/A], 200\n'}
        cur, c = ['hot'], [1800000000.0]
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: rows[cur[0]], paths=['.'], usage_on=False, disk_reader=lambda: {},
                             nic_reader=lambda: {}, clock=lambda: c[0])
        n = notify.Notifier(hold_s=60)
        for t, phase in ((0, 'hot'), (30, 'hot'), (60, 'hot')):
            cur[0], c[0] = phase, 1800000000.0 + t
            s.sample_once()
            st = s.status()
            e = n.update(st['judgments'], t, set(st['blind']), set(st['observable']))     # t=60 proposes new; the send fails
        cur[0], c[0] = 'na', 1800000090.0
        s.sample_once()
        st = s.status()
        e = n.update(st['judgments'], 90, set(st['blind']), set(st['observable']))
        hot = [x for x in e if x['key'] == 'gpu_hot|GPU 0']
        self.assertEqual([x['event'] for x in hot], ['new'])                  # not 'passed': its absence is not observed
        text = notify.message(hot, host='box')
        self.assertIn('GPU 0 is at 90 C (cannot be read now; the current state is unknown)', text)
        self.assertNotIn('came and went', text)
        n.commit(hot)
        self.assertEqual(n.update(st['judgments'], 120, set(st['blind']), set(st['observable'])), [])   # announced; clear waits

    def test_r15_recheck_the_loop_restarts_the_hold_after_stale(self):
        sampler, calls, c, k = FakeSampler([W]), [], Clock(), [0]
        fresh = {0: True, 30: False, 60: True, 90: True, 120: True}
        orig = sampler.status
        sampler.status = lambda: dict(orig(), fresh=fresh.get(c.t, True))

        class Stop:
            def is_set(self_):
                return k[0] >= 5

            def wait(self_, s):
                k[0] += 1
                c.t += s
        notify.loop(sampler, notify.Notifier(hold_s=60), ['x'], Stop(), every_s=30, clock=c,
                    sender=lambda cmd, t, f: calls.append(c.t) or (True, 'ok'))
        self.assertEqual(calls, [120.0])          # not at 60: the stale check at 30 broke the observation

    def test_r15_stale_samples_are_not_judged(self):
        calls = []
        st = self.run_loop(FakeSampler([W], fresh=False), lambda c, t, f: calls.append(t) or (True, 'ok'), checks=4)
        self.assertEqual(calls, [])
        self.assertIn('stale', st['detail'])


class StatusDocServer:
    def __init__(self, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:%d/status.json' % self.srv.server_address[1]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def run_status(url, *extra):
    # the OS error text can be in the system language (Korean on the reference machine); read it without assuming a code page
    return subprocess.run([sys.executable, '-m', 'mai_watch', 'status', '--url', url] + list(extra), cwd=ROOT,
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)


class StatusCommand(unittest.TestCase):
    def test_exit_codes_and_lines_from_a_real_sampler(self):
        # a fixed clock keeps the one sample fresh however slow the machine is (a macOS runner took 35 s here, and the sample went stale)
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: '', paths=['.'], usage_on=False, disk_reader=lambda: {}, nic_reader=lambda: {},
                             clock=lambda: 1800000000.0)
        s.sample_once()
        srv = server.make_server(None, 0, live=s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = 'http://127.0.0.1:%d/status.json' % srv.server_address[1]
        p = run_status(url)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('0 act now, 0 look soon', p.stdout)
        self.assertIn('info  psutil is not installed', p.stdout)
        doc = json.loads(run_status(url, '--json').stdout)
        self.assertEqual((doc['schema'], doc['fresh']), ('mai-watch-status-v1', True))
        self.assertIn('gpu', doc['blind'])                                 # no GPU reading: the GPU source is blind
        s.check_paths()
        s.thresholds = {'free_gib_warn': 10 ** 9}
        p = run_status(url)
        self.assertEqual(p.returncode, 1)
        self.assertIn('warn  ', p.stdout)

    def test_r15_samples_that_stopped_are_not_a_current_reading(self):
        c = [1800000000.0]
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: '', paths=['.'], usage_on=False, disk_reader=lambda: {},
                             nic_reader=lambda: {}, clock=lambda: c[0])
        s.sample_once()
        c[0] += 3450                                                       # sampling stopped almost an hour ago
        doc = s.status()
        self.assertEqual((doc['fresh'], doc['sample_age_s']), (False, 3450.0))
        srv = server.make_server(None, 0, live=s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        p = run_status('http://127.0.0.1:%d/status.json' % srv.server_address[1])
        self.assertEqual(p.returncode, 2)
        self.assertIn('not fresh', p.stderr)

    def test_r16_malformed_or_inconsistent_documents_exit_2(self):
        good = {'schema': 'mai-watch-status-v1', 'fresh': True, 'counts': {'bad': 0, 'warn': 1, 'info': 0}, 'judgments': [W]}
        cases = {
            'no judgments': {'schema': 'mai-watch-status-v1', 'counts': {}, 'fresh': True},
            'counts disagree': dict(good, counts={'bad': 0, 'warn': 0, 'info': 0}),
            'a list': [],
            'no counts': {'schema': 'mai-watch-status-v1', 'fresh': True, 'judgments': [W]},
            'no freshness': {k: v for k, v in good.items() if k != 'fresh'},
            'bad level': dict(good, judgments=[dict(W, level='loud')], counts={'bad': 0, 'warn': 0, 'info': 0}),
            'not json': b'<html>',
        }
        why = {'no judgments': 'judgments is not a list', 'counts disagree': 'counts do not match', 'a list': 'not a JSON object',
               'no counts': 'counts do not match', 'no freshness': 'freshness is missing', 'bad level': 'judgment 0 is malformed',
               'not json': 'is mai-watch running'}
        for name, body in cases.items():
            d = StatusDocServer(body)
            try:
                p = run_status(d.url)
            finally:
                d.close()
            self.assertEqual(p.returncode, 2, '%s: %s %s' % (name, p.stdout, p.stderr))
            self.assertNotIn('Traceback', p.stderr, name)
            self.assertIn(why[name], p.stderr, name)                       # the reason is named, not a generic failure
        d = StatusDocServer(good)
        try:
            self.assertEqual(run_status(d.url).returncode, 1)
        finally:
            d.close()

    def test_unreachable_is_not_all_clear(self):
        p = run_status('http://127.0.0.1:9/status.json')
        self.assertEqual(p.returncode, 2)
        self.assertIn('is mai-watch running', p.stderr)


class NoWindows(unittest.TestCase):
    def test_every_child_is_started_without_a_window(self):
        # measured on Windows: a console-less parent (pythonw, a scheduled task) running nvidia-smi without the flag opened a visible
        # window per call (10 OpenConsole in 10 calls), with it none; nvidia-smi runs every second
        from mai_watch import disks, nics, nvidia
        seen = []

        def fake_run(*a, **kw):
            seen.append(kw.get('creationflags'))
            raise OSError('not run')
        old = subprocess.run
        subprocess.run = fake_run
        try:
            nvidia.run_csv(['nvidia-smi'], 'query-gpu', 'index')
            disks._run(['x'], 1)
            nics.read()
            notify.send(['x'], 'hi', run=fake_run)                         # send takes its runner as an argument
        finally:
            subprocess.run = old
        expected = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.assertEqual(len(seen), 4 if os.name == 'nt' else 3)            # nics.read asks PowerShell only on Windows
        self.assertEqual(set(seen), {expected})


class Settings(unittest.TestCase):
    def test_r18_notify_file_in_a_config_is_relative_to_the_config(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cfg = os.path.join(d, 'watch.toml')
        with open(cfg, 'w', encoding='utf-8') as f:
            f.write('status_dir = "s"\nout_dir = "o"\nnotify_file = "outbox.txt"\n')
        c = collector.load_config(cfg)
        self.assertEqual(os.path.normcase(c.notify_file), os.path.normcase(os.path.join(d, 'outbox.txt')))

    def test_r17_bad_settings_stop_before_anything_starts(self):
        p = subprocess.run([sys.executable, '-m', 'mai_watch', '--no-browser', '--port', '0', '--notify-cmd', 'x', '--notify-hold', '-1'],
                           cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn('notify hold', p.stderr)
        self.assertNotIn('mai-watch live:', p.stdout)                      # the server never started


if __name__ == '__main__':
    unittest.main(verbosity=2)
