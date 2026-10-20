# Verification · mai-os Pulse 0.1.2 · 2026-10-13 KST

## Actual Windows evidence supplied by user
Old 0.1.1 diagnostic harness against AI-WS01:
CPU/RAM <0.001s; GPU 0.156s; local volumes 0.047s; disk I/O 0.031s; network 0.094s; exported sensors absent (0.000s); process scan timed out at 12s.
This proves the tested old process scan exceeded the deadline; it does not establish which individual process or metadata query caused it. Old all-or-nothing collection meant this scan blocked main snapshots.

## New implementation checked here
- 23 tests passed, including normal-mode process scan off, on-demand scan on, no whole-process ppid/status query, true child-process scan, CPU delta history, own-child timeout, shutdown handling, optional adapter failure and UI states.
- Python compilation passed.
- Linux PyInstaller folder build passed (headless XCB library warnings; desktop prerequisites documented).
- Packaged process-probe entry point executed successfully, without loading the GUI path, and returned process records.
- Packaged GUI launch/screenshot/normal exit passed.
- Blocked-volume GUI responsiveness trial ran ~12s; CPU/RAM updates continued. Raw Linux measurements in PERFORMANCE.json. No NVIDIA driver was available in this test environment; do not interpret its memory/CPU measurements as Windows predictions.

## Still requires AI-WS01 verification
New Windows build/install, normal GUI responsiveness and footprint, optimized on-demand process probe timing, HWiNFO sensor export. Original report did verify both RTX 5080 device reads on the existing driver.

## Behavioral changes
Process diagnostics are on-demand only, in an isolated child with a 5s deadline. Only this child is stopped on timeout; user jobs are not terminated. Parent/status metadata columns removed; native task manager remains available. No process list is repeatedly scanned in normal operation.
