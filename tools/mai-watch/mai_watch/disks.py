"""Names for physical disks (DESIGN.md section 9f): which model each disk is and which drive letters or mount points live on it.

psutil names disks the way the OS counts them (PhysicalDrive5 on Windows, nvme0n1 on Linux), which says nothing to a person. This asks
the OS once at start: PowerShell Get-Disk and Get-Partition on Windows, lsblk on Linux. macOS and any failure give an empty map, and
the page then keeps the OS name. Read-only.
"""
import json
import os
import subprocess
import sys

PS = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Disk | ForEach-Object { $n = $_.Number; [pscustomobject]@{ n = $n; model = $_.FriendlyName; size = $_.Size; "
      "letters = @(Get-Partition -DiskNumber $n -ErrorAction SilentlyContinue | Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter + ':' }) } } "
      "| ConvertTo-Json -Depth 3 -Compress")


def _run(cmd, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def parse_windows(text):
    try:
        rows = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get('n'), int):
            continue
        letters = r.get('letters') or []
        if isinstance(letters, str):
            letters = [letters]
        out['PhysicalDrive%d' % r['n']] = {'model': str(r.get('model') or '').strip()[:60] or None,
                                           'places': [str(x) for x in letters if isinstance(x, str)][:8]}
    return out


def parse_lsblk(text):
    try:
        devs = json.loads(text).get('blockdevices') or []
    except (TypeError, ValueError, AttributeError):
        return {}
    out = {}

    def mounts(d):
        found = [m for m in (d.get('mountpoints') or [d.get('mountpoint')]) if m]
        for c in d.get('children') or []:
            found += mounts(c)
        return found
    for d in devs:
        if d.get('type') != 'disk' or not d.get('name'):
            continue
        out[d['name']] = {'model': (d.get('model') or '').strip()[:60] or None, 'places': mounts(d)[:8]}
    return out


def read(timeout=15):
    if os.name == 'nt':
        text = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command', PS], timeout)
        return parse_windows(text) if text else {}
    if sys.platform.startswith('linux'):
        text = _run(['lsblk', '-J', '-o', 'NAME,MODEL,TYPE,MOUNTPOINTS'], timeout)
        return parse_lsblk(text) if text else {}
    return {}


def label_for_place(place, disk_map):
    """'D:\\' -> 'WD_BLACK SN850X 4000GB' when a disk holds that letter or mount point, else None."""
    p = place.rstrip('\\/') or place
    for d in disk_map.values():
        for x in d.get('places') or []:
            if x.rstrip('\\/') == p or (x.rstrip('\\/') or x) == p:
                return d.get('model')
    return None
