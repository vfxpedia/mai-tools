"""What kind each network adapter is (DESIGN.md section 9f, review R10): wired, wireless, virtual or unknown.

A name says too little (en0 can be Wi-Fi, a VPN can be called Ethernet), so the kind comes from the OS: Get-NetAdapter on Windows
(Virtual, HardwareInterface, PhysicalMediaType) and /sys/class/net on Linux (a wireless folder, a device link, the link type). macOS
and any failure give unknown. Read once in the background at start. Read-only.
"""
import json
import os
import subprocess
import sys

from .nvidia import NO_WINDOW

PS = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-NetAdapter -IncludeHidden | Select-Object Name, Virtual, HardwareInterface, PhysicalMediaType | ConvertTo-Json -Compress")
KINDS = ('wired', 'wireless', 'virtual', 'unknown')


def parse_windows(text):
    try:
        rows = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    out = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get('Name'), str):
            continue
        media = str(r.get('PhysicalMediaType') or '')
        if r.get('Virtual') is True or r.get('HardwareInterface') is False:
            kind = 'virtual'
        elif '802.11' in media:
            kind = 'wireless'
        elif media == '802.3' and r.get('HardwareInterface') is True:
            kind = 'wired'
        else:
            kind = 'unknown'
        out[r['Name']] = kind
    return out


def read_linux(root='/sys/class/net'):
    out = {}
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for n in names:
        base = os.path.join(root, n)
        try:
            if os.path.isdir(os.path.join(base, 'wireless')) or os.path.isdir(os.path.join(base, 'phy80211')):
                out[n] = 'wireless'
            elif not os.path.exists(os.path.join(base, 'device')):
                out[n] = 'virtual'          # no hardware device behind it: bridge, veth, tun, docker, VPN
            else:
                with open(os.path.join(base, 'type')) as f:
                    out[n] = 'wired' if f.read().strip() == '1' else 'unknown'    # 1 = Ethernet
        except OSError:
            out[n] = 'unknown'
    return out


def read(timeout=15):
    if os.name == 'nt':
        try:
            p = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', PS], capture_output=True, text=True, creationflags=NO_WINDOW,
                               encoding='utf-8', errors='replace', timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return {}
        return parse_windows(p.stdout) if p.returncode == 0 else {}
    if sys.platform.startswith('linux'):
        return read_linux()
    return {}
