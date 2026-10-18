"""Read-only browser process report. It never ends a process and never claims a GPU share.

Per-process GPU memory is not available on Windows under WDDM (nvidia-smi prints [N/A], measured 10/15), so this report has none.
RSS counts shared pages in every process that maps them, so the total overstates real memory use; the report says so.
"""
from collections import defaultdict

BROWSER_NAMES = ('chrome', 'chrome.exe', 'google chrome', 'google chrome helper', 'msedge', 'msedge.exe', 'brave', 'brave.exe', 'firefox', 'firefox.exe')


def process_type(cmdline):
    for a in cmdline or []:
        if a.startswith('--type='):
            return a[len('--type='):] or 'unknown'
    return 'browser'


def summarize(rows):
    """rows: [{'pid', 'name', 'rss', 'type'}] (rss in bytes). Returns totals and per-type groups sorted by memory, largest first."""
    groups = defaultdict(lambda: [0, 0])
    for r in rows:
        g = groups[r['type']]
        g[0] += 1
        g[1] += int(r.get('rss') or 0)
    by_type = sorted(({'type': t, 'count': c, 'rss_mib': round(b / 1048576, 1)} for t, (c, b) in groups.items()),
                     key=lambda x: (-x['rss_mib'], x['type']))
    return {'count': len(rows), 'rss_mib': round(sum(int(r.get('rss') or 0) for r in rows) / 1048576, 1), 'by_type': by_type}


def collect_rows(names=BROWSER_NAMES):
    import psutil
    rows = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
        try:
            if (p.info['name'] or '').lower() in names:
                rows.append({'pid': p.info['pid'], 'name': p.info['name'], 'rss': p.info['memory_info'].rss if p.info['memory_info'] else 0,
                             'type': process_type(p.info['cmdline'])})
        except Exception:
            continue
    return rows


def render(summary):
    lines = ['# Browser processes', '', 'Processes: %d · resident memory: %.1f MiB (RSS overstates shared memory)' % (summary['count'], summary['rss_mib']),
             'No GPU figure is shown: per-process GPU memory is not available on Windows.', '', '| type | processes | MiB |', '|---|---|---|']
    for g in summary['by_type']:
        lines.append('| %s | %d | %.1f |' % (g['type'], g['count'], g['rss_mib']))
    return '\n'.join(lines) + '\n'
