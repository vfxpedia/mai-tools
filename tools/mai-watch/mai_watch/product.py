"""Bounded local observation and identity-free support diagnostics. No file or network access."""
import datetime
import math
import os


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


class CpuProcesses:
    """Nonblocking CPU-time deltas. One logical core is 100%; identities include creation time."""
    def __init__(self):
        self.previous = {}
        self.at = None

    def update(self, processes, now):
        current, names = {}, {}
        for p in processes:
            try:
                i = p.info
                pid, born = int(i['pid']), float(i['create_time'])
                total = float(i['cpu_times'].user + i['cpu_times'].system)
                if pid <= 0 or not math.isfinite(total) or total < 0 or not math.isfinite(born):
                    continue
                key = (pid, born)
                current[key] = total
                names[key] = os.path.basename((i.get('name') or 'unknown').replace('\\', '/'))[:80]
            except Exception:
                continue
        result = None
        if current and self.at is not None and now > self.at:
            result = []
            for key, total in current.items():
                old = self.previous.get(key)
                if old is not None and total >= old:
                    result.append({'pid': key[0], 'process': names[key],
                                   'cpu_pct': round(100 * (total - old) / (now - self.at), 1)})
            result.sort(key=lambda x: (-x['cpu_pct'], x['pid']))
            result = result[:3] or None
        self.previous, self.at = current, now
        return result


NEXT = {
    'gpu_hot': 'Check cooling and sustained load. Do not stop another workload without approval.',
    'gpu_clock_limited': 'Compare clock, power limit and temperature. A power cap alone is not a failure.',
    'gpu_vram_idle': 'Confirm the job phase and owner before changing a workload.',
    'disk_space': 'Identify growing files and confirm retention before deleting anything.',
    'path_unreachable': 'Check mount and network reachability; do not infer disk space.',
    'slow_link': 'Check adapter type, negotiated speed, cable and switch port.',
    'ram_high': 'Compare top RSS processes and swap activity.',
    'plan_limit': 'Check the gauge reading time and reset time before assigning new work.',
    'source_problem': 'Check the capability diagnostics below.',
    'usage_source': 'Check local gauge availability; do not copy authentication files.',
}


def iso(now):
    return datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat()


class Incidents:
    """At most 256 observations / 24 hours in memory; a missing source is not a resolution."""
    def __init__(self, limit=256, retention_s=86400):
        self.limit, self.retention_s = limit, retention_s
        self.items = {}
        self.closed = []

    def update(self, findings, observable, now, interval):
        self.items = {k: v for k, v in self.items.items() if now - v['last_seen'] <= self.retention_s}
        self.closed = [v for v in self.closed if now - v['last_seen'] <= self.retention_s]
        seen = set()
        for f in findings:
            key = f['kind'] + '|' + str(f['subject'])
            seen.add(key)
            old = self.items.get(key)
            if old and old['state'] == 'cleared':
                self.closed.append(dict(old))
            continuous = old and old['state'] == 'active' and 0 <= now - old['last_seen'] <= max(3 * interval, 5)
            start = old['observed_from'] if continuous else now
            self.items[key] = dict(f, first_seen=old['first_seen'] if old and old['state'] != 'cleared' else now,
                                   last_seen=now, observed_from=start, state='active')
        for key, value in self.items.items():
            if key not in seen and value['state'] != 'cleared':
                value['state'] = 'cleared' if key in observable else 'unknown'
                if value['state'] == 'cleared':
                    value['cleared_at'] = now
        if len(self.items) > self.limit:
            keep = sorted(self.items, key=lambda k: self.items[k]['last_seen'], reverse=True)[:self.limit]
            self.items = {k: self.items[k] for k in keep}
        self.closed = sorted(self.closed, key=lambda x: x['last_seen'], reverse=True)[:max(0, self.limit - len(self.items))]

    def decorate(self, findings, now):
        out = []
        for f in findings:
            v = self.items.get(f['kind'] + '|' + str(f['subject']))
            row = dict(f, next_check=NEXT.get(f['kind'], 'Check the source measurement and its timestamp.'))
            row.update(first_observed_at=iso(v['first_seen']) if v else None,
                       last_observed_at=iso(v['last_seen']) if v else None,
                       observed_s=round(v['last_seen'] - v['observed_from'], 1) if v and v['state'] == 'active' else None)
            out.append(row)
        return out

    def rows(self, now):
        return [dict(v) for v in sorted(list(self.items.values()) + self.closed, key=lambda x: x['last_seen'], reverse=True)
                if now - v['last_seen'] <= self.retention_s]


def diagnostic(sample, host, slow, fresh):
    """Create a new fixed schema, never recursively copy supplied dictionaries or strings."""
    sample, host, slow = sample or {}, host or {}, slow or {}
    checks = []
    def check(key, ok, reason, action):
        checks.append({'source': key, 'state': 'available' if ok else 'unknown',
                       'reason': 'measurement available' if ok else reason, 'next_check': action})
    check('host', sample.get('cpu_pct') is not None, 'CPU has no completed measurement window or psutil is unavailable',
          'Wait for two samples; run mai-watch with psutil installed in the same Python environment.')
    check('gpu', sample.get('gpus') is not None, 'nvidia-smi returned no valid GPU measurement',
          'Run nvidia-smi locally and check the driver and command availability. Non-NVIDIA GPUs are not supported.')
    check('process_cpu', sample.get('cpu_processes') is not None, 'Process scan is warming up or access is restricted',
          'Wait for two background scans. Permission-denied processes remain unmeasured.')
    check('usage', bool((slow.get('usage') or {}).get('available')), 'Local gauge records are absent, disabled or unreadable',
          'Check the local gauge installation. Do not export authentication files.')
    check('freshness', fresh, 'Sampling is stale or has not started', 'Check the running collector, then reload the page.')
    checks.append({'source': 'sharing', 'state': 'local-only', 'reason': 'Server binds loopback; a reverse proxy may change access',
                   'next_check': 'Share only inside a trusted network. This viewer has no internet authentication.'})
    gpu_keys = ('index', 'util_pct', 'vram_used_mib', 'vram_total_mib', 'temperature_c', 'power_w')
    return {'schema': 'mai-watch-diagnostic-v1', 'fresh': fresh is True,
            'metrics': {k: number(sample.get(k)) for k in ('cpu_pct', 'ram_pct', 'ram_used_gib', 'ram_total_gib')},
            'gpus': [{k: number(g.get(k)) for k in gpu_keys} for g in (sample.get('gpus') or [])[:64]],
            'checks': checks,
            'privacy': 'No paths, host names, process names, session names, commands, logs or credentials included.'}
