# Platforms: what was actually run

Updated only from real runs. A cell that says "not measured" means no one ran it. Last updated 2026-10-18.

| System | Python | Node | How it was run | Result |
|---|---|---|---|---|
| Windows 11 Pro (WDDM GPUs) | 3.13 | 24 | `python common/run_all_tests.py` | 173 tests, 0 failed, 0 skipped |
| Ubuntu 24.04 under WSL2 | 3.12 | 20 | the same command, `psutil` not installed | 173 tests, 0 failed, 2 skipped (both need `psutil`; with `MAI_TOOLS_STRICT=1` they fail instead of skipping) |
| Ubuntu on a GitHub-hosted runner | 3.12 | 20 | CI, `MAI_TOOLS_STRICT=1`, `psutil` installed | 173 tests, 0 failed, 0 skipped (first push, 2026-10-18) |
| macOS on a GitHub-hosted runner | 3.12 | 20 | CI, same settings | 173 tests, 0 failed, 0 skipped (first push, 2026-10-18) |

## Session mods (CI, 2026-10-18)

| Mod | Windows | Ubuntu | macOS |
|---|---|---|---|
| mai-gauge (`claude plugin validate` and `test`, 81 tests) | passes on the author's machine | passes on the runner | not run |
| mai-codex-gauge (`node --test`, 117 tests) | 112 pass, 5 skipped (opt-in live tests) | passes | 0 failed, 7 skipped (d181c93). The earlier failure (a hook launched through a linked folder printed nothing) came from comparing the typed script path with the module's real path; fixed by comparing real paths. Before the store path fix there were about 70 failures, all from `/var` being a link. |

## What the numbers do not cover

- Runner results use mocked or recorded input only: a hosted runner has no GPU, no real Chrome and no desktop.
- **mai-watch** was run against a real `nvidia-smi` with two RTX 5080 on Windows and from WSL (read-only, one collection). Not measured: a long run, a real training or render job, other GPU vendors, macOS.
- **mai-tabs** extension: exercised by hand in one isolated Chrome profile on Windows. Not measured: a large real profile, audible tabs, incognito, Chrome on Linux or macOS, other Chromium browsers.
- **mai-approve**: file and path rules are tested on Windows (case-insensitive paths, junctions) and Linux (symlinks). An approval written on one system is refused on another by design, see the A7 row in its DESIGN.md. Not measured: how a particular AI-assisted shell treats an approval file written by its owner.

## Known cross-system differences already handled

| Difference | Handling |
|---|---|
| Windows process paths seen by a Linux collector | file name is taken after splitting on both separators |
| Path comparison is case-insensitive on Windows, case-sensitive on Linux | compared after the OS's own normalisation and real path resolution |
| Windows paths in an approval used on Linux (or the reverse) | refused with `foreign_path_notation`; the owner grants again on the new machine |
| Line endings in golden fixtures | `.gitattributes` forces LF |
| Ports reserved by Windows | mai-watch serves on 28765 and prints a clear error when a port is refused |
