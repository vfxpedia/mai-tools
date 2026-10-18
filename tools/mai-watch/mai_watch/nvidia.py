"""nvidia-smi source: parsers and runner (DESIGN.md section 5).

Measured on a Windows 11 WDDM machine with two RTX 5080: the compute-apps list is never empty, per-process memory is [N/A], one name was
[Insufficient Permissions]. The parsers keep these values as they are. Nothing here infers idleness from the process list.
NVML through pynvml is a later source (M3): it is not installed on the reference machine, so it cannot be verified yet.
"""
import csv
import io
import math
import subprocess

GPU_QUERY = 'index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw'
APPS_QUERY = 'gpu_uuid,pid,process_name,used_memory'
GPU_COLUMNS = GPU_QUERY.split(',')
APPS_COLUMNS = APPS_QUERY.split(',')
NA_MARKERS = ('[n/a]', '[not supported]', '[unknown error]', 'n/a')


def num(field):
    """A number from an nvidia-smi field, or None when the field says it is not available. Never 0 for 'not available'."""
    s = (field or '').strip()
    if not s or s.lower() in NA_MARKERS:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v):          # NaN or inf from a damaged row is not a reading (review R8)
        return None
    return int(v) if v == int(v) else v


def _rows(text, ncols):
    good, bad = [], []
    for row in csv.reader(io.StringIO(text or '')):
        if not row or not any(c.strip() for c in row):
            continue
        if len(row) != ncols:
            bad.append(row)
            continue
        good.append([c.strip() for c in row])
    return good, bad


def parse_gpus(text):
    """Returns (devices, problems). A malformed row is reported, never dropped silently."""
    rows, bad = _rows(text, len(GPU_COLUMNS))
    devices = []
    for r in rows:
        idx = num(r[0])
        if idx is None or not r[1]:
            bad.append(r)
            continue
        devices.append({
            'index': int(idx), 'uuid': r[1], 'name': r[2],
            'utilization_pct': num(r[3]), 'memory_used_mib': num(r[4]), 'memory_total_mib': num(r[5]),
            'temperature_c': num(r[6]), 'power_w': num(r[7]),
        })
    return devices, ['malformed gpu row: %r' % (b,) for b in bad]


def parse_apps(text):
    rows, bad = _rows(text, len(APPS_COLUMNS))
    apps = [{'gpu_uuid': r[0], 'pid': num(r[1]), 'name': r[2], 'memory_mib': num(r[3])} for r in rows]
    return apps, ['malformed process row: %r' % (b,) for b in bad]


def run_csv(cmd, query_flag, query, timeout=20):
    """Runs nvidia-smi (cmd is a list, so tests can substitute a stub). Returns text, or None when the tool is missing or fails."""
    full = list(cmd) + ['--%s=%s' % (query_flag, query), '--format=csv,noheader,nounits']
    try:
        p = subprocess.run(full, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def sample(cmd=('nvidia-smi',)):
    """One sample: (devices or None, apps, problems). devices is None when the source is unavailable."""
    problems = []
    gtext = run_csv(cmd, 'query-gpu', GPU_QUERY)
    if gtext is None or not gtext.strip():
        return None, [], ['nvidia-smi unavailable or returned nothing']
    devices, p1 = parse_gpus(gtext)
    problems += p1
    if not devices:      # output that holds no valid device row is a broken source, not an empty one (M01)
        return None, [], problems + ['nvidia-smi returned output with no valid device row']
    atext = run_csv(cmd, 'query-compute-apps', APPS_QUERY)
    if atext is None:    # a failed query is unknown, not zero processes (M07)
        return devices, None, problems + ['compute-apps query failed; the process list is unknown']
    apps, p2 = parse_apps(atext)
    problems += p2
    return devices, apps, problems
