"""Host resources beyond CPU and RAM (DESIGN.md section 9d): watched paths, disk I/O and network rates.

Read-only. A rate needs two readings, so the first reading of a counter is unknown, and a counter that went backwards (a reset, a
reconnected adapter) is unknown, never a negative or invented spike. A path that does not answer in time is reported as such: a
network share can hang for tens of seconds, so each path is checked in its own thread and a slow one never delays the others.
"""
import os
import shutil
import threading
import time

MAX_PATHS = 64
# Windows reports the largest 32-bit bits-per-second value for adapters without a real link (Hyper-V, VPN): 4294 Mbps after psutil's
# division. Only that exact value is unknown; a real 2.5, 5, 10 or 25 Gbps link is shown (review R5)
VIRTUAL_LINK_MBPS = 4294

GIB = 2 ** 30
MIB = 2 ** 20


def default_paths(psutil_module):
    """Local fixed drives and mounted network drives, as psutil lists them. Without psutil: the home folder only."""
    if not psutil_module:
        return [os.path.expanduser('~')]
    out = []
    try:
        for p in psutil_module.disk_partitions(all=False):
            opts = (p.opts or '').lower()
            if 'cdrom' in opts or (os.name == 'nt' and not opts):
                continue
            if p.fstype in ('squashfs', 'tmpfs', 'devtmpfs', 'overlay') or p.mountpoint.startswith(('/snap', '/boot', '/System/Volumes/')):
                continue
            out.append(p.mountpoint)
    except Exception:
        return [os.path.expanduser('~')]
    return out or [os.path.expanduser('~')]


class PathWatcher:
    """Free space, reachability and answer time of each watched path. check() starts at most one probe per path at a time."""

    def __init__(self, paths, timeout_s=3.0, usage=shutil.disk_usage, clock=time.monotonic):
        uniq = list(dict.fromkeys(paths))
        self.dropped = uniq[MAX_PATHS:]          # one thread per path at most: the list itself is bounded too
        self.paths = uniq[:MAX_PATHS]
        self.timeout_s = timeout_s
        self._usage = usage
        self._clock = clock
        self._lock = threading.Lock()
        self._running = {}
        self._overdue = set()
        self.results = {p: {'path': p, 'state': 'not checked yet', 'total_gib': None, 'free_gib': None, 'used_pct': None, 'answer_ms': None, 'checked_at': None} for p in self.paths}

    def _probe(self, path, wall):
        t0 = self._clock()
        try:
            u = self._usage(path)
            r = {'state': 'ok', 'total_gib': round(u.total / GIB, 2), 'free_gib': round(u.free / GIB, 2),
                 'used_pct': round(100.0 * (u.total - u.free) / u.total, 1) if u.total else None}
        except Exception as e:      # any failure ends the probe with a state; a probe that died silently would stay "running" forever
            r = {'state': 'unreachable', 'error': type(e).__name__ + (': ' + e.strerror if getattr(e, 'strerror', None) else ''),
                 'total_gib': None, 'free_gib': None, 'used_pct': None}
        r.update(path=path, answer_ms=round((self._clock() - t0) * 1000, 1), checked_at=wall)
        with self._lock:
            self.results[path] = r
            self._running.pop(path, None)
            self._overdue.discard(path)

    def check(self, wall=None):
        """Starts a probe for every path that has none running, waits up to timeout_s, and returns the current results."""
        wall = wall if wall is not None else time.time()
        started = []
        for p in self.paths:
            with self._lock:
                if p in self._running:
                    continue
                th = threading.Thread(target=self._probe, args=(p, wall), daemon=True)
                self._running[p] = (th, self._clock())
            th.start()
            started.append(th)
        end = self._clock() + self.timeout_s
        for th in started:
            th.join(max(0.0, end - self._clock()))
        with self._lock:
            # decided by whether the probe finished within the wait, not by comparing clock readings: on Windows the monotonic clock
            # ticks in about 15 ms steps, so "waited >= timeout" could be false right after a full wait (review R6, Windows CI)
            for p, (th, _) in self._running.items():
                if th.is_alive() and th in started:
                    self._overdue.add(p)
        return self.snapshot()

    def snapshot(self):
        now = self._clock()
        out = []
        with self._lock:
            for p in self.paths:
                r = dict(self.results[p])
                if p in self._running:
                    waited = now - self._running[p][1]
                    if p in self._overdue or waited >= self.timeout_s:   # the earlier answer is kept but marked: no answer now
                        r['state'] = 'no answer'
                        r['waiting_s'] = round(waited, 1)
                out.append(r)
        return out


class Rates:
    """Bytes per second from monotonic counters. First reading and counter resets give None."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._prev = {}

    def update(self, key, counters):
        """counters: dict name -> number. Returns dict name -> rate per second or None."""
        now = self._clock()
        prev = self._prev.get(key)
        self._prev[key] = (now, dict(counters))
        out = {}
        for name, v in counters.items():
            if prev is None or name not in prev[1] or now <= prev[0] or v < prev[1][name]:
                out[name] = None
            else:
                out[name] = (v - prev[1][name]) / (now - prev[0])
        return out


def disk_io(ps, rates):
    """Per physical disk read and write MiB/s. None when the source cannot give it."""
    try:
        # nowrap=False: psutil's default hides a counter that went back by adding the old total, which would turn a reset into a
        # normal-looking rate; we want the raw counter and our own rule (review R4)
        per = ps.disk_io_counters(perdisk=True, nowrap=False)
    except Exception:
        return None
    if not per:
        return None
    flat = {}
    for name, c in per.items():
        flat[name + '/r'] = c.read_bytes
        flat[name + '/w'] = c.write_bytes
    r = rates.update('disk', flat)
    out = []
    for name in sorted(per):
        rd, wr = r.get(name + '/r'), r.get(name + '/w')
        out.append({'disk': name, 'read_mib_s': None if rd is None else round(rd / MIB, 2), 'write_mib_s': None if wr is None else round(wr / MIB, 2)})
    return out


def network(ps, rates):
    """Per adapter that is up (loopback left out): receive and send MiB/s and the link speed the OS reports. Adapters are never summed:
    a VPN adapter carries traffic that also crosses the physical one, so a total would count it twice."""
    try:
        counters = ps.net_io_counters(pernic=True, nowrap=False)
        stats = ps.net_if_stats()
    except Exception:
        return None
    flat, names = {}, []
    for name, c in counters.items():
        st = stats.get(name)
        if st is None or not st.isup or 'loopback' in name.lower() or name == 'lo':
            continue
        names.append(name)
        flat[name + '/rx'] = c.bytes_recv
        flat[name + '/tx'] = c.bytes_sent
    r = rates.update('net', flat)
    out = []
    for name in sorted(names):
        rx, tx = r.get(name + '/rx'), r.get(name + '/tx')
        speed = stats[name].speed
        # 0 means not reported; VIRTUAL_LINK_MBPS is the Windows value for "no real link"
        out.append({'nic': name, 'rx_mib_s': None if rx is None else round(rx / MIB, 3), 'tx_mib_s': None if tx is None else round(tx / MIB, 3),
                    'link_mbps': speed if isinstance(speed, int) and speed > 0 and speed != VIRTUAL_LINK_MBPS else None})
    return out
