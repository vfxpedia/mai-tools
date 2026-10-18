Status: draft (M2, live view, wider resources). 132 tests pass on Windows (72 + 12 + 25 + 16 + 7). The earlier 72 + 7 also pass on Linux (WSL and CI) and macOS (CI). Real `nvidia-smi`, disks, network and usage were read on one Windows 11 machine. Not measured: a long run during real training or rendering (M3), notifier, macOS with a GPU, Linux and macOS paths for the session usage files.

[한국어](README.ko.md)

# mai-watch

A read-only monitor for one machine. The page opens with what needs attention (for example a nearly full drive, a slow network link, a GPU that holds memory but does nothing), each line decided from measured numbers. Below that it shows, live:

- CPU (every core), RAM and swap
- each GPU: use, VRAM, temperature, power against its limit, SM clock against its maximum, and whether the clock is being limited and why
- watched folders: free space, how full, and whether they answer (local drives, NAS shares)
- network adapters and disks: how fast data moves right now
- AI coding sessions: Claude Code and Codex plan limits, and per session today's turns, cost and tokens

The same attention list is at http://127.0.0.1:28765/status.json with the numbers behind each line, for scripts and AI agents.

It also keeps a record of your jobs: which are alive, and since when a GPU has been idle. It never starts, stops or changes anything.

## Start

```
pip install ./tools/mai-watch      # from the mai-tools folder; brings psutil
mai-watch
```

The page opens in your browser at http://127.0.0.1:28765/ . Ctrl+C stops it. Without installing, `python -m mai_watch` from `tools/mai-watch` does the same (CPU, RAM, disks and network then need `pip install psutil`).

Useful options: `--path //nas/share` (watch a folder, repeatable), `--port 28766`, `--interval 2` (sample every 2 s), `--history 1800` (keep 30 minutes), `--no-browser`, `--no-usage`.

How to read it:

- A value the source could not give is shown as `unknown`, never as 0. The first rate after start is unknown because a rate needs two readings.
- `clocks low: no work` means the GPU has nothing to do. `clock limited by sw_power_cap` (or a thermal reason) means the GPU is working but held back.
- Free space is shown in GiB first. 99.9 % used can still be 7 GiB or 7 TiB.
- Network adapters are shown one by one and never added up: a VPN adapter carries traffic that also crosses the physical one.
- Graph lines break where samples are missing, so an unobserved stretch never looks like a steady value.
- Plan limit percentages are the gauges' last reading, taken when a session takes a turn; the page shows how old that reading is. They are not measured live.
- Disks are named by model and drive letter. Rows that show nothing (idle disks, virtual adapters, quiet sessions) are folded.

Measured on Windows 11 with two RTX 5080: page values matched `nvidia-smi`; one `nvidia-smi` query takes about 0.08 s; a NAS address that does not answer took Windows 21 s to fail, and the page marked it `no answer` after 3 s while the rest kept updating.

## AI session usage

Read from what the session gauges in this repository ([mai-gauge](../../mods/mai-gauge), [mai-codex-gauge](../../mods/mai-codex-gauge)) record in `~/.mai` (or `$MAI_HOME`, or `--mai-home`). The gauges take the plan limits from the CLIs you are already signed in to, so there is no key to set.

mai-watch reads only `limits.json`, `sessions/` and `costlog/` in that folder, and only files whose real path stays inside it: a link or junction that leads elsewhere (for example to `~/.codex/auth.json`) and a hard-linked file are refused and named on the page. What it shows is rebuilt field by field: each session's name and the one line it says it is doing, numbers, counts and sums. Prompt text and anything of an unexpected type are dropped. A missing token or cost value is unknown, not 0, and a sum over fewer turns than were made says how many it covers. Cost is the API price estimate the gauges compute, not a bill. Without the gauges the page says there is no usage source.

## Job and idle record

Your jobs write a small status file (`status/*.json`) every so often. That is the only integration. The collector reads `nvidia-smi` and those files and writes `snapshot.json`, `events.jsonl` and a heartbeat. `check` exits 1 when something needs attention (a job stopped updating, a source broke, the collector itself stopped).

Try it:

```
mai-watch demo
```

This makes `~/mai-watch-demo` (or the folder you give) with a configuration and one sample job that reports `running`, and opens the page with the job table under the live view. The sample job does not update itself, so after 3 missed heartbeats (3 minutes) it turns `stale`: that is the alarm working. `mai-watch check --config ~/mai-watch-demo/mai-watch.toml` prints the same and exits 1 (`~` works in PowerShell too). The demo only writes into a new or empty folder or one it made itself, so it never touches a real setup. Delete the folder when done.

For real use: `mai-watch init <folder>`, point your jobs at its `status` folder, and run `mai-watch live --config <folder>/mai-watch.toml`. In the configuration, `watch_paths = ["D:/runs", "//nas/share"]` sets the watched folders.

## Status file (what your job writes)

| Field | Meaning |
|---|---|
| `schema_version` | `1` |
| `id`, `kind` | your name for it; `job` or `service` |
| `state` | `running`, `waiting`, `blocked`, `done`, `failed`; `waiting` and `blocked` need a `hold_reason` |
| `updated_at` | UTC time of this write; the job counts as stale after 3 missed `heartbeat_interval_s` |
| `device_uuids` | GPUs it uses (from `nvidia-smi -L`); empty is allowed |
| optional | `started_at`, `progress {done, total}`, `deadline`, `artifacts` (files whose change time shows real progress), `labels` |

Full contract: `schema/status.v1.schema.json`; `mai-watch validate <files>` checks a file.

## Commands

`mai-watch` (same as `live`) · `demo [folder]` · `init <folder>` · `collect [--once]` · `check` (exit 1 on any alert) · `show` (the whole snapshot as JSON) · `serve` (page for a separate collector) · `validate <files>`. Everything listens on 127.0.0.1 only.

Design, idle rules and review history: [DESIGN.md](DESIGN.md). Tests: `python -I tests/test_mai_watch.py`, `tests/test_live.py`, `tests/test_resources.py`, `tests/test_judge.py`, `tests/test_schema_contract.py` (needs `jsonschema`; the page tests need Node.js).
