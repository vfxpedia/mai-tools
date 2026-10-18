"""Collector (DESIGN.md sections 3, 5 to 8): reads resources and status documents, writes snapshot, events, heartbeat.

cycle() is a pure function of its inputs (time, devices, apps, documents, previous state) so that every rule can be tested
with known answers. The file and process parts are thin wrappers around it.
"""
import datetime
import json
import math
import os
import re
import time

from . import idle as idle_mod
from . import nvidia
from . import status as status_mod

SNAPSHOT_SCHEMA = 'mai-watch-snapshot-v1'
DEFAULT_IGNORE_PROCESSES = ('explorer.exe', 'chatgpt.exe', 'startmenuexperiencehost.exe', 'searchhost.exe', 'dwm.exe')


class Config:
    def __init__(self, status_dir, out_dir, **kw):
        self.status_dir, self.out_dir = status_dir, out_dir
        self.interval_s = kw.get('interval_s', 10)
        self.idle_window_s = kw.get('idle_window_s', 600)
        self.idle_utilization_pct = kw.get('idle_utilization_pct', 5)
        self.idle_min_s = kw.get('idle_min_s', 600)
        self.idle_resume_s = kw.get('idle_resume_s', 60)
        self.stale_factor = kw.get('stale_factor', 3)
        self.baseline_memory_mib = kw.get('baseline_memory_mib', {})
        self.nvidia_smi = list(kw.get('nvidia_smi', ['nvidia-smi']))
        self.ignore_processes = [x.lower() for x in kw.get('ignore_processes', DEFAULT_IGNORE_PROCESSES)]
        # a gap longer than this between samples is time that was not observed (W1); default 3 intervals, at least 30 s
        self.max_gap_s = kw.get('max_gap_s', max(3 * self.interval_s, 30))
        # a GPU monitor that cannot see any GPU must say so even on its very first cycle (W3); set false for hosts without a GPU
        self.require_gpu_source = kw.get('require_gpu_source', True)
        self.expected_device_uuids = list(kw.get('expected_device_uuids', []))
        self.future_tolerance_s = kw.get('future_tolerance_s', 60)
        self.missing_alert_s = kw.get('missing_alert_s', 86400)
        # live view only: folders whose free space and answer time are shown (local drives, NAS shares); empty means every local drive
        self.watch_paths = list(kw.get('watch_paths', []))
        self.mai_home = kw.get('mai_home')

    def tracker_args(self):
        return dict(window_s=self.idle_window_s, threshold_pct=self.idle_utilization_pct, min_s=self.idle_min_s, resume_s=self.idle_resume_s, max_gap_s=self.max_gap_s)


def exe_name(name):
    """Lower-case file name of a process path. Splits on both separators: nvidia-smi on Windows reports a drive path ending in app.exe, and a Linux host reading a Windows sample must give the same answer."""
    return re.split(r'[\\/]', str(name))[-1].lower()


def load_config(path):
    import tomllib
    path = os.path.expanduser(path)       # PowerShell passes ~ through to native programs unexpanded (review R7)
    with open(path, 'rb') as f:
        raw = tomllib.load(f)
    base = os.path.dirname(os.path.abspath(path))
    resolve = lambda p: p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
    kw = {k: v for k, v in raw.items() if k not in ('status_dir', 'out_dir')}
    if 'watch_paths' in kw:
        kw['watch_paths'] = [resolve(os.path.expanduser(p)) for p in kw['watch_paths']]
    return Config(resolve(raw['status_dir']), resolve(raw['out_dir']), **kw)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def write_json_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, path)


# ---------- status directory ----------

def read_status_dir(status_dir):
    """Every *.json that declares schema_version. Returns entries: {file, doc, problems}. Unreadable JSON is reported, not dropped."""
    entries = []
    if not os.path.isdir(status_dir):
        return entries
    for name in sorted(os.listdir(status_dir)):
        if not name.endswith('.json'):
            continue
        path = os.path.join(status_dir, name)
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except Exception as e:
            entries.append({'file': name, 'doc': None, 'problems': ['not readable as JSON: %s' % e]})
            continue
        if not isinstance(doc, dict) or 'schema_version' not in doc:
            continue
        entries.append({'file': name, 'doc': doc, 'problems': status_mod.validate(doc)})
    seen = {}
    for e in entries:                       # a repeated id is a diagnostic, not a silent overwrite (W5)
        if e['problems']:
            continue
        wid = e['doc']['id']
        if wid in seen:
            e['problems'] = ['duplicate id %r (also in %s); the first file wins' % (wid, seen[wid])]
        else:
            seen[wid] = e['file']
    return entries


def artifact_mtime(paths):
    best = None
    for p in paths:
        try:
            t = datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc).replace(tzinfo=None)
        except (OSError, ValueError):
            continue
        if best is None or t > best:
            best = t
    return best


# ---------- the cycle ----------

def _z(t):
    return status_mod.format_time(t) if t else None


def cycle(cfg, now, devices, apps, entries, state, host=None, mtime_of=None):
    """Returns (snapshot, events, new_state). devices is None when the source is unavailable."""
    mtime_of = mtime_of or artifact_mtime      # looked up at call time so the real function is what runs
    state = json.loads(json.dumps(state or {}))
    state.setdefault('trackers', {})
    state.setdefault('liveness', {})
    state.setdefault('invalid', [])
    state.setdefault('device_up', {})
    state.setdefault('first_progress', {})
    events = []

    def ev(type_, **kw):
        events.append(dict({'at': _z(now), 'type': type_}, **kw))

    # workloads
    workloads, invalid = [], []
    fresh_running = {}      # uuid -> [ids]
    holds = {}              # uuid -> (updated_at, id, reason)
    for e in entries:
        if e['problems']:
            invalid.append({'file': e['file'], 'problems': e['problems']})
            continue
        d = e['doc']
        try:
            updated = status_mod.parse_time(d['updated_at'])
            started = status_mod.parse_time(d['started_at']) if 'started_at' in d else None
        except ValueError as ex:             # one bad document never stops the collection (W5)
            invalid.append({'file': e['file'], 'problems': ['not a real time: %s' % ex]})
            continue
        terminal = d['state'] in status_mod.TERMINAL
        stale = (not terminal) and status_mod.is_stale(now, updated, d['heartbeat_interval_s'], cfg.stale_factor)
        liveness = 'ended' if terminal else ('stale' if stale else 'alive')
        am = mtime_of(d.get('artifacts', [])) if d.get('artifacts') else None
        wid = d['id']
        fp_key = '%s|%s' % (wid, d.get('started_at') or '')
        if fp_key not in state['first_progress']:
            evidence = None
            if am is not None and (started is None or am > started):
                evidence = am
            elif d.get('progress', {}).get('done', 0) > 0:
                evidence = now
            if evidence is not None:
                state['first_progress'][fp_key] = _z(evidence)
        workloads.append({
            'id': wid, 'kind': d['kind'], 'state': d['state'], 'effective_state': 'stale' if stale else d['state'], 'liveness': liveness,
            'device_uuids': d['device_uuids'], 'updated_at': d['updated_at'], 'heartbeat_age_s': round((now - updated).total_seconds(), 1),
            'started_at': d.get('started_at'), 'hold_reason': d.get('hold_reason'), 'deadline': d.get('deadline'),
            'progress': d.get('progress'), 'artifact_mtime': _z(am),
            'artifact_age_s': round((now - am).total_seconds(), 1) if am else None,
            'first_progress_at': state['first_progress'].get(fp_key), 'labels': d.get('labels', {}),
            'future_heartbeat': (updated - now).total_seconds() > cfg.future_tolerance_s,
        })
        prev = state['liveness'].get(wid)
        if prev == 'missing':
            ev('workload_reappeared', id=wid)
        if liveness == 'stale' and prev != 'stale':
            ev('workload_stale', id=wid, heartbeat_age_s=round((now - updated).total_seconds(), 1))
        elif liveness == 'alive' and prev == 'stale':
            ev('workload_recovered', id=wid)
        state['liveness'][wid] = liveness
        if d['state'] == 'running' and not stale:
            for u in d['device_uuids']:
                fresh_running.setdefault(u, []).append(wid)
        if d['state'] in ('waiting', 'blocked') and not stale:
            for u in d['device_uuids']:
                if u not in holds or updated > holds[u][0]:
                    holds[u] = (updated, wid, d['hold_reason'])
    state.setdefault('missing', {})
    seen_ids = {w['id'] for w in workloads}
    for wid in list(state['liveness']):
        if wid in seen_ids:
            state['missing'].pop(wid, None)
        elif state['liveness'][wid] in ('alive', 'stale'):
            state['missing'][wid] = _z(now)
            state['liveness'][wid] = 'missing'
            ev('workload_disappeared', id=wid)
    old_invalid = set(state['invalid'])
    for i in invalid:
        if i['file'] not in old_invalid:
            ev('workload_invalid', file=i['file'], problems=i['problems'])
    state['invalid'] = sorted(i['file'] for i in invalid)

    # devices
    dev_views = []
    if devices is None:
        for u, up in state['device_up'].items():
            if up:
                ev('device_unavailable', uuid=u)
                state['device_up'][u] = False
    else:
        seen = set()
        by_uuid = {}
        for a in apps or []:
            by_uuid.setdefault(a['gpu_uuid'], []).append(a)
        for d in devices:
            u = d['uuid']
            seen.add(u)
            if state['device_up'].get(u) is False:
                ev('device_recovered', uuid=u)
            state['device_up'][u] = True
            tr = idle_mod.IdleTracker.from_dict(state['trackers'].get(u, {}), **cfg.tracker_args())
            for te in tr.update(now, d['utilization_pct'], bool(fresh_running.get(u))):
                extra = {'since': _z(te['since'])}
                for k in ('duration_s', 'reason', 'unobserved_s'):
                    if k in te:
                        extra[k] = te[k]
                ev(te['type'], uuid=u, **extra)
            state['trackers'][u] = tr.to_dict()
            procs = by_uuid.get(u, [])
            base = cfg.baseline_memory_mib.get(u)
            hold = holds.get(u)
            dev_views.append({
                'index': d['index'], 'uuid': u, 'name': d['name'], 'utilization_pct': d['utilization_pct'],
                'memory_used_mib': d['memory_used_mib'], 'memory_total_mib': d['memory_total_mib'], 'baseline_memory_mib': base,
                'temperature_c': d['temperature_c'], 'power_w': d['power_w'],
                'idle': tr.open, 'idle_since': _z(tr.idle_since),
                'idle_for_s': round((now - tr.idle_since).total_seconds(), 1) if tr.open else None,
                'idle_candidate_since': _z(tr.cond_since) if (tr.cond_since and not tr.open) else None,
                'idle_reason': ({'workload': hold[1], 'reason': hold[2]} if hold else 'unrecorded') if tr.open else None,
                'running_workloads': fresh_running.get(u, []),
                'processes': procs,
                'processes_known': apps is not None,
                'user_processes': [p for p in procs if exe_name(p['name']) not in cfg.ignore_processes],
            })
        for u in list(state['device_up']):
            if u not in seen and state['device_up'][u]:
                ev('device_unavailable', uuid=u)
                state['device_up'][u] = False

    alerts = []
    for dv in dev_views:
        if dv['idle']:
            alerts.append({'type': 'device_idle', 'uuid': dv['uuid'], 'since': dv['idle_since']})
    for w in workloads:
        if w['liveness'] == 'stale':
            alerts.append({'type': 'workload_stale', 'id': w['id']})
    for w in workloads:
        if w['future_heartbeat']:
            alerts.append({'type': 'workload_clock_skew', 'id': w['id']})
    for wid, since in state['missing'].items():
        if (now - status_mod.parse_time(since)).total_seconds() <= cfg.missing_alert_s:
            alerts.append({'type': 'workload_disappeared', 'id': wid, 'since': since})
    for i in invalid:
        alerts.append({'type': 'workload_invalid', 'file': i['file']})
    if devices is None and cfg.require_gpu_source:
        alerts.append({'type': 'source_unavailable', 'detail': 'nvidia-smi gave no device data'})
    if devices is not None:
        got = {d['uuid'] for d in devices}
        for u in cfg.expected_device_uuids:
            if u not in got:
                alerts.append({'type': 'device_missing', 'uuid': u})
    for u, up in state['device_up'].items():
        if not up:
            alerts.append({'type': 'device_unavailable', 'uuid': u})
    snapshot = {
        'schema': SNAPSHOT_SCHEMA, 'generated_at': _z(now), 'interval_s': cfg.interval_s,
        'source': 'unavailable' if devices is None else 'nvidia-smi',
        'devices': dev_views, 'workloads': workloads, 'invalid': invalid, 'host': host or {'available': False}, 'alerts': alerts,
    }
    return snapshot, events, state


# ---------- files and process ----------

def host_metrics(path):
    try:
        import psutil
    except ImportError:
        return {'available': False}
    try:
        return {'available': True, 'cpu_pct': psutil.cpu_percent(interval=None), 'memory_pct': psutil.virtual_memory().percent,
                'disk_pct': psutil.disk_usage(path).percent}
    except Exception:
        return {'available': False}


def pid_alive(pid):
    """True/False when it can be known, None when it cannot. os.kill(pid, 0) is never used: on Windows it terminates the process."""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if os.name == 'nt':
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LockHeld(Exception):
    pass


def take_lock(out_dir):
    path = os.path.join(out_dir, 'collector.lock')
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(open(path, encoding='utf-8').read().strip() or 0)
            except Exception:
                pid = 0
            alive = pid_alive(pid) if pid else False
            if alive is False:
                os.remove(path)
                continue
            raise LockHeld('another collector holds %s (pid %s%s). Remove the file only if you know it is dead.' % (path, pid, '' if alive else ', liveness unknown'))
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
        return path
    raise LockHeld('could not take %s' % path)


def run_once(cfg, state, first, started_at, now=None, sampler=None):
    now = now or utc_now()
    devices, apps, problems = (sampler or (lambda: nvidia.sample(cfg.nvidia_smi)))()
    entries = read_status_dir(cfg.status_dir)
    snapshot, events, state = cycle(cfg, now, devices, apps, entries, state, host=host_metrics(cfg.out_dir))
    snapshot['source_problems'] = problems
    if problems and devices is not None:
        snapshot['alerts'].append({'type': 'source_problem', 'detail': '; '.join(problems)[:300]})
    snapshot['collector'] = {'pid': os.getpid(), 'started_at': _z(started_at)}
    if first:
        events.insert(0, {'at': _z(now), 'type': 'collector_started', 'pid': os.getpid()})
    write_json_atomic(os.path.join(cfg.out_dir, 'snapshot.json'), snapshot)
    if events:
        with open(os.path.join(cfg.out_dir, 'events.jsonl'), 'a', encoding='utf-8', newline='\n') as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
    write_json_atomic(os.path.join(cfg.out_dir, 'collector_heartbeat.json'),
                      {'pid': os.getpid(), 'started_at': _z(started_at), 'last_cycle_at': _z(now), 'interval_s': cfg.interval_s})
    write_json_atomic(os.path.join(cfg.out_dir, 'state.json'), state)
    return snapshot, events, state


def collect(cfg, once=False, max_cycles=None, sleep=time.sleep):
    os.makedirs(cfg.out_dir, exist_ok=True)
    lock = take_lock(cfg.out_dir)
    started = utc_now()
    state, first, n = {}, True, 0
    sp = os.path.join(cfg.out_dir, 'state.json')
    if os.path.exists(sp):
        try:
            state = json.load(open(sp, encoding='utf-8'))
        except Exception:
            state = {}
    try:
        while True:
            _, _, state = run_once(cfg, state, first, started)
            first, n = False, n + 1
            if once or (max_cycles is not None and n >= max_cycles):
                return n
            sleep(cfg.interval_s)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


# ---------- check ----------

def check(out_dir, now=None, ignore=()):
    """Alerts for `mai_watch check`. Empty means healthy. A fresh heartbeat is not enough (W4): the snapshot must have its structure, a sane
    generation time, and the same collector and cycle as the heartbeat; otherwise the check fails instead of reading an old or empty
    snapshot as 'no alerts'."""
    now = now or utc_now()
    alerts = []
    hp, sp = os.path.join(out_dir, 'collector_heartbeat.json'), os.path.join(out_dir, 'snapshot.json')
    hb = snap = None
    try:
        with open(hp, encoding='utf-8') as f:
            hb = json.load(f)
        last = status_mod.parse_time(hb['last_cycle_at'])
        interval = hb['interval_s']
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError('interval_s must be a positive finite number, got %r' % (interval,))
        age = (now - last).total_seconds()
        if age < -2 * interval:
            alerts.append({'type': 'collector_clock', 'detail': 'heartbeat is %.0f s in the future' % -age})
        elif age > 3 * interval:
            alerts.append({'type': 'collector_stale', 'age_s': round(age, 1)})
    except Exception as e:
        hb = None
        alerts.append({'type': 'collector_missing', 'detail': str(e)})
    try:
        with open(sp, encoding='utf-8') as f:
            snap = json.load(f)
    except Exception as e:
        alerts.append({'type': 'snapshot_missing', 'detail': str(e)})
    if snap is not None:
        problems = []
        if not isinstance(snap, dict) or snap.get('schema') != SNAPSHOT_SCHEMA:
            problems.append('schema is not %s' % SNAPSHOT_SCHEMA)
        else:
            for k, t in (('devices', list), ('workloads', list), ('invalid', list), ('alerts', list)):
                if not isinstance(snap.get(k), t):
                    problems.append('%s missing or not a %s' % (k, t.__name__))
            try:
                gen = status_mod.parse_time(snap['generated_at'])
                if hb is not None:
                    if abs((gen - last).total_seconds()) > 1.5 * interval:
                        problems.append('generated_at %s does not belong to the heartbeat cycle %s' % (snap['generated_at'], hb['last_cycle_at']))
                    if (snap.get('collector') or {}).get('pid') != hb.get('pid') or (snap.get('collector') or {}).get('started_at') != hb.get('started_at'):
                        problems.append('snapshot comes from a different collector run than the heartbeat')
                if (gen - now).total_seconds() > 2 * (interval if hb else 10):
                    problems.append('generated_at is in the future')
            except Exception as e:
                problems.append('generated_at: %s' % e)
        if problems:
            alerts.append({'type': 'snapshot_invalid', 'detail': '; '.join(problems)})
        elif isinstance(snap.get('alerts'), list):
            alerts += snap['alerts']
    return [a for a in alerts if a['type'] not in ignore]
