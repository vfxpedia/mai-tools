# mai-os Pulse Implementation Plan

Goal: installable local monitoring and process diagnosis for AI-WS01 with a Windows/Ubuntu shared UI.
Architecture: Python collectors + OS adapters + Qt worker/UI; current-user login startup.
Stack: Python 3.10–3.14, PySide6 Essentials, psutil, NVIDIA NVML bindings, PyInstaller.
Spec: DESIGN.md.
Execution: implemented inline as requested.

- [x] Pure transforms: rates, unavailable values and observations. Verify negative/reset counters, independent GPU VRAM, single-thread load.
- [x] Sensor adapter: Linux hwmon and Windows HWiNFO read-only registry. Verify removed/duplicate sensor identity stays unavailable.
- [x] Background collector: CPU, RAM, GPU, local disk space/I/O, network and process history. Verify self-monitoring access failure does not break sampling.
- [x] Native panel, logical processor grid, process diagnostics, settings, tray/pause, JSON export and local single-instance IPC. Verify live/None/GPU removal rendering and inspect screenshots.
- [x] Icon, Windows per-user install/build/startup, Linux script and removal instructions.
- [x] Run full suite; archive source, scripts, design and verification report.
- [ ] Windows hardware deployment and .exe build validation on AI-WS01: cannot be performed from this Linux session.
- [ ] Ubuntu real desktop/hardware validation and workload A/B cost measurements.

## 0.1.2 corrective execution
- [x] Read actual AI-WS01 report and identify timed-out process adapter.
- [x] Default process diagnostics off; request only while diagnostic view is visible.
- [x] Child-process isolation and timeout/shutdown cleanup of only owned probes.
- [x] Reduce process metadata queries and derive CPU from elapsed CPU times.
- [x] Run 23 tests, Linux packaging and packaged probe/GUI launch verification.
- [ ] Verify new Windows GUI/resource costs on AI-WS01 after installation.
