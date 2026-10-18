"""Known-answer tests for the judgment list (DESIGN.md section 9f) and disk names. Run: python -I tests/test_judge.py
Each input is written here with the answer it must give, including the cases where a rule must stay silent for lack of data."""
import json
import os
import sys
import threading
import unittest
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from mai_watch import disks, judge, live, server  # noqa: E402


def sample(t, gpus=None, nics=None, ram=40.0, problems=None):
    return {'t': '2026-10-18T12:%02d:%02d.00Z' % (t // 60, t % 60), 'ram_pct': ram, 'gpus': gpus, 'nics': nics, 'problems': problems or []}


def gpu(util, vram, throttle=None, temp=50, uuid='GPU-a'):
    return {'index': 0, 'uuid': uuid, 'util_pct': util, 'vram_used_mib': vram, 'vram_total_mib': 16303, 'temperature_c': temp,
            'throttle': throttle if throttle is not None else [], 'sm_clock_mhz': 2800, 'power_w': 100}


def kinds(found):
    return sorted((f['level'], f['kind'], f['subject']) for f in found)


class PathRules(unittest.TestCase):
    def test_free_space_levels_and_unreachable(self):
        slow = {'paths': [
            {'path': 'H:\\', 'label': 'H: disk', 'state': 'ok', 'free_gib': 7.4, 'used_pct': 99.9},
            {'path': 'D:\\', 'state': 'ok', 'free_gib': 37.0, 'used_pct': 99.0},
            {'path': 'G:\\', 'state': 'ok', 'free_gib': 680.0, 'used_pct': 90.9},
            {'path': 'I:\\', 'state': 'ok', 'free_gib': 155.0, 'used_pct': 97.9},
            {'path': '//nas/x', 'state': 'no answer', 'free_gib': None, 'used_pct': None},
            {'path': 'X:\\', 'state': 'not checked yet', 'free_gib': None, 'used_pct': None}]}
        self.assertEqual(kinds(judge.judge([], slow)), [
            ('bad', 'disk_space', 'H: disk'), ('bad', 'path_unreachable', '//nas/x'),
            ('warn', 'disk_space', 'D:\\'), ('warn', 'disk_space', 'I:\\')])           # G: is fine; not checked yet says nothing


class NetworkRules(unittest.TestCase):
    def test_slow_wired_link_only(self):
        last = sample(0, nics=[{'nic': 'Ethernet 2', 'link_mbps': 100}, {'nic': 'eth0', 'link_mbps': 10000},
                               {'nic': 'Wi-Fi', 'link_mbps': 54}, {'nic': 'Tailscale', 'link_mbps': None}])
        self.assertEqual(kinds(judge.judge([last], {})), [('warn', 'slow_link', 'Ethernet 2')])


class GpuRules(unittest.TestCase):
    def test_limit_reasons_but_not_idle_clocks(self):
        s = [sample(0, gpus=[gpu(90, 9000, ['sw_power_cap']), gpu(0, 0, ['gpu_idle'], uuid='GPU-b')])]
        self.assertEqual(kinds(judge.judge(s, {})), [('warn', 'gpu_clock_limited', 'GPU 0')])

    def test_hot(self):
        self.assertEqual(kinds(judge.judge([sample(0, gpus=[gpu(90, 9000, temp=88)])], {})), [('warn', 'gpu_hot', 'GPU 0')])

    def test_vram_held_while_idle_for_the_whole_window(self):
        s = [sample(t, gpus=[gpu(2, 12000)]) for t in range(0, 301, 10)]
        f = [x for x in judge.judge(s, {}) if x['kind'] == 'gpu_vram_idle']
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]['evidence']['span_s'], f[0]['evidence']['max_util_pct'], f[0]['evidence']['vram_mib']), (300, 2, 12000))

    def test_vram_idle_needs_the_window_covered_and_every_sample_low(self):
        short = [sample(t, gpus=[gpu(2, 12000)]) for t in range(0, 200, 10)]                  # 190 s of a 300 s window
        busy = [sample(t, gpus=[gpu(2 if t != 150 else 40, 12000)]) for t in range(0, 301, 10)]  # one busy sample
        unknown = [sample(t, gpus=[gpu(2 if t != 150 else None, 12000)]) for t in range(0, 301, 10)]
        small = [sample(t, gpus=[gpu(2, 500)]) for t in range(0, 301, 10)]                     # little memory held
        for name, s in (('short', short), ('busy', busy), ('unknown', unknown), ('small', small)):
            self.assertEqual([x for x in judge.judge(s, {}) if x['kind'] == 'gpu_vram_idle'], [], name)


class HostAndUsageRules(unittest.TestCase):
    def test_ram_and_plan_limits_and_order(self):
        slow = {'usage': {'limits': [{'engine': 'claude', 'five_hour': {'pct': 96}, 'seven_day': {'pct': 81}},
                                     {'engine': 'codex', 'five_hour': None, 'seven_day': {'pct': None}}],
                          'problems': ['refused session file: x']}}
        found = judge.judge([sample(0, ram=93, problems=['nvidia-smi unavailable'])], slow)
        self.assertEqual([f['level'] for f in found], sorted([f['level'] for f in found], key=lambda l: judge.ORDER[l]))
        self.assertEqual(kinds(found), [('bad', 'plan_limit', 'claude 5-hour'), ('info', 'source_problem', 'sampler'),
                                        ('info', 'usage_source', 'usage'), ('warn', 'plan_limit', 'claude 7-day'), ('warn', 'ram_high', 'RAM')])

    def test_nothing_known_says_nothing(self):
        self.assertEqual(judge.judge([], {}), [])

    def test_thresholds_can_be_changed(self):
        slow = {'paths': [{'path': 'C:\\', 'state': 'ok', 'free_gib': 592.0, 'used_pct': 68.2}]}
        self.assertEqual(len(judge.judge([], slow, {'free_gib_warn': 1000})), 1)


class DiskNames(unittest.TestCase):
    def test_windows_and_lsblk_parsing(self):
        win = json.dumps([{'n': 5, 'model': 'WD_BLACK SN850X 4000GB', 'size': 1, 'letters': ['D:']}, {'n': 4, 'model': 'Samsung 990', 'letters': []}])
        m = disks.parse_windows(win)
        self.assertEqual(m['PhysicalDrive5'], {'model': 'WD_BLACK SN850X 4000GB', 'places': ['D:']})
        self.assertEqual(disks.label_for_place('D:\\', m), 'WD_BLACK SN850X 4000GB')
        self.assertIsNone(disks.label_for_place('Q:\\', m))
        self.assertEqual(disks.parse_windows(json.dumps({'n': 0, 'model': 'One', 'letters': 'E:'})), {'PhysicalDrive0': {'model': 'One', 'places': ['E:']}})
        lsblk = json.dumps({'blockdevices': [{'name': 'nvme0n1', 'model': 'Samsung 990 ', 'type': 'disk', 'mountpoints': [None],
                                              'children': [{'name': 'nvme0n1p2', 'type': 'part', 'mountpoints': ['/']}]},
                                             {'name': 'loop0', 'type': 'loop', 'mountpoints': ['/snap/x']}]})
        self.assertEqual(disks.parse_lsblk(lsblk), {'nvme0n1': {'model': 'Samsung 990', 'places': ['/']}})
        self.assertEqual(disks.parse_windows('not json'), {})

    def test_path_label_uses_the_disk_name(self):
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: '', paths=['D:\\'], usage_on=False,
                             disk_reader=lambda: {'PhysicalDrive5': {'model': 'WD_BLACK', 'places': ['D:']}})
        s.load_disks()
        self.assertEqual(s.payload()['slow']['paths'][0]['label'], 'D: WD_BLACK')


class StatusEndpoint(unittest.TestCase):
    def test_status_json_carries_counts_and_evidence(self):
        s = live.LiveSampler(psutil_module=False, gpu_reader=lambda: '', paths=['.'], usage_on=False, disk_reader=lambda: {})
        s.sample_once()
        srv = server.make_server(None, 0, live=s)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with urllib.request.urlopen('http://127.0.0.1:%d/status.json' % srv.server_address[1], timeout=5) as r:
            d = json.loads(r.read())
        self.assertEqual(d['schema'], 'mai-watch-status-v1')
        self.assertEqual(d['counts']['info'], len([j for j in d['judgments'] if j['level'] == 'info']))
        self.assertTrue(any(j['kind'] == 'source_problem' and 'psutil' in j['text'] for j in d['judgments']))
        self.assertTrue(all('evidence' in j for j in d['judgments']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
