"""Live resource view (DESIGN.md sections 9c to 9e): CPU, RAM, GPU, VRAM, disk I/O and network sampled about once a second and kept
in memory for a short history; watched paths and AI session usage are read every slow_interval_s.

Read-only. A value the source could not give stays None and is shown as unknown, never as 0. Nothing here is written to disk: the live
history is for watching; the workload and idle record stays in snapshot.json and events.jsonl.
"""
import collections
import datetime
import threading
import time

from . import host, nvidia, usage

LIVE_SCHEMA = 'mai-watch-live-v1'
LIVE_GPU_QUERY = 'index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw'
# asked in the same call when the driver supports them; one unsupported field fails the whole call, so on failure the core query is used
EXTRA_FIELDS = ('clocks.sm', 'clocks.max.sm', 'clocks.mem', 'clocks_throttle_reasons.active', 'power.limit', 'fan.speed', 'utilization.memory',
                'pcie.link.gen.current', 'pcie.link.width.current')
EXTRA_KEYS = ('sm_clock_mhz', 'sm_clock_max_mhz', 'mem_clock_mhz', 'throttle', 'power_limit_w', 'fan_pct', 'mem_activity_pct', 'pcie_gen', 'pcie_width')
# NVML clock event reasons (nvmlClocksEventReasons). Bits not listed are kept by number, never dropped
THROTTLE_BITS = ((0x1, 'gpu_idle'), (0x2, 'applications_clocks_setting'), (0x4, 'sw_power_cap'), (0x8, 'hw_slowdown'), (0x10, 'sync_boost'),
                 (0x20, 'sw_thermal_slowdown'), (0x40, 'hw_thermal_slowdown'), (0x80, 'hw_power_brake_slowdown'), (0x100, 'display_clock_setting'))


def decode_throttle(field):
    """'0x0000000000000004' -> ['sw_power_cap']; '0x0' -> []. Unreadable -> None (unknown). Bits not in the table -> 'bit_0x...'."""
    s = (field or '').strip().lower()
    try:
        mask = int(s, 16) if s.startswith('0x') else int(s)
    except ValueError:
        return None
    names = []
    for bit, name in THROTTLE_BITS:
        if mask & bit:
            names.append(name)
            mask &= ~bit
    b = 1
    while mask:
        if mask & b:
            names.append('bit_%#x' % b)
            mask &= ~b
        b <<= 1
    return names


def _z(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:-4] + 'Z'


def _gib(n):
    return round(n / 2 ** 30, 2)


class LiveSampler:
    def __init__(self, nvidia_cmd=('nvidia-smi',), interval_s=1.0, history_s=600, clock=time.time, psutil_module=None, gpu_reader=None,
                 paths=None, mai_home=None, usage_on=True, slow_interval_s=30, path_timeout_s=3.0, rate_clock=time.monotonic, usage_reader=None):
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
        self._gpu_reader = gpu_reader or self._read_gpu
        self._extra_ok = None          # None: not tried yet; False: the driver refused the extra fields, so the core query only
        self._primed = False
        self._rates = host.Rates(clock=rate_clock)
        self.host_info = self._host_info()
        self.paths = host.PathWatcher(paths if paths else host.default_paths(self._ps()), timeout_s=path_timeout_s)
        self.mai_home = mai_home
        self.usage_on = usage_on
        self._usage_reader = usage_reader or (lambda: usage.read(self.mai_home, clock=self.clock))
        self.slow_interval_s = float(slow_interval_s)
        self.slow = {'paths': self.paths.snapshot(), 'usage': None if usage_on else {'available': False, 'reason': 'usage view turned off (--no-usage)'},
                     'updated_at': None}

    def _read_gpu(self):
        """Core plus extra fields in one call when the driver supports them, else the core fields only."""
        if self._extra_ok is not False:
            text = nvidia.run_csv(self.nvidia_cmd, 'query-gpu', LIVE_GPU_QUERY + ',' + ','.join(EXTRA_FIELDS), timeout=5)
            if text is not None and text.strip():
                self._extra_ok = True
                return text
            if self._extra_ok is None:
                self._extra_ok = False
        return nvidia.run_csv(self.nvidia_cmd, 'query-gpu', LIVE_GPU_QUERY, timeout=5)

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
             'swap_used_gib': None, 'swap_total_gib': None, 'gpus': None, 'disks': None, 'nics': None, 'problems': []}
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
        if ps:
            s['disks'] = host.disk_io(ps, self._rates)
            s['nics'] = host.network(ps, self._rates)
        text = self._gpu_reader()
        if text is None or not text.strip():
            s['problems'].append('nvidia-smi unavailable or returned nothing: GPU and VRAM are unknown')
        else:
            s['gpus'] = self._parse_gpus(text, s['problems'])
            if s['gpus'] is None:
                s['problems'].append('nvidia-smi returned no valid device row: GPU and VRAM are unknown')
        with self.lock:
            self.samples.append(s)
        return s

    @staticmethod
    def _parse_gpus(text, problems):
        """Rows with the core columns, or the core columns plus EXTRA_FIELDS. Any other width is a malformed row and is reported."""
        n_core = len(LIVE_GPU_QUERY.split(','))
        core_lines, extras = [], {}
        for line in text.splitlines():
            if not line.strip():
                continue
            cells = [c.strip() for c in line.split(',')]
            if len(cells) == n_core + len(EXTRA_FIELDS):
                core_lines.append(','.join(cells[:n_core]))
                idx = nvidia.num(cells[0])
                if idx is not None:
                    extras[int(idx)] = cells[n_core:]
            else:
                core_lines.append(line)
        devices, p = nvidia.parse_gpus('\n'.join(core_lines) + '\n')
        problems += p
        if not devices:
            return None
        out = []
        for d in devices:
            g = {'index': d['index'], 'name': d['name'], 'uuid': d['uuid'], 'util_pct': d['utilization_pct'],
                 'vram_used_mib': d['memory_used_mib'], 'vram_total_mib': d['memory_total_mib'],
                 'temperature_c': d['temperature_c'], 'power_w': d['power_w']}
            ex = extras.get(d['index']) or [None] * len(EXTRA_KEYS)
            for k, cell in zip(EXTRA_KEYS, ex):
                if k == 'throttle':
                    g[k] = None if cell is None else decode_throttle(cell)
                else:
                    g[k] = nvidia.num(cell)
            out.append(g)
        return out

    def slow_once(self):
        """Watched paths and usage. Runs in its own thread, so a hanging network path never delays the one-second samples."""
        paths = self.paths.check(wall=self.clock())
        for r in paths:
            if isinstance(r.get('checked_at'), (int, float)):
                r['checked_at'] = _z(r['checked_at'])
        u = self.slow['usage']
        if self.usage_on:
            try:
                u = self._usage_reader()
            except Exception as e:                 # a broken usage file must not stop the resource view
                u = {'available': False, 'reason': 'usage read failed: %s' % type(e).__name__}
        slow = {'paths': paths, 'usage': u, 'updated_at': _z(self.clock())}
        with self.lock:
            self.slow = slow
        return slow

    def payload(self, since=None):
        with self.lock:
            items = list(self.samples)
            slow = self.slow
        if since:
            items = [x for x in items if x['t'] > since]
        return {'schema': LIVE_SCHEMA, 'interval_s': self.interval_s, 'history_s': self.history_s, 'host': self.host_info,
                'generated_at': _z(self.clock()), 'samples': items, 'slow': slow}

    def run(self, stop, sleep=time.sleep):
        """Samples until stop is set. A slow source delays the next sample; samples are never invented to fill a gap."""
        def slow_loop():
            while not stop.is_set():
                self.slow_once()
                stop.wait(self.slow_interval_s)
        threading.Thread(target=slow_loop, daemon=True).start()
        while not stop.is_set():
            started = time.monotonic()
            self.sample_once()
            rest = self.interval_s - (time.monotonic() - started)
            if rest > 0:
                stop.wait(rest)
