"""Live resource view (DESIGN.md section 9c): CPU, RAM, GPU and VRAM sampled about once a second, kept in memory for a short history.

Read-only. A value the source could not give stays None and is shown as unknown, never as 0. Nothing here is written to disk: the live
history is for watching; the workload and idle record stays in snapshot.json and events.jsonl.
"""
import collections
import datetime
import threading
import time

from . import nvidia

LIVE_SCHEMA = 'mai-watch-live-v1'
LIVE_GPU_QUERY = 'index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw'


def _z(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:-4] + 'Z'


def _gib(n):
    return round(n / 2 ** 30, 2)


class LiveSampler:
    def __init__(self, nvidia_cmd=('nvidia-smi',), interval_s=1.0, history_s=600, clock=time.time, psutil_module=None, gpu_reader=None):
        if not (isinstance(interval_s, (int, float)) and 0.2 <= interval_s <= 60):
            raise ValueError('interval_s must be between 0.2 and 60 seconds')
        if not (isinstance(history_s, (int, float)) and interval_s <= history_s <= 24 * 3600):
            raise ValueError('history_s must be at least one interval and at most 24 h')
        self.nvidia_cmd = tuple(nvidia_cmd)
        self.interval_s = float(interval_s)
        self.history_s = float(history_s)
        self.clock = clock
        self.samples = collections.deque(maxlen=max(1, int(round(history_s / interval_s))))
        self.lock = threading.Lock()
        self._psutil = psutil_module
        self._gpu_reader = gpu_reader or (lambda: nvidia.run_csv(self.nvidia_cmd, 'query-gpu', LIVE_GPU_QUERY, timeout=5))
        self._primed = False
        self.host_info = self._host_info()

    def _ps(self):
        if self._psutil is None:
            try:
                import psutil
                self._psutil = psutil
            except ImportError:
                self._psutil = False
        return self._psutil or None

    def _host_info(self):
        ps = self._ps()
        if not ps:
            return {'available': False, 'reason': 'psutil is not installed'}
        try:
            return {'available': True, 'logical_cpus': ps.cpu_count(logical=True), 'ram_total_gib': _gib(ps.virtual_memory().total)}
        except Exception as e:
            return {'available': False, 'reason': type(e).__name__}

    def sample_once(self):
        """One sample. Every field the source cannot give is None, with the reason in problems."""
        now = self.clock()
        s = {'t': _z(now), 'cpu_pct': None, 'cpu_per_core': None, 'ram_used_gib': None, 'ram_total_gib': None, 'ram_pct': None,
             'swap_used_gib': None, 'swap_total_gib': None, 'gpus': None, 'problems': []}
        ps = self._ps()
        if ps:
            try:
                per = ps.cpu_percent(interval=None, percpu=True)
                if self._primed:                     # the first call only starts the measurement window and always returns 0
                    s['cpu_per_core'] = [round(x, 1) for x in per]
                    s['cpu_pct'] = round(sum(per) / len(per), 1) if per else None
                self._primed = True
                vm = ps.virtual_memory()
                s.update(ram_used_gib=_gib(vm.total - vm.available), ram_total_gib=_gib(vm.total), ram_pct=round(vm.percent, 1))
                sw = ps.swap_memory()
                s.update(swap_used_gib=_gib(sw.used), swap_total_gib=_gib(sw.total))
            except Exception as e:
                s['problems'].append('host metrics failed: %s' % type(e).__name__)
        else:
            s['problems'].append('psutil is not installed: CPU and RAM are unknown')
        text = self._gpu_reader()
        if text is None or not text.strip():
            s['problems'].append('nvidia-smi unavailable or returned nothing: GPU and VRAM are unknown')
        else:
            devices, problems = nvidia.parse_gpus(text)
            s['problems'] += problems
            if devices:
                s['gpus'] = [{'index': d['index'], 'name': d['name'], 'uuid': d['uuid'], 'util_pct': d['utilization_pct'],
                              'vram_used_mib': d['memory_used_mib'], 'vram_total_mib': d['memory_total_mib'],
                              'temperature_c': d['temperature_c'], 'power_w': d['power_w']} for d in devices]
            else:
                s['problems'].append('nvidia-smi returned no valid device row: GPU and VRAM are unknown')
        with self.lock:
            self.samples.append(s)
        return s

    def payload(self, since=None):
        with self.lock:
            items = list(self.samples)
        if since:
            items = [x for x in items if x['t'] > since]
        return {'schema': LIVE_SCHEMA, 'interval_s': self.interval_s, 'history_s': self.history_s, 'host': self.host_info,
                'generated_at': _z(self.clock()), 'samples': items}

    def run(self, stop, sleep=time.sleep):
        """Samples until stop is set. A slow source delays the next sample; samples are never invented to fill a gap."""
        while not stop.is_set():
            started = time.monotonic()
            self.sample_once()
            rest = self.interval_s - (time.monotonic() - started)
            if rest > 0:
                stop.wait(rest)
