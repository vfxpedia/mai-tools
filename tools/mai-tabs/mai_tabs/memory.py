"""Memory measured around an action (DESIGN.md section 12.4): the browser's resident memory and each GPU's used memory, before and after.

Per-tab memory is not something the browser reports to an extension, and per-process GPU memory under Windows WDDM does not add up to
the GPU total (dwm counts surfaces of other windows), so the only honest figure is the whole: Chrome's processes together and each
GPU's total, read before the action and again after the browser has settled. The difference is reported as measured, and everything
else on the machine that changed in between is in it too; the page says so.
On Windows the figure is private bytes, memory that belongs to Chrome alone; elsewhere it is resident memory, which counts pages shared
between Chrome processes more than once, so there the absolute figure is high and the difference is what matters.
"""
import shutil
import subprocess
import time

CHROME = ('chrome', 'chrome.exe', 'google chrome', 'google chrome helper', 'google chrome helper (renderer)', 'google chrome helper (gpu)')


def browser_mib(names=CHROME):
    """Chrome's memory in MiB: private bytes on Windows (what Chrome alone holds), resident memory elsewhere. None without psutil.
    Only the browser's processes are asked for their memory, which keeps one reading near 0.1 s on a machine with 800 processes."""
    try:
        import psutil
    except ImportError:
        return None
    total = 0
    for p in psutil.process_iter(['name']):
        try:
            if (p.info['name'] or '').lower() in names:
                m = p.memory_info()
                total += getattr(m, 'private', 0) or m.rss
        except Exception:
            continue
    return round(total / 1048576)


def gpus_mib(timeout=5):
    exe = shutil.which('nvidia-smi')
    if not exe:
        return []
    try:
        p = subprocess.run([exe, '--query-gpu=index,memory.used,memory.total,display_active', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in p.stdout.splitlines():
        parts = [x.strip() for x in line.split(',')]
        if len(parts) >= 3 and parts[0].isdigit():
            try:
                out.append({'index': int(parts[0]), 'used_mib': int(float(parts[1])), 'total_mib': int(float(parts[2])),
                            'display': len(parts) > 3 and parts[3].lower() == 'enabled'})
            except ValueError:
                continue
    return out


def measure(clock=time.time):
    return {'at': int(clock() * 1000), 'browser_mib': browser_mib(), 'gpus': gpus_mib()}


def difference(before, after):
    """{'browser_mib': -830, 'gpus': [{'index': 1, 'mib': -410}]}; a side that was not measured stays None, never 0."""
    if not before or not after:
        return None
    b, a = before.get('browser_mib'), after.get('browser_mib')
    g_before = {g['index']: g['used_mib'] for g in before.get('gpus') or []}
    gpus = [{'index': g['index'], 'mib': g['used_mib'] - g_before[g['index']]} for g in after.get('gpus') or [] if g['index'] in g_before]
    return {'browser_mib': a - b if a is not None and b is not None else None, 'gpus': gpus, 'seconds': round((after['at'] - before['at']) / 1000)}
