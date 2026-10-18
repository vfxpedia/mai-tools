"""Judgments with evidence (DESIGN.md section 9f, stage 2 of direction B on vfxpedia/mai-os#43).

One list of findings, computed from the live samples and the slow state, read by the page (the "check these" line at the top), by
/status.json (agents and notifiers) and later by alerts. A rule only states what was measured: each finding carries the numbers it
was decided on, and a rule that lacks the data it needs says nothing rather than guessing. Pure functions of their inputs, so every
rule has a known-answer test.

Levels: bad (act now), warn (look soon), info (worth knowing). Thresholds are named here and can be overridden by the caller.
"""

DEFAULTS = {
    'free_gib_warn': 50,          # a watched folder with less free space than this
    'used_pct_warn': 95,
    'free_gib_bad': 10,
    'gpu_temp_warn': 85,
    'ram_pct_warn': 90,
    'limit_pct_warn': 80,         # Claude or Codex plan window
    'limit_pct_bad': 95,
    'idle_vram_mib': 1024,        # a GPU holding at least this much memory ...
    'idle_util_pct': 5,           # ... while every sample in the window is below this use ...
    'idle_window_s': 300,         # ... for this long ...
    'idle_coverage': 0.8,         # ... with at least this share of the window actually sampled
    'slow_link_mbps': 1000,       # a wired adapter that is up but linked slower than this
}

LIMIT_REASONS = ('sw_power_cap', 'hw_slowdown', 'sw_thermal_slowdown', 'hw_thermal_slowdown', 'hw_power_brake_slowdown')
WIRELESS_HINTS = ('wi-fi', 'wifi', 'wlan', 'wireless', 'bluetooth', 'wl')


def _f(level, kind, subject, text, **evidence):
    return {'level': level, 'kind': kind, 'subject': subject, 'text': text, 'evidence': evidence}


def paths(slow, t):
    out = []
    for p in (slow or {}).get('paths') or []:
        name = p.get('label') or p.get('path')
        if p.get('state') in ('unreachable', 'no answer'):
            out.append(_f('bad', 'path_unreachable', name, '%s does not answer (%s)' % (name, p.get('error') or p.get('state')),
                          state=p.get('state'), checked_at=p.get('checked_at')))
            continue
        free, used = p.get('free_gib'), p.get('used_pct')
        if free is None or used is None:
            continue
        if free < t['free_gib_bad']:
            out.append(_f('bad', 'disk_space', name, '%s has %.1f GiB free' % (name, free), free_gib=free, used_pct=used))
        elif free < t['free_gib_warn'] or used >= t['used_pct_warn']:
            out.append(_f('warn', 'disk_space', name, '%s has %.1f GiB free (%.1f%% used)' % (name, free, used), free_gib=free, used_pct=used))
    return out


def network(last, t):
    out = []
    for n in (last or {}).get('nics') or []:
        speed = n.get('link_mbps')
        name = n.get('nic') or ''
        if speed is None or any(h in name.lower() for h in WIRELESS_HINTS):
            continue
        if speed < t['slow_link_mbps']:
            out.append(_f('warn', 'slow_link', name, '%s is linked at %d Mbps; a cable or switch port can hold a faster adapter back' % (name, speed),
                          link_mbps=speed))
    return out


def gpus(samples, t):
    out = []
    if not samples:
        return out
    last = samples[-1]
    for g in last.get('gpus') or []:
        name = 'GPU %s' % g.get('index')
        real = [r for r in (g.get('throttle') or []) if r in LIMIT_REASONS]
        if real:
            out.append(_f('warn', 'gpu_clock_limited', name, '%s clock is held back by %s' % (name, ', '.join(real)), reasons=real,
                          sm_clock_mhz=g.get('sm_clock_mhz'), power_w=g.get('power_w'), temperature_c=g.get('temperature_c')))
        temp = g.get('temperature_c')
        if temp is not None and temp >= t['gpu_temp_warn']:
            out.append(_f('warn', 'gpu_hot', name, '%s is at %s C' % (name, temp), temperature_c=temp))
        held = idle_holding(samples, g.get('uuid'), t)
        if held:
            out.append(_f('warn', 'gpu_vram_idle', name, '%s holds %.1f GiB but has been below %s%% use for %d min' % (
                name, held['vram_mib'] / 1024, t['idle_util_pct'], round(held['span_s'] / 60)), **held))
    return out


def _sec(iso):
    import datetime
    try:
        return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def idle_holding(samples, uuid, t):
    """Evidence when the GPU held memory and stayed below the use threshold for the whole window, else None. Needs the window to be
    covered: a short or gappy history is not enough to say it has been idle."""
    now = _sec(samples[-1].get('t'))
    if now is None:
        return None
    window = [s for s in samples if (_sec(s.get('t')) or 0) >= now - t['idle_window_s']]
    rows = []
    for s in window:
        g = next((x for x in s.get('gpus') or [] if x.get('uuid') == uuid), None)
        if g is None or g.get('util_pct') is None or g.get('vram_used_mib') is None:
            return None                               # an unknown reading inside the window: cannot say idle
        rows.append((_sec(s['t']), g['util_pct'], g['vram_used_mib']))
    if len(rows) < 2:
        return None
    span = rows[-1][0] - rows[0][0]
    if span < t['idle_coverage'] * t['idle_window_s']:
        return None
    if any(u >= t['idle_util_pct'] for _, u, _ in rows) or any(v < t['idle_vram_mib'] for _, _, v in rows):
        return None
    return {'span_s': round(span), 'samples': len(rows), 'max_util_pct': max(u for _, u, _ in rows), 'vram_mib': rows[-1][2]}


def host(last, t):
    out = []
    ram = (last or {}).get('ram_pct')
    if ram is not None and ram >= t['ram_pct_warn']:
        out.append(_f('warn', 'ram_high', 'RAM', 'RAM is %.0f%% used' % ram, ram_pct=ram))
    return out


def usage(slow, t):
    out = []
    u = (slow or {}).get('usage') or {}
    for r in u.get('limits') or []:
        for w, label in (('five_hour', '5-hour'), ('seven_day', '7-day')):
            x = r.get(w)
            if not x or x.get('pct') is None:
                continue
            pct = x['pct']
            level = 'bad' if pct >= t['limit_pct_bad'] else 'warn' if pct >= t['limit_pct_warn'] else None
            if level:
                out.append(_f(level, 'plan_limit', '%s %s' % (r.get('engine'), label), '%s %s window is at %s%%' % (r.get('engine'), label, pct),
                              pct=pct, reset=x.get('reset'), read_at=x.get('read_at')))
    for p in u.get('problems') or []:
        out.append(_f('info', 'usage_source', 'usage', p))
    return out


def sources(last):
    return [_f('info', 'source_problem', 'sampler', p) for p in (last or {}).get('problems') or []]


ORDER = {'bad': 0, 'warn': 1, 'info': 2}


def judge(samples, slow, thresholds=None):
    t = dict(DEFAULTS, **(thresholds or {}))
    last = samples[-1] if samples else None
    found = paths(slow, t) + network(last, t) + gpus(samples, t) + host(last, t) + usage(slow, t) + sources(last)
    return sorted(found, key=lambda f: ORDER[f['level']])
