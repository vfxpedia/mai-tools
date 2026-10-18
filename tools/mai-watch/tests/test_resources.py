"""Known-answer tests for the wider live view (DESIGN.md sections 9d and 9e): GPU clocks and limits, watched paths, disk and network
rates, AI session usage, the no-command start and the demo folder. Run: python -I tests/test_resources.py
Every expected value is written here from the fixed input, not computed by the code under test."""
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from mai_watch import cli, collector, host, live, nvidia, usage  # noqa: E402

CORE = '0, GPU-a, RTX A, 37, 9714, 16303, 52, 98.25'
EXTRA = '2827, 3090, 14801, 0x0000000000000004, 360.00, 33, 11, 5, 16'


class W:
    """A file target for json.dump that closes after every write (no open handles left behind)."""
    def __init__(self, path):
        self.path = path
        open(path, 'w', encoding='utf-8').close()

    def write(self, text):
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(text)


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


class ThrottleTests(unittest.TestCase):
    def test_known_masks(self):
        self.assertEqual(live.decode_throttle('0x0000000000000000'), [])
        self.assertEqual(live.decode_throttle('0x0000000000000004'), ['sw_power_cap'])
        self.assertEqual(live.decode_throttle('0x41'), ['gpu_idle', 'hw_thermal_slowdown'])
        self.assertEqual(live.decode_throttle('0x200'), ['bit_0x200'])        # a bit outside the table is kept, not dropped
        self.assertIsNone(live.decode_throttle('[N/A]'))                      # unreadable is unknown, not "no limit"


class DamagedInputTests(unittest.TestCase):
    def test_negative_or_huge_mask_is_unknown_and_returns(self):
        self.assertIsNone(live.decode_throttle('-1'))                 # used to loop forever (review R8)
        self.assertIsNone(live.decode_throttle(hex(2 ** 64)))

    def test_nan_is_not_a_number(self):
        self.assertIsNone(nvidia.num('NaN'))
        self.assertIsNone(nvidia.num('inf'))
        g = live.LiveSampler._parse_gpus(CORE + ', NaN, 3090, 14801, 0x0, 360, 33, 11, 5, 16\n', [])[0]
        self.assertEqual((g['util_pct'], g['sm_clock_mhz'], g['sm_clock_max_mhz']), (37, None, 3090))

    def test_sampler_thread_survives_a_failing_sample(self):
        s = live.LiveSampler(psutil_module=False, paths=['.'], usage_on=False, interval_s=0.2, history_s=10,
                             gpu_reader=lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        stop = threading.Event()
        t = threading.Thread(target=s.run, args=(stop,))
        t.start()
        stop.wait(0.7)
        alive = t.is_alive()
        stop.set()
        t.join(3)
        self.assertTrue(alive)
        self.assertTrue(any('sample failed: RuntimeError' in p for x in s.payload()['samples'] for p in x['problems']))


class GpuExtraTests(unittest.TestCase):
    def test_extra_columns_are_parsed(self):
        problems = []
        g = live.LiveSampler._parse_gpus(CORE + ', ' + EXTRA + '\n', problems)[0]
        self.assertEqual((g['util_pct'], g['vram_used_mib'], g['sm_clock_mhz'], g['sm_clock_max_mhz'], g['mem_clock_mhz'], g['throttle'],
                          g['power_limit_w'], g['fan_pct'], g['mem_activity_pct'], g['pcie_gen'], g['pcie_width']),
                         (37, 9714, 2827, 3090, 14801, ['sw_power_cap'], 360, 33, 11, 5, 16))
        self.assertEqual(problems, [])

    def test_core_only_output_leaves_extras_unknown(self):
        g = live.LiveSampler._parse_gpus(CORE + '\n', [])[0]
        self.assertEqual((g['util_pct'], g['sm_clock_mhz'], g['throttle']), (37, None, None))

    def test_driver_that_refuses_extra_fields_falls_back_to_core_and_stays_there(self):
        calls = []

        def fake_run(cmd, flag, query, timeout=20):
            calls.append(query)
            return None if 'clocks.sm' in query else CORE + '\n'
        old = live.nvidia.run_csv
        live.nvidia.run_csv = fake_run
        try:
            s = live.LiveSampler(psutil_module=False, paths=['.'], usage_on=False)
            first = s.sample_once()
            s.sample_once()
        finally:
            live.nvidia.run_csv = old
        self.assertEqual(first['gpus'][0]['util_pct'], 37)
        self.assertEqual(sum('clocks.sm' in q for q in calls), 1)      # asked once, then never again


class FakeIO:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakePs:
    def __init__(self):
        self.nowrap_seen = []
        self.disk = {'PhysicalDrive0': FakeIO(read_bytes=0, write_bytes=0)}
        self.net = {'eth': FakeIO(bytes_recv=0, bytes_sent=0), 'vpn': FakeIO(bytes_recv=0, bytes_sent=0), 'fast': FakeIO(bytes_recv=0, bytes_sent=0),
                    'down': FakeIO(bytes_recv=0, bytes_sent=0), 'Loopback Pseudo-Interface 1': FakeIO(bytes_recv=0, bytes_sent=0)}
        self.stats = {'eth': FakeIO(isup=True, speed=1000), 'vpn': FakeIO(isup=True, speed=4294), 'fast': FakeIO(isup=True, speed=10000), 'down': FakeIO(isup=False, speed=100),
                      'Loopback Pseudo-Interface 1': FakeIO(isup=True, speed=1073)}

    def disk_io_counters(self, perdisk=False, nowrap=True):
        self.nowrap_seen.append(('disk', nowrap))
        return self.disk

    def net_io_counters(self, pernic=False, nowrap=True):
        self.nowrap_seen.append(('net', nowrap))
        return self.net

    def net_if_stats(self):
        return self.stats


class RateTests(unittest.TestCase):
    def test_first_reading_unknown_then_rate_then_reset_unknown(self):
        c = Clock(0.0)
        r = host.Rates(clock=c)
        self.assertEqual(r.update('k', {'a': 100}), {'a': None})
        c.t = 2.0
        self.assertEqual(r.update('k', {'a': 300}), {'a': 100.0})
        c.t = 3.0
        self.assertEqual(r.update('k', {'a': 50}), {'a': None})          # went backwards: a reset, never a negative rate

    def test_network_per_adapter_only_up_no_loopback_virtual_speed_unknown(self):
        ps, c = FakePs(), Clock(0.0)
        rates = host.Rates(clock=c)
        first = host.network(ps, rates)
        # 4294 is the Windows "no real link" value; a real 10 Gbps link is kept (review R5)
        self.assertEqual([(n['nic'], n['rx_mib_s'], n['link_mbps']) for n in first], [('eth', None, 1000), ('fast', None, 10000), ('vpn', None, None)])
        ps.net['eth'] = FakeIO(bytes_recv=4 * 2 ** 20, bytes_sent=2 ** 20)
        c.t = 2.0
        eth = host.network(ps, rates)[0]
        self.assertEqual((eth['rx_mib_s'], eth['tx_mib_s']), (2.0, 0.5))
        # the raw counter is asked for, so psutil does not hide a reset by adding the old total (review R4)
        self.assertEqual(set(ps.nowrap_seen), {('net', False)})

    def test_disk_rates(self):
        ps, c = FakePs(), Clock(0.0)
        rates = host.Rates(clock=c)
        self.assertEqual(host.disk_io(ps, rates), [{'disk': 'PhysicalDrive0', 'read_mib_s': None, 'write_mib_s': None}])
        ps.disk['PhysicalDrive0'] = FakeIO(read_bytes=10 * 2 ** 20, write_bytes=2 ** 20)
        c.t = 1.0
        self.assertEqual(host.disk_io(ps, rates), [{'disk': 'PhysicalDrive0', 'read_mib_s': 10.0, 'write_mib_s': 1.0}])
        self.assertEqual(set(ps.nowrap_seen), {('disk', False)})


Usage = collections.namedtuple('Usage', 'total used free')


class PathTests(unittest.TestCase):
    def test_free_space_unreachable_and_no_answer(self):
        gate = threading.Event()
        hang_calls = []

        def fake_usage(p):
            if p == 'ok':
                return Usage(total=1000 * 2 ** 30, used=990 * 2 ** 30, free=10 * 2 ** 30)
            if p == 'gone':
                raise FileNotFoundError(2, 'no such share')
            hang_calls.append(p)
            gate.wait(5)                                   # a share that hangs
            return Usage(total=1, used=0, free=1)
        w = host.PathWatcher(['ok', 'gone', 'hang'], timeout_s=0.3, usage=fake_usage)
        t0 = time.monotonic()
        r = {x['path']: x for x in w.check(wall=0)}
        self.assertLess(time.monotonic() - t0, 2.0)          # a hanging path never holds the check longer than the timeout
        self.assertEqual((r['ok']['state'], r['ok']['free_gib'], r['ok']['used_pct']), ('ok', 10.0, 99.0))
        self.assertEqual((r['gone']['state'], r['gone']['free_gib']), ('unreachable', None))
        self.assertEqual((r['hang']['state'], r['hang']['free_gib']), ('no answer', None))
        w.check(wall=1)                                      # the hanging probe is still running: no second probe piles up
        self.assertEqual(len(hang_calls), 1)
        gate.set()
        for _ in range(50):                                  # once it answers, the next snapshot shows it at once (review R6)
            if w.snapshot()[2]['state'] == 'ok':
                break
            time.sleep(0.05)
        self.assertEqual(w.snapshot()[2]['state'], 'ok')

    def test_no_answer_does_not_depend_on_clock_resolution(self):
        # a clock that never moves: the old rule (waited >= timeout) could never say "no answer" (the Windows CI failure, review R6)
        gate = threading.Event()
        w = host.PathWatcher(['hang'], timeout_s=0.2, usage=lambda p: gate.wait(5) and Usage(1, 0, 1), clock=lambda: 0.0)
        self.assertEqual(w.check(wall=0)[0]['state'], 'no answer')
        gate.set()

    def test_path_list_is_bounded(self):
        w = host.PathWatcher(['p%d' % i for i in range(70)], usage=lambda p: Usage(1, 0, 1))
        self.assertEqual((len(w.paths), len(w.dropped)), (64, 6))


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.now_ms = 1792300000000
        lim = {'default': {'five_hour': [{'at': self.now_ms - 60000, 'pct': 35, 'reset': '2026-10-18T12:10:00.000Z'},
                                         {'at': self.now_ms - 120000, 'pct': 30, 'reset': '2026-10-18T12:10:00.000Z'}],
                           'seven_day': [{'at': self.now_ms - 60000, 'pct': 16, 'reset': '2020-01-01T00:00:00.000Z'}]},
               'codex:box': {'seven_day': [{'at': self.now_ms - 3600000, 'pct': 48, 'reset': '2026-10-24T20:55:10.000Z'}]}}
        json.dump(lim, W(os.path.join(self.home, 'limits.json')))
        os.makedirs(os.path.join(self.home, 'sessions'))
        json.dump({'id': 'c1', 'name': 'lead', 'doing': 'training', 'contextPercent': 57, 'updatedAt': self.now_ms - 30000},
                  W(os.path.join(self.home, 'sessions', 'c1.json')))
        json.dump({'id': 'old', 'name': 'gone', 'updatedAt': self.now_ms - 3 * 86400000}, W(os.path.join(self.home, 'sessions', 'old.json')))
        cdir = os.path.join(self.home, 'costlog', '2026-10-18')
        os.makedirs(cdir)
        json.dump({'sessionId': 'c1', 'name': 'lead', 'account': 'default', 'events': [
            {'kind': 'turn', 'at': self.now_ms - 40000, 'costUsd': 1.25, 'prompt': 'SECRET-PROMPT-TEXT'},
            {'kind': 'turn', 'at': self.now_ms - 30000, 'costUsd': 0.75, 'prompt': 'x'}, {'kind': 'compact', 'at': self.now_ms}]},
            W(os.path.join(cdir, 'c1.json')))
        json.dump({'sessionId': 'x1', 'name': 'pipeline', 'account': 'codex:box', 'events': [
            {'kind': 'turn', 'at': self.now_ms - 50000, 'costUsd': 0, 'estimatedCostUsd': None, 'inputTokens': 1000, 'outputTokens': 200, 'prompt': 'y'}]},
            W(os.path.join(cdir, 'x1.json')))

    def test_limits_latest_reading_and_expired_window(self):
        rows = usage.limits(os.path.realpath(self.home), self.now_ms, [])
        claude = [r for r in rows if r['engine'] == 'claude'][0]
        self.assertEqual((claude['five_hour']['pct'], claude['five_hour']['read_at']), (35, '2026-10-18T05:05:40Z'))   # 1792300000 - 60 s = 2026-10-18 05:05:40 UTC
        self.assertIsNone(claude['seven_day']['pct'])                  # reset time passed: the old percent is not shown as current
        codex = [r for r in rows if r['engine'] == 'codex'][0]
        self.assertEqual((codex['five_hour'], codex['seven_day']['pct']), (None, 48))

    def test_sessions_sums_and_no_prompt_text(self):
        rows = usage.sessions(os.path.realpath(self.home), self.now_ms, [], today='2026-10-18')
        by = {r['name']: r for r in rows}
        self.assertNotIn('gone', by)
        self.assertEqual((by['lead']['turns_today'], by['lead']['cost_usd_today'], by['lead']['context_pct'], by['lead']['engine']), (2, 2.0, 57, 'claude'))
        self.assertEqual((by['pipeline']['engine'], by['pipeline']['cost_usd_today'], by['pipeline']['tokens_today']), ('codex', None, 1200))
        self.assertEqual((by['lead']['cost_turns'], by['pipeline']['cost_turns'], by['pipeline']['token_turns']), (2, 0, 1))
        self.assertNotIn('SECRET-PROMPT-TEXT', json.dumps(rows))

    def write_cost(self, sid, account, events):
        json.dump({'sessionId': sid, 'name': sid, 'account': account, 'events': events}, W(os.path.join(self.home, 'costlog', '2026-10-18', sid + '.json')))

    def test_unknown_tokens_and_costs_stay_unknown_and_real_zero_stays_zero(self):
        t = self.now_ms - 10000
        self.write_cost('n1', 'codex:box', [{'kind': 'turn', 'at': t, 'inputTokens': None, 'outputTokens': None},
                                            {'kind': 'turn', 'at': t, 'inputTokens': 50, 'outputTokens': None}])
        self.write_cost('z1', 'default', [{'kind': 'turn', 'at': t, 'costUsd': 0}])
        by = {r['id']: r for r in usage.sessions(os.path.realpath(self.home), self.now_ms, [], today='2026-10-18')}
        self.assertEqual((by['n1']['tokens_today'], by['n1']['token_turns'], by['n1']['turns_today']), (None, 0, 2))   # not 0 (review R3)
        self.assertEqual((by['z1']['cost_usd_today'], by['z1']['cost_turns']), (0, 1))                                  # a real 0 is 0
        self.assertIsNone(by['lead_no_log']['turns_today'] if 'lead_no_log' in by else None)

    def test_session_without_cost_log_has_unknown_turns_not_zero(self):
        json.dump({'id': 's9', 'name': 'quiet', 'updatedAt': self.now_ms - 1000}, W(os.path.join(self.home, 'sessions', 's9.json')))
        by = {r['id']: r for r in usage.sessions(os.path.realpath(self.home), self.now_ms, [], today='2026-10-18')}
        self.assertIsNone(by['s9']['turns_today'])

    def test_wrong_types_are_dropped_not_passed_on(self):
        json.dump({'id': 'c2', 'name': {'prompt': 'NESTED-CANARY'}, 'doing': ['NESTED-CANARY'], 'contextPercent': {'prompt': 'NESTED-CANARY'},
                   'updatedAt': self.now_ms - 1000}, W(os.path.join(self.home, 'sessions', 'c2.json')))
        out = usage.read(self.home, clock=lambda: self.now_ms / 1000)
        self.assertNotIn('NESTED-CANARY', json.dumps(out))                                                   # review R1
        c2 = [r for r in out['sessions'] if r['id'] == 'c2'][0]
        self.assertEqual((c2['name'], c2['doing'], c2['context_pct']), (None, '', None))

    def test_a_link_out_of_the_gauge_home_is_refused(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        json.dump({'id': 'ext', 'name': 'LINKED-CANARY', 'updatedAt': self.now_ms - 1000}, W(os.path.join(outside, 'auth.json')))
        made = []
        # a hard link to a file elsewhere: refused by its link count
        try:
            os.link(os.path.join(outside, 'auth.json'), os.path.join(self.home, 'sessions', 'hard.json'))
            made.append('hardlink')
        except OSError:
            pass
        # a directory junction (Windows) or symlink (elsewhere) that leads out: refused by its real path
        link = os.path.join(self.home, 'costlog', '2026-10-19')
        if os.name == 'nt':
            r = subprocess.run(['cmd', '/c', 'mklink', '/J', link, outside], capture_output=True)
            if r.returncode == 0:
                made.append('junction')
        else:
            try:
                os.symlink(outside, link)
                made.append('symlink')
            except OSError:
                pass
        self.assertTrue(made, 'could not make any link to test with')
        problems = []
        root = os.path.realpath(self.home)
        rows = usage.sessions(root, self.now_ms, problems, today='2026-10-19')
        self.assertNotIn('LINKED-CANARY', json.dumps(rows))
        self.assertTrue(problems)
        if os.name == 'nt' and 'junction' in made:
            os.rmdir(link)

    def test_a_file_whose_real_path_is_outside_is_refused(self):
        # a file symlink needs extra rights on Windows, so the rule is checked on the path itself: what a link resolves to is a real
        # path outside the home, and that is exactly what _load must refuse
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        json.dump({'id': 'ext'}, W(os.path.join(outside, 'auth.json')))
        root = os.path.realpath(self.home)
        with self.assertRaises(usage.Refused):
            usage._load(root, os.path.join(outside, 'auth.json'))
        with self.assertRaises(usage.Refused):
            usage._load(root, os.path.join(root, 'sessions', '..', '..', os.path.basename(outside), 'auth.json'))

    def test_missing_home_is_no_source_not_zero(self):
        u = usage.read(os.path.join(self.home, 'nope'))
        self.assertFalse(u['available'])
        self.assertIn('no usage source', u['reason'])


class CliTests(unittest.TestCase):
    def test_no_command_starts_live(self):
        p = subprocess.run([sys.executable, '-m', 'mai_watch', '--interval', '0', '--no-browser'], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn('interval_s must be between', p.stderr)        # reached the live sampler: no command means live

    def test_demo_folder_and_refusal_of_a_real_config(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cfg = cli.write_demo(os.path.join(d, 'demo'))
        with open(os.path.join(d, 'demo', 'status', 'my-first-job.json'), encoding='utf-8') as f:
            job = json.load(f)
        self.assertEqual((job['state'], job['id']), ('running', 'my-first-job'))
        self.assertTrue(os.path.isfile(cfg))
        cli.write_demo(os.path.join(d, 'demo'))                       # a second demo run reuses its own folder
        real = os.path.join(d, 'real')
        os.makedirs(os.path.join(real, 'status'))
        W(os.path.join(real, 'mai-watch.toml')).write('status_dir = "s"\nout_dir = "o"\n')
        W(os.path.join(real, 'status', 'my-first-job.json')).write('{"id": "real", "state": "done"}')
        with self.assertRaises(FileExistsError):
            cli.write_demo(real)
        with open(os.path.join(real, 'status', 'my-first-job.json'), encoding='utf-8') as f:
            self.assertEqual(f.read(), '{"id": "real", "state": "done"}')     # untouched even with the same file name (review R2)

    def test_tilde_in_config_path_is_expanded(self):
        d = tempfile.mkdtemp(dir=os.path.expanduser('~'))
        self.addCleanup(shutil.rmtree, d, True)
        W(os.path.join(d, 'mai-watch.toml')).write('status_dir = "s"\nout_dir = "o"\n')
        cfg = collector.load_config('~/' + os.path.basename(d) + '/mai-watch.toml')        # review R7
        self.assertEqual(os.path.normcase(cfg.status_dir), os.path.normcase(os.path.join(d, 's')))


class SparkGapTests(unittest.TestCase):
    def test_a_gap_longer_than_the_limit_breaks_the_line(self):
        js = os.path.join(ROOT, 'mai_watch', 'viewer-live.js').replace(os.sep, '/')
        script = ("const m=require(%r);"
                  "console.log(JSON.stringify(m.sparkPoints([0,1000,2000,60000],[10,20,30,40],60000,60,100,60,10,5000)))") % js
        p = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        # x = 60 - age/60*60, y = 10 - v/100*10; the 58 s hole between t=2000 and t=60000 is not drawn as a line
        self.assertEqual(json.loads(p.stdout), ['0.0,9.0 1.0,8.0 2.0,7.0', '60.0,6.0'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
