"""Known-answer tests for the live view (DESIGN.md section 9c). Run: python -I tests/test_live.py
Inputs are fixed: a fake psutil with chosen numbers and a fixed nvidia-smi text, so every expected value is written here, not computed by the code."""
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from mai_watch import live, server  # noqa: E402

GIB = 2 ** 30
GPU_TEXT = ('0, GPU-aaaaaaaa-0000-0000-0000-000000000001, RTX A, 37, 9714, 16303, 52, 98.25\n'
            '1, GPU-bbbbbbbb-0000-0000-0000-000000000002, RTX B, [N/A], 11235, 16303, 60, [N/A]\n')


class FakeMem:
    def __init__(self, total, available, percent, used=0):
        self.total, self.available, self.percent, self.used = total, available, percent, used


class FakePsutil:
    def __init__(self):
        self.calls = 0

    def cpu_count(self, logical=True):
        return 4

    def cpu_percent(self, interval=None, percpu=False):
        self.calls += 1
        return [10.0, 20.0, 30.0, 40.0]

    def virtual_memory(self):
        return FakeMem(total=64 * GIB, available=48 * GIB, percent=25.0)

    def swap_memory(self):
        return FakeMem(total=8 * GIB, available=0, percent=12.5, used=1 * GIB)


class Clock:
    def __init__(self, t=1800000000.0):
        self.t = t

    def __call__(self):
        return self.t


def sampler(gpu_text=GPU_TEXT, ps='fake', **kw):
    return live.LiveSampler(psutil_module=FakePsutil() if ps == 'fake' else ps, gpu_reader=lambda: gpu_text, clock=kw.pop('clock', Clock()), **kw)


class SamplerTests(unittest.TestCase):
    def test_ram_process_view_is_sorted_and_capped_at_five(self):
        class Proc:
            def __init__(self, pid, rss): self.info = {'pid': pid, 'name': 'worker%d.exe' % pid, 'memory_info': type('Mem', (), {'rss': rss})()}
        class Ps:
            def process_iter(self, attrs): return [Proc(i, i * 2 ** 20) for i in range(1, 8)]
        rows = live.LiveSampler._ram_processes(Ps())
        self.assertEqual([(x['pid'], x['rss_mib']) for x in rows], [(7, 7.0), (6, 6.0), (5, 5.0), (4, 4.0), (3, 3.0)])

    def test_gpu_processes_are_grouped_per_gpu_with_memory_and_safe_run_name(self):
        s = sampler()
        s._apps_reader = lambda: ('GPU-aaaaaaaa-0000-0000-0000-000000000001, 42, python.exe, 2048\n'
                                  'GPU-bbbbbbbb-0000-0000-0000-000000000002, 43, trainer.exe, [N/A]\n')
        class Proc:
            def __init__(self, pid): self.pid = pid
            def create_time(self): return 1799999900
            def cmdline(self): return ['python', '--run_name', 'terrain trial']
        s._ps().Process = Proc
        sample = s.sample_once()
        p0 = sample['gpus'][0]['processes'][0]
        self.assertEqual((p0['pid'], p0['process'], p0['run_name'], p0['elapsed_s'], p0['vram_mib']),
                         (42, 'python.exe', 'terrain_trial', 100, 2048))
        self.assertEqual(sample['gpus'][1]['processes'][0]['vram_mib'], None)

    def test_failed_compute_apps_query_is_unknown_not_an_empty_process_list(self):
        s = sampler()
        s._apps_reader = lambda: None
        sample = s.sample_once()
        self.assertIsNone(sample['gpus'][0]['processes'])
        self.assertTrue(any('per-process GPU use is unknown' in x for x in sample['problems']))

    def test_first_cpu_reading_is_unknown_then_the_average_of_cores(self):
        s = sampler()
        first = s.sample_once()
        self.assertIsNone(first['cpu_pct'])            # psutil's first call only opens the window and returns 0; 0 would be a lie
        self.assertIsNone(first['cpu_per_core'])
        second = s.sample_once()
        self.assertEqual(second['cpu_pct'], 25.0)
        self.assertEqual(second['cpu_per_core'], [10.0, 20.0, 30.0, 40.0])

    def test_ram_used_is_total_minus_available_and_swap_is_reported(self):
        x = sampler().sample_once()
        self.assertEqual((x['ram_used_gib'], x['ram_total_gib'], x['ram_pct']), (16.0, 64.0, 25.0))
        self.assertEqual((x['swap_used_gib'], x['swap_total_gib']), (1.0, 8.0))

    def test_gpu_and_vram_values_and_unknowns(self):
        g = sampler().sample_once()['gpus']
        self.assertEqual([(d['index'], d['util_pct'], d['vram_used_mib'], d['vram_total_mib'], d['temperature_c'], d['power_w']) for d in g],
                         [(0, 37, 9714, 16303, 52, 98.25), (1, None, 11235, 16303, 60, None)])

    def test_missing_sources_are_unknown_with_a_reason_never_zero(self):
        x = sampler(gpu_text=None, ps=False).sample_once()
        self.assertIsNone(x['gpus'])
        self.assertIsNone(x['cpu_pct'])
        self.assertIsNone(x['ram_pct'])
        self.assertTrue(any('psutil' in p for p in x['problems']))
        self.assertTrue(any('nvidia-smi' in p for p in x['problems']))

    def test_output_with_no_valid_gpu_row_is_unknown(self):
        x = sampler(gpu_text='garbage\n').sample_once()
        self.assertIsNone(x['gpus'])
        self.assertTrue(any('no valid device row' in p for p in x['problems']))

    def test_history_keeps_only_the_window_and_since_returns_newer_samples(self):
        c = Clock()
        s = sampler(interval_s=1, history_s=5, clock=c)
        for i in range(8):
            c.t = 1800000000.0 + i
            s.sample_once()
        p = s.payload()
        self.assertEqual(len(p['samples']), 5)
        self.assertEqual(p['schema'], 'mai-watch-live-v1')
        newer = s.payload(since=p['samples'][2]['t'])['samples']
        self.assertEqual([x['t'] for x in newer], [x['t'] for x in p['samples'][3:]])

    def test_bad_interval_or_history_is_refused(self):
        for kw in ({'interval_s': 0}, {'interval_s': 0.1}, {'interval_s': 61}, {'interval_s': 5, 'history_s': 2}, {'history_s': 10 ** 6}):
            with self.assertRaises(ValueError, msg=kw):
                sampler(**kw)

    def test_run_stops_when_asked(self):
        s = sampler(interval_s=0.2, history_s=10)
        stop = threading.Event()
        t = threading.Thread(target=s.run, args=(stop,))
        t.start()
        stop.wait(0.7)
        stop.set()
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertGreaterEqual(len(s.payload()['samples']), 2)


class ServerTests(unittest.TestCase):
    def serve(self, live_sampler):
        srv = server.make_server(None, 0, live=live_sampler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return 'http://127.0.0.1:%d' % srv.server_address[1]

    def get(self, url):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_live_json_is_served_with_since(self):
        c = Clock()
        s = sampler(clock=c)
        for i in range(3):
            c.t += 1
            s.sample_once()
        base = self.serve(s)
        code, body = self.get(base + '/live.json')
        d = json.loads(body)
        self.assertEqual((code, d['schema'], len(d['samples'])), (200, 'mai-watch-live-v1', 3))
        code, body = self.get(base + '/live.json?since=' + urllib.request.quote(d['samples'][0]['t']))
        self.assertEqual(len(json.loads(body)['samples']), 2)
        self.assertEqual(self.get(base + '/viewer-live.js')[0], 200)

    def test_without_a_sampler_live_json_is_404_and_output_files_are_not_read(self):
        base = self.serve(None)
        self.assertEqual(self.get(base + '/live.json')[0], 404)
        self.assertEqual(self.get(base + '/snapshot.json')[0], 404)
        self.assertEqual(self.get(base + '/')[0], 200)

    def test_pwa_manifest_and_icon_are_served_as_package_assets(self):
        base = self.serve(None)
        code, manifest = self.get(base + '/manifest.webmanifest')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(manifest)['short_name'], 'mai-watch')
        self.assertEqual(self.get(base + '/viewer-icon.svg')[0], 200)


class SparkTests(unittest.TestCase):
    def test_points_place_time_on_x_value_on_y_and_break_at_unknowns(self):
        js = os.path.join(ROOT, 'mai_watch', 'viewer-live.js').replace(os.sep, '/')
        script = ("const m=require(%r);"
                  "console.log(JSON.stringify(m.sparkPoints([0,30000,60000,90000,120000],[0,50,null,100,150],120000,120,100,300,48)))") % js
        p = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        # x = 300 - age/120*300; y = 48 - clamp(v)/100*48; null breaks the line; 150 is clamped to the top
        self.assertEqual(json.loads(p.stdout), ['0.0,48.0 75.0,24.0', '225.0,0.0 300.0,0.0'])


class LimitLabelTests(unittest.TestCase):
    def test_old_reading_is_grey_and_says_old_fresh_high_is_hot(self):
        js = os.path.join(ROOT, 'mai_watch', 'viewer-live.js').replace(os.sep, '/')
        script = ("const m=require(%r);"
                  "console.log(JSON.stringify([m.limitLabel(86,36000),m.limitLabel(86,60),m.limitLabel(40,60),m.limitLabel(86,null),m.limitLabel(null,60)]))") % js
        p = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        old, hot, calm, noage, unknown = json.loads(p.stdout)
        self.assertEqual(old['cls'], 'off')                   # 10/20: codex 86 % from 09:52 shown hot after an early reset
        self.assertIn('old reading (10.0 h ago)', old['text'])
        self.assertEqual((hot['cls'], hot['text']), ('hot', '86%'))
        self.assertEqual((calm['cls'], calm['text']), ('', '40%'))
        self.assertEqual(noage['cls'], 'off')
        self.assertEqual(unknown['text'], 'unknown')


class CliTests(unittest.TestCase):
    def test_live_command_exists_and_refuses_a_bad_interval(self):
        env = dict(os.environ)
        p = subprocess.run([sys.executable, '-m', 'mai_watch', 'live', '--interval', '0', '--port', '0'], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', timeout=30, env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn('interval_s must be between', p.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
