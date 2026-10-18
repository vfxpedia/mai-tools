Status: draft (M2 plus live view). 72 + 12 + 7 tests pass on Windows; earlier 72 + 7 also on on Windows, Linux (WSL and CI) and macOS (CI). Read real `nvidia-smi` on Windows and WSL. Not measured: a long run during real training or rendering (M3), notifier, macOS with a GPU.

[한국어](README.ko.md)

# mai-watch

A read-only monitor. It shows CPU, RAM, GPU and VRAM live in the browser, and it answers three questions about your jobs: how busy each GPU is, which jobs are alive, and since when a GPU has been idle.

## Live view in one command

```powershell
python -m mai_watch live
```

Open http://127.0.0.1:28765/ . CPU (with every core), RAM and swap, and for each GPU its use, VRAM, temperature and power, sampled every second, with graphs of the last 10 minutes. One process does the sampling and the page; Ctrl+C stops it. `--interval 2` samples every 2 s, `--history 1800` keeps 30 minutes, `--port` picks another port. Add `--config <mai-watch.toml>` to also record jobs and idle time below the live panel (the rest of this README). The live history lives in memory only; nothing is written for it. Values a source cannot give are shown as unknown, never as 0 (for example, the first CPU reading, which only opens the measurement window).

Needs `psutil` for CPU and RAM and `nvidia-smi` for the GPUs. Measured on Windows 11 with two RTX 5080: one `nvidia-smi` query takes about 0.08 s, and the page values matched `nvidia-smi` (VRAM identical; GPU use moves from second to second).

## Job and idle record

- Your jobs write a small status file (`status/*.json`) every so often. That is the only integration.
- The collector reads `nvidia-smi` and those files, and writes `snapshot.json`, `events.jsonl` and a heartbeat.
- `check` exits 1 when something needs attention (a job stopped updating, a source broke, the collector itself stopped). A local web page shows the same thing.

It never starts, stops or changes anything.

## Try it in five minutes

From `tools/mai-watch`. PowerShell shown; on Linux or macOS the commands are the same with `/` paths.

```powershell
# 1. a folder with a config file
python -m mai_watch init "$HOME\mai-watch-demo"

# 2. a pretend job that reports "running" right now
mkdir "$HOME\mai-watch-demo\status" -Force | Out-Null
$now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$job = '{"schema_version":1,"id":"my-first-job","kind":"job","state":"running","updated_at":"' + $now + '","heartbeat_interval_s":60,"device_uuids":[]}'
[IO.File]::WriteAllText("$HOME\mai-watch-demo\status\my-first-job.json", $job)

# 3. one collection, then ask whether anything is wrong
$cfg = "$HOME\mai-watch-demo\mai-watch.toml"
python -m mai_watch collect --config $cfg --once
python -m mai_watch check --config $cfg

# 4. the page: open http://127.0.0.1:28765/ in a browser, Ctrl+C to stop
python -m mai_watch serve --config $cfg
```

What you should see (measured 2026-10-18 on Windows with two GPUs): `check` prints `"ok": true` and `"alerts": []` and exits 0. The page lists each GPU with use, memory, temperature and power, and the job `my-first-job` as `running`, `alive`.

Known answer for the alarm: write the same file with an `updated_at` an hour ago, run `collect --once` again, and `check` prints `workload_stale` for `my-first-job` and exits 1.

For real use run `collect` without `--once` (every `interval_s`, default 10 s) and keep `serve` open. Without an NVIDIA GPU the GPU list is reported as unavailable, not as zero. Delete `$HOME\mai-watch-demo` when done.

## Status file (what your job writes)

| Field | Meaning |
|---|---|
| `schema_version` | `1` |
| `id`, `kind` | your name for it; `job` or `service` |
| `state` | `running`, `waiting`, `blocked`, `done`, `failed`; `waiting` and `blocked` need a `hold_reason` |
| `updated_at` | UTC time of this write; the job counts as stale after 3 missed `heartbeat_interval_s` |
| `device_uuids` | GPUs it uses (from `nvidia-smi -L`); empty is allowed |
| optional | `started_at`, `progress {done, total}`, `deadline`, `artifacts` (files whose change time shows real progress), `labels` |

Full contract: `schema/status.v1.schema.json`; `python -m mai_watch validate <files>` checks a file.

## Commands

`init <dir>` · `collect [--once]` · `check` (exit 1 on any alert) · `show` (prints the whole snapshot as JSON) · `serve` (page on 127.0.0.1:28765, local only) · `validate <files>`.

Design, idle rules and review history: [DESIGN.md](DESIGN.md). Tests: `python -I tests/test_mai_watch.py` and `tests/test_schema_contract.py` (need `jsonschema`; the page test needs Node.js).
