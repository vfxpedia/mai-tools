# mai-tools

Small, general-purpose tools for people who run long, unattended AI and GPU work and want to trust what ran, when, and whether it is still alive.

Each tool started as something its author needed, was checked against real measurements on one machine, and was then made to work for anyone. The rule is in [PRINCIPLES.md](PRINCIPLES.md): **Start with myself. Validate with evidence. Generalize for others.**

| Tool | What it does | Status | Install-free run |
|---|---|---|---|
| [mai-approve](tools/mai-approve/) | Owner-run standing approval with an expiry for unattended runs: a hashed approval file, per-run receipts, counts that cannot be reset by a new run id, a tamper-evident audit log | M1, reviewed | `python -m mai_approve --help` (inside `tools/mai-approve`) |
| [mai-watch](tools/mai-watch/) | Read-only monitor for GPU use and workload status: collector, idle detection with explicit unknowns, liveness, event log, local viewer | M2, reviewed | `python -m mai_watch --help` (inside `tools/mai-watch`) |
| [mai-tabs](tools/mai-tabs/) | Saves open browser tabs as categorized Markdown before a cleanup, proposes what could be closed, never closes anything | M1, exercised once in an isolated profile | `python -m mai_tabs --help` (inside `tools/mai-tabs`) |

Session mods live in [mods/](mods/): **mai-gauge** for Claude Code (install with `/plugin marketplace add vfxpedia/mai-tools` then `/plugin install mai-gauge@mai-mods`) and **mai-codex-gauge** for Codex.

Python 3.12 (Linux) and 3.13 (Windows) are the versions measured so far; older versions are not measured. No build step. Tests need `jsonschema`; mai-tabs process reports and one test need `psutil`; the viewer and mai-tabs tests need Node.js.

## Naming

| Where | Rule | Example |
|---|---|---|
| Tool, folder, command name, documents | `mai-<tool>` | `mai-watch` |
| Python package (`python -m ...`) | `mai_<tool>` (Python cannot import a hyphen) | `mai_watch` |
| Schema id | `mai-<tool>-<document>-v<N>` | `mai-watch-snapshot-v1`, `mai-approve-approval-v1` |

Ids used before this rule (`mai-approval-v1`, `mai-run-receipt-v1`) are still read so that files on disk keep working; new files never use them. Each tool keeps its own folder, tests, documents and version and imports nothing from another tool, so any tool can later move to its own repository unchanged.

## What "verified" means here

A tool is not called done because its tests pass. [docs/VERIFICATION.md](docs/VERIFICATION.md) lists the gates a tool must pass before it is called releasable, and [docs/PLATFORMS.md](docs/PLATFORMS.md) states per operating system what was actually run. Anything not measured is written as not measured.

## Run everything

```
pip install -r requirements-dev.txt
python common/hygiene_check.py        # no personal paths, addresses, hosts or secrets
python common/run_all_tests.py        # every test file, each in an isolated interpreter
```

## Status of this repository

Early. The first three tools are checked on Windows 11 and Ubuntu 24.04 (WSL). Linux and macOS runner results are in docs/PLATFORMS.md (mocked input only: no GPU or Chrome on a runner). Interfaces are versioned in their schemas (`mai-approve-approval-v1`, `mai-watch-snapshot-v1`, `mai-tabs-export-v1`) and may still change before 1.0.

License: see [LICENSE](LICENSE).
