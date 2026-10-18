"""Known-answer and mutation tests for mai_watch M1. Run: python -I tools/mai-watch/tests/test_mai_watch.py

Every expected value was fixed from the design (DESIGN.md sections 4 to 8) or from measured nvidia-smi output before the code
was written, not read back from the code under test. The mutation tests prove the suites are sensitive: with a rule deliberately
broken, the matching suite must fail. No test creates GPU load. A missing jsonschema is a failure, not a skip.
"""
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit('jsonschema is required for the contract tests (pip install jsonschema)')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, ROOT)
from mai_watch import collector, idle, nvidia, status  # noqa: E402

EXAMPLES = os.path.join(ROOT, 'schema', 'examples')
T0 = datetime.datetime(2026, 10, 18, 3, 0, 0)
U1, U2 = 'GPU-aaaaaaaa-0000-0000-0000-000000000001', 'GPU-bbbbbbbb-0000-0000-0000-000000000002'


def readj(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def at(sec):
    return T0 + datetime.timedelta(seconds=sec)


def z(sec):
    return status.format_time(at(sec))


# measured on a Windows 11 WDDM machine 2026-10-15 (shape only): idle GPUs, a desktop process list with [N/A] and a permission marker
GPU_TWO_IDLE = '0, %s, NVIDIA GeForce RTX 5080, 0, 1200, 16303, 40, 25.10\n1, %s, NVIDIA GeForce RTX 5080, 0, 5645, 16303, 38, [N/A]\n' % (U1, U2)
APPS_WDDM = (U2 + r', 1234, C:\Windows\explorer.exe, [N/A]' + '\n' + U2 + ', 5678, [Insufficient Permissions], [N/A]\n' + U2 + ', 9012, C:\\py\\python.exe, [N/A]\n')


class ParserTests(unittest.TestCase):
    def test_two_idle_gpus(self):
        devs, problems = nvidia.parse_gpus(GPU_TWO_IDLE)
        self.assertEqual(problems, [])
        self.assertEqual([d['index'] for d in devs], [0, 1])
        self.assertEqual(devs[0]['utilization_pct'], 0)
        self.assertEqual(devs[0]['power_w'], 25.1)
        self.assertEqual(devs[1]['memory_used_mib'], 5645)

    def test_not_available_is_none_never_zero(self):
        devs, _ = nvidia.parse_gpus(GPU_TWO_IDLE)
        self.assertIsNone(devs[1]['power_w'])

    def test_one_busy_single_gpu(self):
        devs, _ = nvidia.parse_gpus('0, %s, NVIDIA GeForce RTX 5080, 97, 14000, 16303, 71, 310.5\n' % U1)
        self.assertEqual((len(devs), devs[0]['utilization_pct']), (1, 97))

    def test_wddm_process_list_kept_as_is(self):
        apps, problems = nvidia.parse_apps(APPS_WDDM)
        self.assertEqual(problems, [])
        self.assertEqual([a['pid'] for a in apps], [1234, 5678, 9012])
        self.assertEqual(apps[1]['name'], '[Insufficient Permissions]')
        self.assertTrue(all(a['memory_mib'] is None for a in apps))

    def test_malformed_row_is_reported(self):
        devs, problems = nvidia.parse_gpus('0, %s, X, 5\n' % U1)
        self.assertEqual(devs, [])
        self.assertEqual(len(problems), 1)

    def test_empty_output(self):
        self.assertEqual(nvidia.parse_gpus(''), ([], []))
        self.assertEqual(nvidia.parse_apps('\n \n'), ([], []))

    def test_missing_tool_is_unavailable_not_a_crash(self):
        devices, apps, problems = nvidia.sample(['definitely-not-a-real-binary-xyz'])
        self.assertIsNone(devices)
        self.assertTrue(problems)


class IdleTests(unittest.TestCase):
    def feed(self, tracker, series):
        events = []
        for sec, util, running in series:
            events += [(e['type'], e) for e in tracker.update(at(sec), util, running)]
        return events

    def test_opens_after_min_from_first_sample_and_closes_after_resume(self):
        tr = idle.IdleTracker(window_s=60, threshold_pct=5, min_s=60, resume_s=20)
        series = [(t, 0, False) for t in range(0, 61, 10)] + [(70, 90, False), (80, 90, False), (90, 90, False)]
        ev = self.feed(tr, series)
        self.assertEqual([e[0] for e in ev], ['idle_started', 'idle_ended'])
        started, ended = ev[0][1], ev[1][1]
        self.assertEqual((started['at'], started['since']), (at(60), at(0)))     # recorded from the first sample, confirmed at 60
        self.assertEqual((ended['at'], ended['since'], ended['duration_s']), (at(90), at(0), 70))

    def flap_tracker(self):
        return idle.IdleTracker(window_s=10, threshold_pct=5, min_s=30, resume_s=20)

    def test_short_blip_does_not_close_the_interval(self):
        tr = self.flap_tracker()
        ev = self.feed(tr, [(0, 0, False), (10, 0, False), (20, 0, False), (30, 0, False), (40, 80, False), (50, 0, False), (60, 0, False)])
        self.assertEqual([e[0] for e in ev], ['idle_started'])
        self.assertTrue(tr.open)

    def test_long_busy_closes_it(self):
        tr = self.flap_tracker()
        ev = self.feed(tr, [(0, 0, False), (10, 0, False), (20, 0, False), (30, 0, False), (40, 80, False), (50, 0, False),
                            (60, 80, False), (70, 80, False), (80, 80, False)])
        self.assertEqual([e[0] for e in ev], ['idle_started', 'idle_ended'])
        self.assertEqual(ev[1][1]['duration_s'], 60)

    def test_flapping_below_min_never_opens(self):
        tr = self.flap_tracker()
        ev = self.feed(tr, [(0, 0, False), (10, 0, False), (20, 80, False), (30, 0, False), (40, 0, False), (50, 80, False)])
        self.assertEqual(ev, [])

    def test_running_workload_blocks_idle(self):
        tr = self.flap_tracker()
        self.assertEqual(self.feed(tr, [(t, 0, True) for t in range(0, 200, 10)]), [])

    def test_unavailable_utilization_is_never_idle(self):
        tr = self.flap_tracker()
        self.assertEqual(self.feed(tr, [(t, None, False) for t in range(0, 200, 10)]), [])

    def test_clock_step_back_is_ignored(self):
        tr = self.flap_tracker()
        self.feed(tr, [(0, 0, False), (10, 0, False), (20, 0, False), (30, 0, False)])
        self.assertEqual(tr.update(at(5), 0, False), [])
        self.assertEqual(tr.update(at(30), 0, False), [])
        self.assertTrue(tr.open)

    def test_state_survives_serialization(self):
        tr = self.flap_tracker()
        self.feed(tr, [(0, 0, False), (10, 0, False), (20, 0, False), (30, 0, False)])
        tr2 = idle.IdleTracker.from_dict(json.loads(json.dumps(tr.to_dict())), window_s=10, threshold_pct=5, min_s=30, resume_s=20)
        self.assertTrue(tr2.open)
        self.assertEqual(tr2.idle_since, at(0))


def make_cfg(tmp, **kw):
    kw.setdefault('idle_window_s', 10)
    kw.setdefault('idle_min_s', 30)
    kw.setdefault('idle_resume_s', 20)
    return collector.Config(os.path.join(tmp, 'status'), os.path.join(tmp, 'out'), **kw)


def doc(**kw):
    d = {'schema_version': 1, 'id': 'train-a', 'kind': 'job', 'state': 'running', 'updated_at': z(0), 'heartbeat_interval_s': 30,
         'device_uuids': [U1], 'started_at': z(-3600)}
    d.update(kw)
    return d


def entry(d, file='train-a.json'):
    return {'file': file, 'doc': d, 'problems': status.validate(d)}


def gpus(util1=0, util2=0):
    return [{'index': 0, 'uuid': U1, 'name': 'RTX', 'utilization_pct': util1, 'memory_used_mib': 1, 'memory_total_mib': 2, 'temperature_c': 40, 'power_w': 20},
            {'index': 1, 'uuid': U2, 'name': 'RTX', 'utilization_pct': util2, 'memory_used_mib': 1, 'memory_total_mib': 2, 'temperature_c': 40, 'power_w': 20}]


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.cfg = make_cfg(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def run_series(self, steps, entries_fn, devices_fn=lambda s: gpus(), apps=None, state=None):
        out = []
        for sec in steps:
            snap, events, state = collector.cycle(self.cfg, at(sec), devices_fn(sec), apps or [], entries_fn(sec), state)
            out.append((snap, events))
        return out, state

    def types(self, results):
        return [e['type'] for _, ev in results for e in ev]

    def test_idle_opens_with_unrecorded_reason(self):
        res, _ = self.run_series([0, 10, 20, 30, 40], lambda s: [])
        dev = res[-1][0]['devices'][0]
        self.assertTrue(dev['idle'])
        self.assertEqual((dev['idle_since'], dev['idle_for_s'], dev['idle_reason']), (z(0), 40, 'unrecorded'))
        self.assertIn('device_idle', [a['type'] for a in res[-1][0]['alerts']])

    def test_idle_reason_comes_from_hold_reason_only(self):
        waiting = doc(id='eval-b', state='waiting', hold_reason='waiting for verification verdict', updated_at=z(0), heartbeat_interval_s=1000)
        res, _ = self.run_series([0, 10, 20, 30, 40], lambda s: [entry(waiting, 'eval-b.json')])
        self.assertEqual(res[-1][0]['devices'][0]['idle_reason'], {'workload': 'eval-b', 'reason': 'waiting for verification verdict'})

    def test_fresh_running_workload_blocks_idle(self):
        res, _ = self.run_series([0, 10, 20, 30, 40, 50], lambda s: [entry(doc(updated_at=z(s)))])
        dev = res[-1][0]['devices'][0]
        self.assertFalse(dev['idle'])
        self.assertEqual(dev['running_workloads'], ['train-a'])
        started = [e['uuid'] for _, ev in res for e in ev if e['type'] == 'idle_started']
        self.assertNotIn(U1, started)          # the other, unused device does go idle
        self.assertIn(U2, started)

    def test_stale_running_workload_is_reported_stale_once_and_does_not_block_idle(self):
        old = doc(updated_at=z(0))     # heartbeat 30 s, factor 3: stale after 90 s without refresh
        res, state = self.run_series([0, 60, 100, 110, 120, 130], lambda s: [entry(old)])
        self.assertEqual(self.types(res).count('workload_stale'), 1)
        w = res[-1][0]['workloads'][0]
        self.assertEqual((w['liveness'], w['effective_state']), ('stale', 'stale'))
        self.assertTrue(res[-1][0]['devices'][0]['idle'] or res[-1][0]['devices'][0]['idle_candidate_since'])

    def test_workload_recovers(self):
        entries = lambda s: [entry(doc(updated_at=z(0 if s < 200 else s)))]
        res, _ = self.run_series([0, 100, 110, 210], entries)
        self.assertEqual(self.types(res).count('workload_stale'), 1)
        self.assertEqual(self.types(res).count('workload_recovered'), 1)

    def test_done_job_is_never_stale(self):
        res, _ = self.run_series([0, 1000, 5000], lambda s: [entry(doc(state='done', updated_at=z(0)))])
        self.assertEqual([t for t in self.types(res) if t.startswith('workload_')], [])
        self.assertEqual(res[-1][0]['workloads'][0]['liveness'], 'ended')

    def test_invalid_document_reported_once_never_dropped(self):
        bad = {'schema_version': 1, 'id': 'x'}
        res, _ = self.run_series([0, 10, 20], lambda s: [entry(bad, 'bad.json')])
        self.assertEqual(self.types(res).count('workload_invalid'), 1)
        self.assertEqual(res[-1][0]['invalid'][0]['file'], 'bad.json')
        self.assertIn('workload_invalid', [a['type'] for a in res[-1][0]['alerts']])

    def test_first_progress_evidence_from_artifact_mtime(self):
        d = doc(updated_at=z(0), artifacts=['x'])
        times = {10: at(5), 20: at(15)}
        res = []
        state = None
        for sec in (0, 10, 20):
            snap, _, state = collector.cycle(self.cfg, at(sec), gpus(), [], [entry(d)], state, mtime_of=lambda p, s=sec: times.get(s))
            res.append(snap['workloads'][0])
        self.assertIsNone(res[0]['first_progress_at'])
        self.assertEqual(res[1]['first_progress_at'], z(5))
        self.assertEqual(res[2]['first_progress_at'], z(5))            # stays at the first evidence
        self.assertEqual((res[2]['artifact_mtime'], res[2]['artifact_age_s']), (z(15), 5))
        self.assertEqual(res[2]['heartbeat_age_s'], 20)

    def test_device_unavailable_and_recovered(self):
        state = None
        _, _, state = collector.cycle(self.cfg, at(0), gpus(), [], [], state)
        snap, ev, state = collector.cycle(self.cfg, at(10), None, [], [], state)
        self.assertEqual([e['type'] for e in ev], ['device_unavailable', 'device_unavailable'])
        self.assertEqual(snap['source'], 'unavailable')
        self.assertIn('device_unavailable', [a['type'] for a in snap['alerts']])
        _, ev, _ = collector.cycle(self.cfg, at(20), gpus(), [], [], state)
        self.assertEqual([e['type'] for e in ev], ['device_recovered', 'device_recovered'])

    def test_process_list_is_shown_but_never_decides_idle(self):
        apps, _ = nvidia.parse_apps(APPS_WDDM)
        res, _ = self.run_series([0, 10, 20, 30, 40], lambda s: [], apps=apps)
        d2 = res[-1][0]['devices'][1]
        self.assertTrue(d2['idle'])
        self.assertEqual(len(d2['processes']), 3)
        self.assertEqual([p['pid'] for p in d2['user_processes']], [5678, 9012])      # explorer.exe filtered from the view only


class IoTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name
        self.status_dir = os.path.join(self.tmp, 'status')
        os.makedirs(self.status_dir)
        self.out = os.path.join(self.tmp, 'out')
        self.stub = os.path.join(self.tmp, 'fake_smi.py')
        with open(self.stub, 'w', encoding='utf-8') as f:
            f.write('import sys\n'
                    'a = " ".join(sys.argv)\n'
                    'if "--query-gpu" in a:\n'
                    '    print(%r, end="")\n'
                    'elif "--query-compute-apps" in a:\n'
                    '    print(%r, end="")\n' % (GPU_TWO_IDLE, APPS_WDDM))
        self.toml = os.path.join(self.tmp, 'mai-watch.toml')
        py = sys.executable.replace(os.sep, '/')
        with open(self.toml, 'w', encoding='utf-8') as f:
            f.write('status_dir = "status"\nout_dir = "out"\ninterval_s = 10\nnvidia_smi = ["%s", "%s"]\n' % (py, self.stub.replace(os.sep, '/')))

    def tearDown(self):
        self._t.cleanup()

    def cli(self, *args):
        code = 'import sys; sys.path.insert(0, %r); from mai_watch.cli import main; sys.exit(main(sys.argv[1:]))' % ROOT
        return subprocess.run([sys.executable, '-c', code] + list(args), capture_output=True, text=True, encoding='utf-8')

    def test_collect_once_writes_the_four_files_and_check_passes(self):
        r = self.cli('collect', '--config', self.toml, '--once')
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ('snapshot.json', 'collector_heartbeat.json', 'state.json', 'events.jsonl'):
            self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        snap = readj(os.path.join(self.out, 'snapshot.json'))
        self.assertEqual([d['uuid'] for d in snap['devices']], [U1, U2])
        self.assertEqual(len(snap['devices'][1]['processes']), 3)
        events = [json.loads(x) for x in open(os.path.join(self.out, 'events.jsonl'), encoding='utf-8').read().splitlines()]
        self.assertEqual(events[0]['type'], 'collector_started')
        self.assertFalse(os.path.exists(os.path.join(self.out, 'collector.lock')), 'lock must be released')
        c = self.cli('check', '--config', self.toml)
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)

    def test_check_fails_when_heartbeat_is_stale_or_missing(self):
        c = self.cli('check', '--config', self.toml)
        self.assertEqual(c.returncode, 1)
        self.assertIn('collector_missing', c.stdout)
        self.cli('collect', '--config', self.toml, '--once')
        hp = os.path.join(self.out, 'collector_heartbeat.json')
        hb = readj(hp)
        hb['last_cycle_at'] = '2020-01-01T00:00:00Z'
        with open(hp, 'w', encoding='utf-8') as f:
            json.dump(hb, f)
        c = self.cli('check', '--config', self.toml)
        self.assertEqual(c.returncode, 1)
        self.assertIn('collector_stale', c.stdout)

    def test_second_collector_is_refused_while_lock_is_held(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, 'collector.lock'), 'w') as f:
            f.write(str(os.getpid()))        # this test process is alive
        r = self.cli('collect', '--config', self.toml, '--once')
        self.assertEqual(r.returncode, 2)
        self.assertIn('another collector', r.stderr)

    def test_lock_of_a_dead_process_is_taken_over(self):
        try:
            import psutil
        except ImportError:
            self.skipTest('liveness of a pid cannot be known without psutil on Windows (by design the lock is then kept)')
        pid = 4000000
        self.assertFalse(psutil.pid_exists(pid))
        os.makedirs(self.out)
        with open(os.path.join(self.out, 'collector.lock'), 'w') as f:
            f.write(str(pid))
        self.assertEqual(self.cli('collect', '--config', self.toml, '--once').returncode, 0)

    def test_validate_command_known_answers(self):
        ok = self.cli('validate', os.path.join(EXAMPLES, 'valid-running-job.json'))
        bad = self.cli('validate', os.path.join(EXAMPLES, 'invalid-state-idle.json'))
        self.assertEqual((ok.returncode, bad.returncode), (0, 1))
        self.assertIn('INVALID', bad.stdout)

    def test_unreadable_status_file_is_reported(self):
        with open(os.path.join(self.status_dir, 'broken.json'), 'w') as f:
            f.write('{not json')
        entries = collector.read_status_dir(self.status_dir)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]['problems'])

    def test_files_without_schema_version_are_ignored(self):
        with open(os.path.join(self.status_dir, 'other.json'), 'w') as f:
            f.write('{"hello": 1}')
        self.assertEqual(collector.read_status_dir(self.status_dir), [])


class ViewerTests(unittest.TestCase):
    def setUp(self):
        from mai_watch import server
        self._t = tempfile.TemporaryDirectory()
        self.out = self._t.name
        for name, body in (('snapshot.json', '{"ok": 1}'), ('state.json', 'internal'), ('events.jsonl', '{"type": "x"}' + chr(10))):
            with open(os.path.join(self.out, name), 'w', encoding='utf-8') as f:
                f.write(body)
        import threading
        self.srv = server.make_server(self.out, 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self._t.cleanup()

    def get(self, path):
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (self.port, path), timeout=5) as r:
                return r.status, r.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            return e.code, ''

    def test_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], '127.0.0.1')

    def test_serves_page_and_three_files(self):
        code, body = self.get('/')
        self.assertEqual(code, 200)
        self.assertIn('<title>mai_watch</title>', body)
        self.assertEqual(self.get('/snapshot.json'), (200, '{"ok": 1}'))
        self.assertEqual(self.get('/snapshot.json?t=123')[0], 200)
        self.assertEqual(self.get('/events.jsonl')[0], 200)

    def test_serves_nothing_else(self):
        for path in ('/state.json', '/collector.lock', '/../mai_watch/cli.py', '/%2e%2e/mai_watch/cli.py', '/mai_watch/cli.py', '/collector_heartbeat.json'):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_page_makes_no_external_request_and_has_no_em_dash(self):
        with open(os.path.join(ROOT, 'mai_watch', 'viewer.html'), encoding='utf-8') as f:
            html = f.read()
        self.assertNotIn('http://', html)
        self.assertNotIn('https://', html)
        self.assertNotIn(chr(0x2014), html)
        self.assertNotIn('innerHTML', html)          # data from status documents is only ever written as text


class IdleObservationTests(unittest.TestCase):
    """independent review W1 and W2: time that was not observed is never idle."""

    def tracker(self):
        return idle.IdleTracker(window_s=600, threshold_pct=5, min_s=30, resume_s=20, max_gap_s=30)

    def test_w1_two_samples_an_hour_apart_are_not_an_idle_hour(self):
        tr = self.tracker()
        ev = tr.update(at(0), 0, False) + tr.update(at(3600), 0, False)
        self.assertEqual(ev, [])
        self.assertFalse(tr.open)

    def test_w1_gap_closes_an_open_interval_at_the_last_observed_sample(self):
        tr = self.tracker()
        for t in (0, 10, 20, 30):
            tr.update(at(t), 0, False)
        self.assertTrue(tr.open)
        ev = tr.update(at(3600), 0, False)
        self.assertEqual([e['type'] for e in ev], ['idle_ended'])
        self.assertEqual((ev[0]['reason'], ev[0]['duration_s'], ev[0]['unobserved_s']), ('observation_gap', 30, 3570))
        self.assertFalse(tr.open)

    def test_w2_missing_samples_after_a_low_one_are_not_idle(self):
        tr = self.tracker()
        ev = []
        for t, u in ((0, 0), (10, None), (20, None), (30, None)):
            ev += tr.update(at(t), u, False)
        self.assertEqual(ev, [])
        self.assertFalse(tr.open)

    def test_w2_open_interval_closes_as_unobservable_after_resume_s(self):
        tr = self.tracker()
        for t in (0, 10, 20, 30):
            tr.update(at(t), 0, False)
        ev = []
        for t in (40, 50, 60):
            ev += tr.update(at(t), None, False)
        self.assertEqual([(e['type'], e['reason']) for e in ev], [('idle_ended', 'unobservable')])

    def test_w2_unknown_sample_never_reuses_older_low_samples(self):
        tr = self.tracker()
        for t in (0, 10, 20):
            tr.update(at(t), 0, False)
        tr.update(at(30), None, False)
        self.assertFalse(tr.open)
        self.assertIsNone(tr.cond_since)


def snapshot_for(pid=111, generated=0, **over):
    s = {'schema': collector.SNAPSHOT_SCHEMA, 'generated_at': z(generated), 'collector': {'pid': pid, 'started_at': z(-100)},
         'devices': [], 'workloads': [], 'invalid': [], 'alerts': []}
    s.update(over)
    return s


class SourceAndCheckTests(unittest.TestCase):
    """independent review W3, W4, W5."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name
        self.cfg = make_cfg(self.tmp)

    def tearDown(self):
        self._t.cleanup()

    def test_w3_missing_source_alerts_on_the_very_first_cycle(self):
        snap, ev, _ = collector.cycle(self.cfg, at(0), None, [], [], {})
        self.assertIn('source_unavailable', [a['type'] for a in snap['alerts']])

    def test_w3_host_without_gpu_can_opt_out(self):
        cfg = make_cfg(self.tmp, require_gpu_source=False)
        snap, _, _ = collector.cycle(cfg, at(0), None, [], [], {})
        self.assertEqual(snap['alerts'], [])

    def test_w3_expected_device_that_never_appeared_alerts(self):
        cfg = make_cfg(self.tmp, expected_device_uuids=[U1, 'GPU-never-seen'])
        snap, _, _ = collector.cycle(cfg, at(0), gpus(), [], [], {})
        self.assertEqual([a for a in snap['alerts'] if a['type'] == 'device_missing'], [{'type': 'device_missing', 'uuid': 'GPU-never-seen'}])

    def write_pair(self, snapshot=None, heartbeat=None):
        out = os.path.join(self.tmp, 'out')
        os.makedirs(out, exist_ok=True)
        hb = {'pid': 111, 'started_at': z(-100), 'last_cycle_at': z(0), 'interval_s': 10}
        hb.update(heartbeat or {})
        snap = snapshot_for() if snapshot is None else snapshot
        for name, d in (('collector_heartbeat.json', hb), ('snapshot.json', snap)):
            with open(os.path.join(out, name), 'w', encoding='utf-8') as f:
                json.dump(d, f)
        return out

    def test_w4_consistent_pair_is_healthy(self):
        self.assertEqual(collector.check(self.write_pair(), now=at(5)), [])

    def test_w4_fresh_heartbeat_with_empty_snapshot_fails(self):
        out = self.write_pair(snapshot={})
        self.assertEqual([a['type'] for a in collector.check(out, now=at(5))], ['snapshot_invalid'])

    def test_w4_old_snapshot_next_to_fresh_heartbeat_fails(self):
        out = self.write_pair(snapshot=snapshot_for(generated=-3600))
        alerts = collector.check(out, now=at(5))
        self.assertEqual([a['type'] for a in alerts], ['snapshot_invalid'])
        self.assertIn('heartbeat cycle', alerts[0]['detail'])

    def test_w4_snapshot_from_another_collector_run_fails(self):
        out = self.write_pair(snapshot=snapshot_for(pid=999))
        self.assertEqual([a['type'] for a in collector.check(out, now=at(5))], ['snapshot_invalid'])

    def test_w4_future_heartbeat_is_not_healthy(self):
        out = self.write_pair(heartbeat={'last_cycle_at': z(3600)}, snapshot=snapshot_for(generated=3600))
        self.assertIn('collector_clock', [a['type'] for a in collector.check(out, now=at(5))])

    def test_w4_alerts_of_a_good_snapshot_are_passed_on(self):
        out = self.write_pair(snapshot=snapshot_for(alerts=[{'type': 'device_idle', 'uuid': U1}]))
        self.assertEqual([a['type'] for a in collector.check(out, now=at(5))], ['device_idle'])

    def test_w5_impossible_calendar_date_is_invalid_and_isolated(self):
        bad = doc(updated_at='2026-99-99T00:00:00Z')
        self.assertTrue(status.validate(bad))
        good = doc(id='good-one', updated_at=z(0))
        snap, _, _ = collector.cycle(self.cfg, at(0), gpus(), [], [entry(bad, 'bad.json'), entry(good, 'good.json')], {})
        self.assertEqual([w['id'] for w in snap['workloads']], ['good-one'])
        self.assertEqual([i['file'] for i in snap['invalid']], ['bad.json'])

    def test_w5_a_document_that_slips_past_validation_still_cannot_stop_the_cycle(self):
        sneaky = {'file': 'sneaky.json', 'doc': doc(updated_at='2026-99-99T00:00:00Z'), 'problems': []}
        snap, _, _ = collector.cycle(self.cfg, at(0), gpus(), [], [sneaky], {})
        self.assertEqual([i['file'] for i in snap['invalid']], ['sneaky.json'])

    def test_w5_non_finite_numbers_are_invalid(self):
        self.assertTrue(status.validate(doc(heartbeat_interval_s=float('inf'))))
        self.assertTrue(status.validate(doc(progress={'done': float('nan'), 'total': 1})))

    def test_w5_duplicate_ids_are_diagnosed(self):
        status_dir = os.path.join(self.tmp, 'status')
        os.makedirs(status_dir)
        for n in ('a.json', 'b.json'):
            with open(os.path.join(status_dir, n), 'w', encoding='utf-8') as f:
                json.dump(doc(id='same', updated_at=z(0)), f)
        entries = collector.read_status_dir(status_dir)
        self.assertEqual([bool(e['problems']) for e in entries], [False, True])
        self.assertIn('duplicate id', entries[1]['problems'][0])

    def test_w5_future_heartbeat_is_flagged(self):
        snap, _, _ = collector.cycle(self.cfg, at(0), gpus(), [], [entry(doc(updated_at=z(3600)))], {})
        self.assertTrue(snap['workloads'][0]['future_heartbeat'])
        self.assertIn('workload_clock_skew', [a['type'] for a in snap['alerts']])


class ReviewTwoTests(unittest.TestCase):
    """independent review (M01 to M07): each probe is reproduced as known input and must now be refused or reported."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = self._t.name
        self.cfg = make_cfg(self.tmp)

    def tearDown(self):
        self._t.cleanup()

    def test_m01_output_with_no_valid_device_row_is_a_broken_source(self):
        devices, apps, problems = nvidia.parse_gpus('this is not a GPU row' + chr(10)), None, None
        with mock.patch.object(nvidia, 'run_csv', side_effect=['this is not a GPU row' + chr(10), '']):
            devices, apps, problems = nvidia.sample()
        self.assertIsNone(devices)
        self.assertTrue(problems)
        snap, _, _ = collector.cycle(self.cfg, at(0), devices, apps, [], {})
        self.assertIn('source_unavailable', [a['type'] for a in snap['alerts']])

    def test_m01_partial_malformed_rows_become_an_alert(self):
        os.makedirs(self.cfg.out_dir)
        os.makedirs(self.cfg.status_dir)
        good = '0, %s, fixture, 0, 1, 10, 40, 20' % U1 + chr(10)
        with mock.patch.object(nvidia, 'run_csv', side_effect=[good + 'garbage row' + chr(10), '']):
            snap, _, _ = collector.run_once(self.cfg, {}, True, at(0), now=at(0))
        self.assertIn('source_problem', [a['type'] for a in snap['alerts']])

    def test_m02_artifact_path_the_os_refuses_is_a_missing_artifact(self):
        d = doc(updated_at=z(0), artifacts=[chr(0)])
        self.assertEqual(status.validate(d), [])
        snap, _, _ = collector.cycle(self.cfg, at(0), [], [], [entry(d)], {})
        self.assertIsNone(snap['workloads'][0]['artifact_mtime'])

    def test_m02_huge_integer_is_invalid_not_a_crash(self):
        problems = status.validate(doc(heartbeat_interval_s=10 ** 400))
        self.assertTrue(problems)

    def test_m03_viewer_and_python_check_agree_on_the_same_cases(self):
        hb = {'pid': 111, 'started_at': z(-100), 'last_cycle_at': z(0), 'interval_s': 10}
        snap = snapshot_for(111, 0)
        cases = {
            'good': (hb, snap, 5),
            'no_heartbeat': (None, snap, 5),
            'future_heartbeat': (dict(hb, last_cycle_at=z(3600)), snapshot_for(111, 3600), 5),
            'stale_heartbeat': (hb, snap, 500),
            'malformed_time': (dict(hb, last_cycle_at='2026-99-99T00:00:00Z'), snap, 5),
            'infinite_interval': ('{"pid": 111, "started_at": "%s", "last_cycle_at": "%s", "interval_s": 1e999}' % (z(-100), z(0)), snap, 8640000),
            'empty_snapshot': (hb, {}, 5),
            'old_snapshot_fresh_heartbeat': (hb, snapshot_for(111, -3600), 5),
            'other_run_snapshot': (hb, snapshot_for(999, 0), 5),
            'future_snapshot': (hb, snapshot_for(111, 7200), 5),
            'no_snapshot': (hb, None, 5),
        }
        health_js = os.path.join(ROOT, 'mai_watch', 'viewer-health.js').replace(os.sep, '/')
        script = ("const h=require(%r);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const c=JSON.parse(s);"
                  "console.log(JSON.stringify(c.map(x=>h.health(x.hb,x.snap,x.now).map(p=>p.type).sort())))})" % health_js)
        payload = []
        for name, (h, s, now_s) in cases.items():
            h = json.loads(h) if isinstance(h, str) else h
            payload.append({'hb': h, 'snap': s, 'now': status.parse_time(z(now_s)).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000})
        raw = json.dumps(payload).replace('"interval_s": Infinity', '"interval_s": 1e999')
        p = subprocess.run(['node', '-e', script], input=raw, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        js_types = json.loads(p.stdout)
        for (name, (h, s, now_s)), got in zip(cases.items(), js_types):
            out = os.path.join(self.tmp, 'case-' + name)
            os.makedirs(out)
            if h is not None:
                with open(os.path.join(out, 'collector_heartbeat.json'), 'w', encoding='utf-8') as f:
                    f.write(h if isinstance(h, str) else json.dumps(h))
            if s is not None:
                with open(os.path.join(out, 'snapshot.json'), 'w', encoding='utf-8') as f:
                    json.dump(s, f)
            py = sorted(a['type'] for a in collector.check(out, now=at(now_s)))
            self.assertEqual(got, py, '%s: viewer says %s, check says %s' % (name, got, py))
        self.assertEqual(js_types[0], [], 'the good case must be healthy in both')
        self.assertTrue(all(t for t in js_types[1:]), 'every bad case must be reported by the viewer logic')

    def test_m04_a_disappeared_running_workload_is_reported_once_and_stays_an_alert(self):
        _, _, state = collector.cycle(self.cfg, at(0), [], [], [entry(doc(updated_at=z(0)))], {})
        snap, ev, state = collector.cycle(self.cfg, at(40), [], [], [], state)
        self.assertEqual([e['type'] for e in ev], ['workload_disappeared'])
        self.assertIn('workload_disappeared', [a['type'] for a in snap['alerts']])
        snap, ev, state = collector.cycle(self.cfg, at(80), [], [], [], state)
        self.assertEqual(ev, [])
        self.assertIn('workload_disappeared', [a['type'] for a in snap['alerts']])
        snap, ev, state = collector.cycle(self.cfg, at(120), [], [], [entry(doc(updated_at=z(120)))], state)
        self.assertIn('workload_reappeared', [e['type'] for e in ev])
        self.assertNotIn('workload_disappeared', [a['type'] for a in snap['alerts']])

    def test_m04_a_finished_job_whose_file_is_removed_is_not_an_alert(self):
        _, _, state = collector.cycle(self.cfg, at(0), [], [], [entry(doc(state='done', updated_at=z(0)))], {})
        snap, ev, _ = collector.cycle(self.cfg, at(40), [], [], [], state)
        self.assertEqual([e for e in ev if e['type'].startswith('workload_')], [])
        self.assertNotIn('workload_disappeared', [a['type'] for a in snap['alerts']])

    def test_m04_the_alert_expires_after_missing_alert_s(self):
        cfg = make_cfg(self.tmp, missing_alert_s=100)
        _, _, state = collector.cycle(cfg, at(0), [], [], [entry(doc(updated_at=z(0)))], {})
        _, _, state = collector.cycle(cfg, at(40), [], [], [], state)
        snap, _, _ = collector.cycle(cfg, at(500), [], [], [], state)
        self.assertNotIn('workload_disappeared', [a['type'] for a in snap['alerts']])

    def test_m05_a_new_run_of_the_same_id_does_not_inherit_old_progress(self):
        d1 = doc(updated_at=z(0), started_at=z(0), progress={'done': 1, 'total': 10})
        _, _, state = collector.cycle(self.cfg, at(0), [], [], [entry(d1)], {})
        d2 = doc(updated_at=z(10), started_at=z(10), progress={'done': 0, 'total': 10})
        snap, _, state = collector.cycle(self.cfg, at(10), [], [], [entry(d2)], state)
        self.assertIsNone(snap['workloads'][0]['first_progress_at'])
        d3 = doc(updated_at=z(20), started_at=z(10), progress={'done': 2, 'total': 10})
        snap, _, _ = collector.cycle(self.cfg, at(20), [], [], [entry(d3)], state)
        self.assertEqual(snap['workloads'][0]['first_progress_at'], z(20))

    def test_m06_an_infinite_heartbeat_interval_is_not_healthy(self):
        out = os.path.join(self.tmp, 'out')
        os.makedirs(out)
        with open(os.path.join(out, 'collector_heartbeat.json'), 'w', encoding='utf-8') as f:
            f.write('{"pid": 1, "started_at": "%s", "last_cycle_at": "%s", "interval_s": 1e999}' % (z(-100), z(0)))
        with open(os.path.join(out, 'snapshot.json'), 'w', encoding='utf-8') as f:
            json.dump(snapshot_for(1, 0), f)
        types = [a['type'] for a in collector.check(out, now=at(100 * 86400))]
        self.assertIn('collector_missing', types)

    def test_m07_a_failed_process_query_is_unknown_not_zero(self):
        good = '0, %s, fixture, 0, 1, 10, 40, 20' % U1 + chr(10)
        with mock.patch.object(nvidia, 'run_csv', side_effect=[good, None]):
            devices, apps, problems = nvidia.sample()
        self.assertEqual(len(devices), 1)
        self.assertIsNone(apps)
        self.assertTrue(any('process list is unknown' in p for p in problems))
        snap, _, _ = collector.cycle(self.cfg, at(0), devices, apps, [], {})
        self.assertFalse(snap['devices'][0]['processes_known'])

    def test_m07_an_empty_process_list_is_known_and_empty(self):
        good = '0, %s, fixture, 0, 1, 10, 40, 20' % U1 + chr(10)
        with mock.patch.object(nvidia, 'run_csv', side_effect=[good, '']):
            devices, apps, problems = nvidia.sample()
        self.assertEqual((apps, problems), ([], []))
        snap, _, _ = collector.cycle(self.cfg, at(0), devices, apps, [], {})
        self.assertTrue(snap['devices'][0]['processes_known'])

    def test_events_are_served_as_a_bounded_tail(self):
        from mai_watch import server
        import threading
        import urllib.request
        out = os.path.join(self.tmp, 'srv')
        os.makedirs(out)
        lines = [json.dumps({'at': z(i), 'type': 'x', 'n': i}) for i in range(20000)]
        with open(os.path.join(out, 'events.jsonl'), 'w', encoding='utf-8') as f:
            f.write(chr(10).join(lines) + chr(10))
        srv = server.make_server(out, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/events.jsonl' % srv.server_address[1], timeout=5) as r:
                body = r.read().decode('utf-8')
            with urllib.request.urlopen('http://127.0.0.1:%d/viewer-health.js' % srv.server_address[1], timeout=5) as r:
                js_status, js_body = r.status, r.read().decode('utf-8')
        finally:
            srv.shutdown()
            srv.server_close()
        served = body.splitlines()
        self.assertLessEqual(len(body.encode('utf-8')), server.TAIL_BYTES)
        self.assertEqual(json.loads(served[-1])['n'], 19999)
        for line in served:
            json.loads(line)          # no cut line at the start
        self.assertEqual(js_status, 200)
        self.assertIn('MaiWatchHealth', js_body)


class ViewerPageTests(unittest.TestCase):
    """The real inline script of viewer.html, run against a small fake DOM (finding G1: a snapshot of the wrong shape must not hide the real heartbeat)."""

    def run_cases(self, cases):
        p = subprocess.run(['node', os.path.join(ROOT, 'tests', 'viewer_harness.js')], input=json.dumps(cases), capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def cases(self):
        now = datetime.datetime(2026, 10, 18, 5, 0, 0, tzinfo=datetime.timezone.utc)
        iso = lambda sec: (now + datetime.timedelta(seconds=sec)).strftime('%Y-%m-%dT%H:%M:%SZ')
        now_ms = now.timestamp() * 1000
        hb = {'pid': 111, 'started_at': iso(-100), 'last_cycle_at': iso(-2), 'interval_s': 10}
        cfg = make_cfg(tempfile.mkdtemp())
        snap, _, _ = collector.cycle(cfg, at(0), gpus(), [], [entry(doc(updated_at=z(0)))], {})
        snap = dict(snap, generated_at=iso(-2), collector={'pid': 111, 'started_at': iso(-100)})
        no_devices = {k: v for k, v in snap.items() if k != 'devices'}
        base = {'hb': hb, 'now_ms': now_ms}
        return {
            'good': dict(base, snapshot=snap),
            'empty_object': dict(base, snapshot={}),
            'missing_devices': dict(base, snapshot=no_devices),
            'not_json': dict(base, snapshot='this is not json'),
            'http_500': dict(base, snapshot={}, snapshot_status=500),
            'no_heartbeat_wrong_shape': dict(base, hb=None, snapshot={}),
        }

    def test_each_failure_is_named_for_what_it_is_and_the_heartbeat_is_kept(self):
        cases = self.cases()
        got = dict(zip(cases.keys(), self.run_cases(list(cases.values()))))
        g = got['good']
        self.assertFalse(g['error_shown'])
        self.assertIn('collector alive', g['pill'])
        self.assertEqual(g['device_rows'], 2)
        for name in ('empty_object', 'missing_devices'):
            r = got[name]
            self.assertTrue(r['error_shown'], name)
            self.assertIn('wrong structure', r['error'], name)
            self.assertNotIn('Cannot read', r['error'], name)
            self.assertNotIn('file://', r['error'], name)
            self.assertNotIn('collector_missing', r['pill'], name)      # the real heartbeat is not thrown away
            self.assertNotIn('snapshot_missing', r['pill'], name)
            self.assertIn('snapshot_invalid', r['pill'], name)
            self.assertIn('bad', r['pill_class'], name)
            self.assertEqual(r['device_rows'], 0, name)
        self.assertIn('not valid JSON', got['not_json']['error'])
        self.assertIn('Cannot read snapshot.json', got['http_500']['error'])
        self.assertIn('500', got['http_500']['error'])
        self.assertIn('collector_missing', got['no_heartbeat_wrong_shape']['pill'])
        self.assertIn('wrong structure', got['no_heartbeat_wrong_shape']['error'])


class RuntimeValidatorAgreement(unittest.TestCase):
    def test_runtime_validator_agrees_with_json_schema_on_every_example(self):
        sch = readj(os.path.join(ROOT, 'schema', 'status.v1.schema.json'))
        v = Draft202012Validator(sch)
        names = sorted(n for n in os.listdir(EXAMPLES) if n.endswith('.json'))
        self.assertGreaterEqual(len(names), 14)
        for n in names:
            d = readj(os.path.join(EXAMPLES, n))
            schema_ok = not list(v.iter_errors(d))
            runtime_ok = status.validate(d) == []
            if n.startswith('semantic-'):
                self.assertTrue(schema_ok and not runtime_ok, '%s: the shape is fine but the runtime must reject it' % n)
                continue
            self.assertEqual(schema_ok, runtime_ok, '%s: schema says %s, runtime says %s %s' % (n, schema_ok, runtime_ok, status.validate(d)))
            self.assertEqual(schema_ok, n.startswith('valid-'), n)


MUTATIONS = [
    ('idle ignores running workloads', idle, 'condition', lambda avg, thr, running: avg is not None and avg < thr, [IdleTests, CollectorTests]),
    ('staleness never triggers', status, 'is_stale', lambda now, u, i, f: False, [CollectorTests]),
    ('N/A parsed as 0', nvidia, 'num', lambda f: float(f) if (f or '').strip().replace('.', '', 1).isdigit() else 0, [ParserTests]),
    ('runtime validator accepts everything', status, 'validate', lambda d: [], [RuntimeValidatorAgreement]),
    ('gap check ignored', idle.IdleTracker, '__init__', (lambda orig: (lambda self, window_s=600, threshold_pct=5, min_s=600, resume_s=60, max_gap_s=None: orig(self, window_s, threshold_pct, min_s, resume_s, None)))(idle.IdleTracker.__init__), [IdleObservationTests]),
    ('check trusts a fresh heartbeat alone', collector, 'check', lambda out_dir, now=None, ignore=(): [], [SourceAndCheckTests]),
    ('artifact path error crashes the cycle', collector, 'artifact_mtime', lambda paths: (_ for _ in ()).throw(ValueError('embedded null byte')) if any(chr(0) in p for p in paths) else None, [ReviewTwoTests]),
    ('malformed GPU output counts as an empty source', nvidia, 'parse_gpus', lambda text: ([], []), [ReviewTwoTests]),
    ('unavailable utilization counts as idle', idle, 'condition', lambda avg, thr, running: (avg is None or avg < thr) and not running, [IdleTests]),
]


class MutationTests(unittest.TestCase):
    def test_each_broken_rule_makes_its_suite_fail(self):
        for label, module, attr, replacement, suites in MUTATIONS:
            with self.subTest(label):
                with mock.patch.object(module, attr, replacement):
                    loader = unittest.TestLoader()
                    failed = False
                    for s in suites:
                        res = unittest.TextTestRunner(stream=io.StringIO()).run(loader.loadTestsFromTestCase(s))
                        failed = failed or not res.wasSuccessful()
                self.assertTrue(failed, 'the suites still pass with the rule broken: %s' % label)

    def test_resume_hysteresis_mutation(self):
        original = idle.IdleTracker.__init__

        def broken(self, window_s=600, threshold_pct=5, min_s=600, resume_s=60):
            original(self, window_s, threshold_pct, min_s, 0)
        with mock.patch.object(idle.IdleTracker, '__init__', broken):
            res = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestLoader().loadTestsFromTestCase(IdleTests))
        self.assertFalse(res.wasSuccessful(), 'hysteresis removed but IdleTests still pass')


if __name__ == '__main__':
    unittest.main(verbosity=2)
