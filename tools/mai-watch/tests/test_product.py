"""Known-answer resource attribution and private diagnostics."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mai_watch import product
from mai_watch.live import LiveSampler
from mai_watch import server
import threading
import urllib.request
import subprocess
import time


def proc(pid, born, cpu, name='worker'):
    return NS(info={'pid': pid, 'create_time': born, 'name': name,
                    'cpu_times': NS(user=cpu, system=0)})


class ProductTests(unittest.TestCase):
    def test_overlapping_background_scans_do_not_overwrite_psutil_info(self):
        cpu_yielded, ram_entered = threading.Event(), threading.Event()
        p = proc(1, 1, 2)
        class Ps:
            def process_iter(self, attrs):
                if 'cpu_times' in attrs:
                    p.info = dict(proc(1, 1, 2).info)
                    cpu_yielded.set()
                    yield p
                    ram_entered.wait(1)
                else:
                    ram_entered.set()
                    p.info = {'pid': 1, 'name': 'worker', 'memory_info': NS(rss=1024 ** 2)}
                    yield p
        s = LiveSampler(psutil_module=False, gpu_reader=lambda: None)
        s._cpu_counter.previous, s._cpu_counter.at = {(1, 1.0): 0}, time.monotonic() - 1
        s._cpu_top(Ps()); self.assertTrue(cpu_yielded.wait(2)); s._ram_top(Ps())
        end = time.monotonic() + 4
        while (s._cpu_busy or s._ram_busy) and time.monotonic() < end:
            time.sleep(0.01)
        self.assertFalse(s._cpu_busy or s._ram_busy)
        self.assertIsNotNone(s._cpu_cache)
        self.assertEqual(s._cpu_cache[0]['process'], 'worker')
        self.assertEqual(s._ram_cache[0]['rss_mib'], 1)

    def test_warning_expansion_survives_real_renderer_redraw(self):
        p = subprocess.run(['node', str(Path(__file__).with_name('live_view_harness.js'))],
                           input=json.dumps({'open_warning': True}), capture_output=True, text=True, check=True)
        warnings = [n for n in json.loads(p.stdout) if 'warning-evidence' in n['cls']]
        self.assertTrue(warnings[0]['open'])

    def test_actual_renderer_cpu_diagnostics_and_incidents(self):
        fixture = {'cpu_processes': [{'pid': 17, 'process': 'worker', 'cpu_pct': 125.0}],
                   'diagnostics': {'checks': [{'source': 'gpu', 'state': 'unknown', 'reason': 'driver unavailable', 'next_check': 'Check driver'}]},
                   'incidents': [{'text': 'hot earlier', 'state': 'cleared', 'last_seen': 0}]}
        p = subprocess.run(['node', str(Path(__file__).with_name('live_view_harness.js'))],
                           input=json.dumps(fixture), capture_output=True, text=True, check=True)
        text = ' '.join(n['text'] for n in json.loads(p.stdout))
        self.assertIn('125.0', text)
        self.assertIn('driver unavailable', text)
        self.assertIn('hot earlier', text)

    def test_sampler_diagnostics_and_http_export_are_real_allowlist(self):
        clock = [1800000000.0]
        s = LiveSampler(psutil_module=False, gpu_reader=lambda: None, paths=['PRIVATE_SENTINEL'], clock=lambda: clock[0])
        s.sample_once()
        d = s.diagnostics()
        self.assertEqual(d['schema'], 'mai-watch-diagnostic-v1')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(d))
        srv = server.make_server(None, port=0, live=s)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/diagnostic.json' % srv.server_port) as r:
                self.assertEqual(json.load(r), d)
            clock[0] += 11
            with urllib.request.urlopen('http://127.0.0.1:%d/diagnostic.json' % srv.server_port) as r:
                self.assertFalse(json.load(r)['fresh'])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_sampler_incident_metadata_and_history(self):
        s = LiveSampler(psutil_module=False, gpu_reader=lambda: None)
        s.sample_once()
        p = s.payload()
        self.assertTrue(p['judgments'])
        self.assertIn('next_check', p['judgments'][0])
        self.assertEqual(p['incident_retention']['limit'], 256)
        self.assertTrue(p['incidents'])

    def test_cpu_deltas_and_top_three(self):
        c = product.CpuProcesses()
        self.assertIsNone(c.update([proc(1, 1, 10)], 10))
        rows = c.update([proc(1, 1, 11), proc(2, 1, 8)], 12)
        self.assertEqual(rows, [{'pid': 1, 'process': 'worker', 'cpu_pct': 50.0}])
        rows = c.update([proc(i, 1, 12 + i) for i in range(1, 6)], 14)
        self.assertEqual([(r['pid'], r['cpu_pct']) for r in rows], [(2, 300.0), (1, 100.0)])

    def test_cpu_reuse_reset_and_paths(self):
        c = product.CpuProcesses()
        c.update([proc(1, 1, 10)], 10)
        self.assertIsNone(c.update([proc(1, 2, 20)], 12))
        self.assertIsNone(c.update([proc(1, 2, 19)], 14))
        self.assertEqual(c.update([proc(1, 2, 23, 'C:\\private\\train.exe')], 16)[0]['process'], 'train.exe')
        self.assertIsNone(c.update([], 15))

    def test_cpu_ranking_is_bounded_and_missing_scan_is_unknown(self):
        c = product.CpuProcesses()
        c.update([proc(i, 1, 0) for i in range(1, 8)], 0)
        rows = c.update([proc(i, 1, i) for i in range(1, 8)], 1)
        self.assertEqual([r['pid'] for r in rows], [7, 6, 5])
        self.assertIsNone(c.update([], 2))

    def test_sample_storage_has_an_absolute_cap(self):
        s = LiveSampler(psutil_module=False, interval_s=0.2, history_s=86400, gpu_reader=lambda: None)
        self.assertEqual(s.samples.maxlen, 36000)

    def test_export_allowlist_discards_all_identity_and_unknown_is_null(self):
        secret = 'PRIVATE_SENTINEL'
        sample = {'t': '2026-10-23T00:00:00Z', 'cpu_pct': None, 'ram_pct': 0,
                  'cpu_processes': [{'process': secret}], 'gpus': [{'index': 0, 'uuid': secret, 'name': secret,
                   'util_pct': 0, 'temperature_c': None}], 'problems': [secret]}
        result = product.diagnostic(sample, {'available': False, 'reason': secret}, {'paths': [{'path': secret}]}, True)
        self.assertNotIn(secret, json.dumps(result))
        self.assertIsNone(result['metrics']['cpu_pct'])
        self.assertEqual(result['metrics']['ram_pct'], 0)
        self.assertTrue(result['checks'])
        self.assertTrue(all('next_check' in x and 'reason' in x for x in result['checks']))

    def test_incident_unknown_does_not_clear_and_gap_resets_duration(self):
        h = product.Incidents()
        f = {'kind': 'gpu_hot', 'subject': 'GPU 0', 'level': 'warn', 'text': 'hot', 'evidence': {'temperature_c': 90}}
        h.update([f], ['gpu_hot|GPU 0'], 0, 1)
        h.update([f], ['gpu_hot|GPU 0'], 1, 1)
        self.assertEqual(h.decorate([f], 1)[0]['observed_s'], 1)
        h.update([], [], 2, 1)
        self.assertEqual(len(h.rows(2)), 1)
        self.assertEqual(h.rows(2)[0]['state'], 'unknown')
        h.update([f], ['gpu_hot|GPU 0'], 100, 1)
        self.assertEqual(h.decorate([f], 100)[0]['observed_s'], 0)
        h.update([], ['gpu_hot|GPU 0'], 101, 1)
        self.assertEqual(h.rows(101)[0]['state'], 'cleared')

    def test_incident_retention_and_bound(self):
        h = product.Incidents(limit=3, retention_s=10)
        for i in range(5):
            f = {'kind': 'x', 'subject': str(i), 'level': 'warn', 'text': 'x'}
            h.update([f], ['x|' + str(i)], i, 1)
        self.assertLessEqual(len(h.rows(4)), 3)
        self.assertEqual(h.rows(100), [])

    def test_repeated_incident_keeps_previous_cleared_episode(self):
        h = product.Incidents(limit=3)
        f = {'kind': 'x', 'subject': 'a', 'text': 'x', 'level': 'warn'}
        for t in (0, 2, 4, 6):
            h.update([f], ['x|a'], t, 1)
            h.update([], ['x|a'], t + 1, 1)
        self.assertEqual(len(h.rows(7)), 3)
        self.assertTrue(all(x['state'] == 'cleared' for x in h.rows(7)))

    def test_real_sampler_idle_window_missing_value_does_not_clear(self):
        clock = [1800000000.0]
        util = ['0']
        s = LiveSampler(psutil_module=False, clock=lambda: clock[0], thresholds={'idle_window_s': 1, 'idle_coverage': 1},
                        gpu_reader=lambda: '0, GPU-a, Example, %s, 2048, 16384, 40, 50\n' % util[0])
        s._apps_reader = lambda: ''
        for t in range(2):
            clock[0] = 1800000000.0 + t
            s.sample_once()
        item = lambda: next(x for x in s.payload()['incidents'] if x['kind'] == 'gpu_vram_idle')
        self.assertEqual(item()['state'], 'active')
        util[0] = '[N/A]'; clock[0] += 1; s.sample_once()
        self.assertEqual(item()['state'], 'unknown')
        util[0] = '0'; clock[0] += 1; s.sample_once()
        self.assertEqual(item()['state'], 'unknown')
        util[0] = '50'; clock[0] += 1; s.sample_once()
        self.assertEqual(item()['state'], 'cleared')


if __name__ == '__main__':
    unittest.main()
