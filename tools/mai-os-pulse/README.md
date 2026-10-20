# mai-os Pulse · AI-WS01 workstation panel

2026.10.13 KST · v0.1.2 · Windows/Ubuntu target · source + installation/build package

This package contains an implemented native desktop application, icon, Windows executable builder/installer, current-user login startup, Ubuntu launcher and tests. **It does not contain a prebuilt Windows .exe and has not been installed on AI-WS01.** The current development environment is Linux. Installation needs one action on that PC.

## v0.1.2 fix · based on AI-WS01 diagnosis

The supplied Windows report recorded CPU/RAM at <0.001s, GPU 0.156s, volumes 0.047s, disk I/O 0.031s and network 0.094s. **Only the original process scan exceeded 12 seconds and was timed out.** The original collector waited for that scan before emitting the main snapshot.

Changes:
- No process scan in normal panel/tray operation. It is requested only while Process View is visible.
- Process scan runs in a separate child executable/Python process. GUI/CPU/RAM do not wait for it; a five-second deadline stops only this diagnostic child.
- Removed repeated whole-process parent/status metadata queries and redundant CPU-percent calls. CPU percentages derive from sampled CPU time deltas and are available after a second successful reading. Parent PID/status columns were removed from the process view; investigate relationships through the native task manager.
- CPU/RAM and optional metric adapters stay independent. Error/paused states are explicit. Main window title identifies 0.1.2.
- Local bounded operational logs at `%LOCALAPPDATA%\MaiOsPulse\logs\pulse.log`.

**Update:** Quit the old app through tray → completely quit. Extract this new 0.1.2 ZIP and run `Install-Windows.cmd`. If the old app cannot quit because its scan is stuck, close only `MaiOsPulse.exe` in Task Manager. Do not rerun an older package. Python and dependencies already installed are reused.

**Verify after update:** main panel should refresh near the selected two-second interval without opening Process View. Check the version title and that STALE no longer climbs while the panel is visible. Open Process View separately: if it reports a process timeout, core readings must still update. Actual Windows memory/CPU use is not guaranteed by Linux measurements.

**Diagnose if still needed:** `Diagnose-Windows.cmd` writes `Pulse-Diagnostics.txt` into this extracted folder without needing the main app. Read-only probes are isolated and bounded. Review process/interface information before sharing.

The Windows report identifies the old process-scan bottleneck. **It does not verify installation or real-world responsiveness of the new build**; this still needs confirmation on AI-WS01.

## Windows 11: install and start

1. Extract the ZIP to a local folder. Do not execute from inside the ZIP.
2. Use 64-bit Python 3.10–3.14 with the `py` launcher installed. Python 3.12 is recommended. Download: https://www.python.org/downloads/windows/ . If the launcher exists, no Python change is needed.
3. Double-click **Install-Windows.cmd**. Dependencies are downloaded from PyPI into a dedicated virtual environment. Tests run, the icon is generated and PyInstaller builds `MaiOsPulse.exe` in a folder. No administrator permission is required. If a step fails, read the displayed error; it does not claim installation succeeded.
4. On success the app launches, adds a desktop shortcut and enables current-user login startup. The executable is under `%LOCALAPPDATA%\MaiOsPulse\dist\MaiOsPulse\MaiOsPulse.exe`. Keep its accompanying `_internal` folder; it is a folder-based executable distribution.
5. In Settings, choose a display and 2/5/10-second sampling. Normal window defaults avoid topmost interference. Tray → completely quit stops collection. X minimizes to tray when a system tray is available.

The application only samples data. The installer writes its own installation files, shortcut and login startup entry. It does not install HWiNFO, modify NVIDIA settings, kill processes, change power plans or apply RAM cleanup. A Windows build generated locally is not a publisher-signed application.

## Windows CPU/SSD temperature and CPU package power

These values are not reliably provided by standard Windows APIs. Optional HWiNFO: https://www.hwinfo.com/download/ . Follow the official current license terms: https://www.hwinfo.com/licenses/ . It is not bundled. Business use must follow the relevant license, rather than assuming the free personal-use route applies.

1. Start HWiNFO Sensors-only. Sensor configure → HWiNFO Gadget: enable reporting to Gadget. This is the registry export documented at https://docs.rainmeter.net/tips/hwinfo/ . Shared Memory is not needed by Pulse.
2. Export the actual CPU Tctl/Tdie/package temperature, CPU package power (W), and desired NVMe temperature sensors. Exact labels vary by firmware and hardware. Do not select a motherboard temperature in place of CPU package temperature.
3. In Pulse Settings select CPU temperature and package power from the exported list. All exported temperatures/power appear under Details, including SSD temperature readings with their original source names.
4. Registry data is considered unavailable if its key has not been updated for 15 seconds. If exported sensors change, check mappings. Never substitute zero for an unavailable reading.
5. Sensor export reads are every 10 seconds. HWiNFO has its own polling interval and overhead. Avoid redundant low-level sensor collectors; keep existing cooling control software if it is needed to operate cooling. Do not uninstall it just for monitoring.

GPU metrics do not depend on HWiNFO: NVML reads them from the installed NVIDIA driver. Actual RTX 5080 metric support still needs verification on your driver. There is no inference/training/CUDA initialization.

## Ubuntu (including the EVO 4TB multiboot installation)

Use the same extracted source package separately on Ubuntu. `bash install-linux.sh` installs to `~/.local/share/mai-os-pulse` (or XDG equivalent), creates its own venv, downloads dependencies and opens the panel. Enable login startup in Settings.

Ubuntu prerequisites, if missing:

```bash
sudo apt install python3-venv libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1
bash install-linux.sh
```

Use an already working NVIDIA Linux driver and verify `nvidia-smi` independently. Do not install/change drivers as part of this app's setup. CPU/NVMe thermal readings require hwmon exposure (e.g. k10temp/NVMe). Linux CPU package power is usually unavailable in this version. On Wayland, the compositor can override the requested window location; move it to the right manually or use an X11 session if needed. A tray requires desktop support; Ubuntu may need its existing AppIndicator extension enabled.

Source supports a common Windows/Linux UI. This release does **not** guarantee every OS, identical sensors, mobile operation or macOS operation. Each OS requires its own runtime/build. No live state is shared across rebooting into another OS.

## Actual use

- **GPU memory:** compare each GPU's allocated VRAM separately. 2×16GB is not generally a single 32GB pool. GPU compute utilization and memory allocation are different indicators.
- **CPU:** low overall load with one saturated logical processor can warrant checking single-thread code/preprocessing. It alone does not identify the cause. Details shows logical processors, not a guessed physical/SMT mapping.
- **RAM/processes:** open Processes and sort by RSS, CPU, age or observed RSS growth. Growth over about one minute can reflect caches or legitimate batch work; it is not a leak verdict. Copy PID or open the native task manager for manual investigation. No termination/trim action on user work processes exists in Pulse. Its own diagnostic child is stopped if it exceeds its deadline.
- **Disk:** local volume free space and device/block I/O are separately labelled. RAID/dynamic-volume/SSD mapping is not inferred. Busy percentage is shown only when the OS exposes a counter; it is a coarse interval estimate, not latency.
- **Network:** each active adapter is shown separately. These are throughput counters, not link capacity/quality or NAS health measurements.
- **Export:** Save creates a JSON containing the last 60 samples, host information, process names and PIDs on demand. Nothing is uploaded. Bounded operational error logs are saved locally (up to 3 MiB); samples are exported only on request. Review it before sharing.
- **Cost:** the footer reports this app's CPU use (100%=one logical processor) and RSS where the OS permits reading its own process. Observe it during normal workloads. No workload overhead percentage is claimed without measurement.

## Verify on AI-WS01

1. Compare CPU/RAM with Task Manager and both GPUs with `nvidia-smi`; small sampling differences are normal. Check actual CPU model/count instead of relying on the earlier “PRO 7970X” description: AMD 7970X and PRO 7975WX are different product names.
2. Use a known single-GPU task; confirm the corresponding UUID/PCI device and VRAM change. GPU enumeration numbers can change across OS/reboots.
3. Run a representative learning/simulation workload with Pulse fully quit, then with Pulse active, using the same workload and repeated timing. Compare speed and responsiveness. Check again with HWiNFO active separately if used.
4. If overhead is material, increase interval to 5/10s, hide the panel, or fully quit. Remove login startup in Settings to roll back. No power/fan/driver changes need to be undone.
5. Confirm login startup with a logout/login after installation; simply downloading the ZIP does not install or activate it.

## Remove

Windows: quit Pulse using the tray menu, then run `Uninstall-Windows.ps1` with PowerShell. It removes the controlled app folder, desktop shortcut and its startup entry; preferences/exported snapshots are retained. It never force-terminates processes.

Ubuntu: disable startup in Settings, quit the app, then delete the app's `~/.local/share/mai-os-pulse` folder (or the actual XDG location). To remove the startup entry manually, delete only `~/.config/autostart/mai-os-pulse.desktop` (or XDG equivalent).

## Development validation

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py
```

See `docs/VERIFICATION.md` for passed checks and unverified deployment items. The illustrated AI-WS01 preview uses explicitly labelled synthetic data, not readings from your computer.
