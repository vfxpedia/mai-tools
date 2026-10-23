Status: draft. M0, M1 and M2 are implemented (collector, status schema, idle detection, liveness, event log, CLI, viewer, local server), 72 tests + 7 contract tests, independently reviewed. Windows: all pass. Linux (WSL): all pass, one test skipped without psutil. Viewer checked in light and dark at 390, 768, 1280 px. Not measured: long-running operation, notifier, a real training or render job (M3), macOS.

# mai_watch: resource and workload status monitor (design v0.1)

## 1. Purpose and scope

mai_watch answers three questions at a glance, on any machine and OS:

1. What is the utilization of each resource (GPU first, then host CPU, memory, disk) right now?
2. Which workloads are running, and are they alive?
3. For how long has a resource been idle, and why?

In scope: collection, a stable status schema for workloads, idle detection, liveness detection, an append-only event log, a static viewer, a CLI.

Out of scope for v1: controlling workloads (no stop, kill, or launch), remote access, authentication, metrics storage beyond the event log, vendors other than NVIDIA (the schema leaves room for them).

The design is not tied to any project. the first project is the first user, through an adapter that it owns.

## 2. Terminology

Standard terms are used everywhere in code, files, and docs.

| Term | Definition |
|---|---|
| collector | The process that samples resources and writes the snapshot. |
| snapshot | One JSON document with the latest samples. Replaced atomically. |
| utilization | Percentage of time the device was busy in the sampling interval (NVML `utilization.gpu`). |
| idle | A device state, defined in section 6. Never inferred from the process list. |
| idle detection | The rule that opens and closes idle intervals. |
| status document | A small JSON file that a workload writes about itself (section 4). |
| heartbeat | Periodic refresh of a timestamp that proves a writer is alive. |
| stale | A status document or collector heartbeat older than its time-to-live. |
| liveness | Whether a writer is still updating its heartbeat. Distinct from `state`. |
| event log | Append-only JSON Lines file of state transitions. |
| adapter | A small translator from a project's own files to the status schema. Owned by the project. |
| viewer | A static HTML page that reads the snapshot. |

## 3. Architecture

Data flows one way: workloads and the host feed the collector; the collector writes files; everything else only reads those files.

1. Workloads write status documents into a configured status directory. They never talk to the collector.
2. The collector runs every `interval_s` (default 10). It reads resource metrics and the status directory, applies idle detection and staleness checks, writes `snapshot.json` (atomic replace), appends transitions to `events.jsonl`, and refreshes `collector_heartbeat.json`.
3. The viewer is one static HTML file that polls `snapshot.json` and `collector_heartbeat.json` and renders them. It makes no external requests.
4. The CLI (`python -m mai_watch`) offers `collect`, `check`, `show`, `validate`. `check` exits non-zero when any alert condition holds, so other tools can use it without parsing.

A different viewer (terminal table, desktop widget) can replace the HTML page without touching the collector. A second adapter can be added without touching the schema.

## 4. Status schema v1

A status document is one JSON object. Writers replace the file atomically (write a temporary file in the same directory, then rename). Times are RFC 3339 in UTC, for example `2026-10-15T05:30:00Z`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | integer, must be `1` | yes | Reject documents with an unknown major version. |
| `id` | string, 1 to 128 chars of `[A-Za-z0-9._-]` | yes | Stable identifier of the workload. |
| `kind` | `job` or `service` | yes | A job ends; a service runs until stopped. |
| `state` | `running`, `waiting`, `blocked`, `done`, `failed` | yes | See rules below. |
| `updated_at` | RFC 3339 time | yes | Last heartbeat. |
| `heartbeat_interval_s` | number > 0 | yes | How often the writer promises to refresh `updated_at`. |
| `device_uuids` | array of strings | yes (may be empty) | Devices the workload uses, by UUID (never by index). |
| `started_at` | RFC 3339 time | no | When the workload started. |
| `hold_reason` | string | when `state` is `waiting` or `blocked` | Why it is not running. |
| `deadline` | RFC 3339 time | no | Latest acceptable end. |
| `progress` | object with `done` and `total` numbers | no | Optional coarse progress. |
| `labels` | object of string to string | no | Free metadata. |

Rules:

- `running` means the workload is actively using its devices. `waiting` means it is intentionally paused for a known reason. `blocked` means it cannot continue without outside action. `done` and `failed` are terminal.
- A document is stale when `now - updated_at > stale_factor * heartbeat_interval_s` (default factor 3). A stale document with state `running` is reported as `stale`, not as running.
- Unknown fields are ignored. Missing required fields make the document `invalid`, which is reported and never silently dropped.
- Devices are identified by UUID because index order differs between CUDA (default `FASTEST_FIRST`) and `nvidia-smi` (PCI bus order), and this machine has two identical GPUs.
- The directory to scan is configured. File names are free; the collector reads every `*.json` in the status directory that declares `schema_version`.

Adapters convert project-specific files to this schema. The first project's unattended chain files (`gate_result.json`, `watchdog_hb.json`, `kill_receipt.json`) are the first adapter input; the adapter is written and owned by the first project.

## 5. Resource collection

Sources are tried in order, per resource:

1. NVML through `pynvml` (package `nvidia-ml-py`), if importable.
2. `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`, parsed by header-independent column order.
3. None: the resource is reported as `unavailable`. The collector never exits because of a missing source.

Host metrics use `psutil` when present (CPU, memory, disk), and are reported as `unavailable` otherwise.

Measured on a Windows 11 WDDM workstation with two RTX 5080 on 2026-10-15:

- `pynvml` is not installed; `psutil` is. So the `nvidia-smi` path is the primary path on this machine and must be tested first.
- With both GPUs idle, `nvidia-smi --query-compute-apps` still listed several PIDs (ChatGPT.exe, explorer.exe, StartMenuExperienceHost, SearchHost). Per-process memory was `[N/A]` for all, and one process name was `[Insufficient Permissions]`. Under WDDM the process list is not a usable signal for "a job is running".
- GPU 1 held 5,645 MiB of memory with no job (desktop applications), so memory used is not a signal either.

Consequences, all enforced in the design: the process list is displayed but never used for idle detection; per-device memory is reported as measured, with a configurable `baseline_memory_mib` per device so that "memory attributable to workloads" is only ever what workloads report themselves; no device-total value is attributed to a workload.

## 6. Idle detection

A device is idle at a sample time when both hold:

1. Its utilization, averaged over the last `idle_window_s` (default 600), is below `idle_utilization_pct` (default 5).
2. No fresh status document with state `running` lists that device UUID.

An idle interval opens when the condition has held continuously for `idle_min_s` (default 600) and closes when it stops holding for `idle_resume_s` (default 60, hysteresis against flapping). The interval is recorded from the first sample of the condition, not from the moment it was confirmed.

The reason for an interval comes from status documents: the `hold_reason` of the most recent document that listed the device in state `waiting` or `blocked`. If none exists the reason is `unrecorded`. A reason is never invented.

All thresholds are configuration, not constants. Defaults are proposals to be tuned on measured data.

## 7. Liveness

- Workload liveness: a status document older than its time-to-live is `stale` (section 4). The transition is written to the event log.
- Collector liveness: the collector refreshes `collector_heartbeat.json` every cycle with its start time, PID, and last cycle time. The viewer shows the age of this heartbeat and turns it red after `3 * interval_s`. `mai_watch check` fails when the heartbeat is stale or missing.
- Single instance: the collector takes an exclusive lock file at start and exits with a clear message if it cannot.
- Supervision: the collector is expected to be restarted by the operating system (a repeating scheduled task on Windows, a service with restart on Linux). Registering that task changes the machine and needs the owner's approval; it is not done by the tool on its own.

The reason for collector liveness is practical: a monitor that stops silently leaves an empty log that looks like "nothing happened". On 2026-10-13 an unattended archive job hung for 18 hours without any signal for the same reason.

## 8. Events and notifications

The event log is JSON Lines, one object per transition: `idle_started`, `idle_ended`, `workload_stale`, `workload_recovered`, `workload_invalid`, `collector_started`, `device_unavailable`, `device_recovered`. Each has `at`, `type`, and the identifiers involved. The log is append-only and never rewritten.

Sinks, in order of delivery:

1. Files (default, always on): `snapshot.json` and `events.jsonl`.
2. `mai_watch check` exit status.
3. Notifier plugins (off by default). A plugin receives events and may, for example, send one line to an idle terminal session. Any such plugin must send only to a session that is idle with an empty input box. A notifier is a separate decision from this design and shares code with the session-resume watcher in the internal issue.

## 9. Viewer

One static HTML file with inline script and style, no external requests, no frameworks. It reads `snapshot.json` and `collector_heartbeat.json` through a relative path. When opened from a file, browsers block reads; the CLI can serve the directory on `127.0.0.1` only. The page shows per device: utilization, memory, temperature, power, idle or busy, the interval so far, and the reason; per workload: state, liveness, age of last heartbeat; and the age of the collector heartbeat at the top.

## 9c. Live view (added 2026-10-18 after the owner's first use)

The owner's first use showed the gap: the page was a picture of one collection (`collect --once`), host CPU and RAM were collected as percentages but never shown, the interval was 10 s and there was no history. What was wanted is a live resource view: CPU, GPU, RAM and VRAM, moving.

- `python -m mai_watch live` runs one process: a sampler thread (default every 1 s), the local server, and with `--config` the existing workload collector. Ctrl+C stops all.
- Sample (`mai-watch-live-v1`): time, CPU average and per core, RAM used (total minus available), total and percent, swap, and per GPU use, VRAM used and total, temperature, power. A value the source cannot give is None with the reason in `problems`; the first CPU reading is None because psutil's first call only opens the window.
- History is an in-memory ring of `history_s / interval_s` samples (default 600). It is not written to disk; the durable record stays in snapshot.json and events.jsonl. `/live.json?since=<t>` returns only newer samples, so a poll each second stays small.
- The page adds a live panel (tiles with a number and a graph whose window grows with the data up to the history). Without a live sampler (`serve`) the panel stays hidden. Live without `--config` shows "workload recording off" instead of an error.
- Measured: one nvidia-smi query about 0.08 s on the reference machine; page values matched nvidia-smi; tests with a fake psutil and fixed nvidia-smi text (12), graph point math checked in node, removing the first-reading rule fails a test.
- Not done in 9c (clocks and limit reasons came in 9d): P state; per-process GPU memory (not available under WDDM); a durable metric history; NVML source.

## 9d. Wider resources and one command (owner decision 2026-10-18, direction B on vfxpedia/mai-os#43)

Direction B: facts and judgments first (a judgment list with evidence, stage 2), and the page, agents and notifications all read the same list. Stage 1 widens what is measured and makes the start one command.

- `mai-watch` with no command is `live`, opens the browser (`--no-browser` or `CI` set turns that off), and `pip install ./tools/mai-watch` installs the `mai-watch` command with psutil. `mai-watch demo [folder]` writes a configuration and a sample job (any OS, no hand-written JSON) and starts live with it; it refuses a folder that holds a real configuration.
- GPU: the live query asks for SM clock and its maximum, memory clock, clock limit reasons, power limit, fan, memory activity and PCIe link in the same call. One unsupported field fails the whole nvidia-smi call: if the very first try fails, the core query is used from then on (asked once); if a later call fails after earlier successes, that sample falls back to the core query and the next sample tries again. A damaged extra field (NaN, a negative or over 64-bit mask) makes that field unknown with a problem line, never the sample; the sampler loop also survives an exception in a sample. Limit reasons decode the NVML bit mask; bits outside the table are kept as `bit_0x...`; unreadable is unknown. `gpu_idle` is shown as "clocks low: no work", not as a slowdown. `utilization.memory` is named memory activity: it is the share of time memory was read or written, not VRAM fill.
- Watched paths: local drives by default (psutil partitions), plus `--path` and `watch_paths`. Each path is probed in its own thread and the round waits at most 3 s (the probe itself cannot be cancelled; the wait is bounded). A path still probing is not probed again (no pile-up) and is `no answer`, decided by whether the probe finished within the wait, not by comparing clock readings (the Windows clock ticks in about 15 ms steps; this failed once in CI). At most 64 paths; more are listed as not watched. Path state is rebuilt on every page poll, so an answer or a new silence shows at once, with its check time. Measured: an unroutable share took Windows 21 s to fail; the page said `no answer` after 3 s. Free space is shown in GiB first.
- Disk and network: per physical disk and per adapter that is up, rates from raw counter differences over monotonic time (`nowrap=False`: psutil's default would add the old total after a reset and show a normal-looking rate). First reading and a counter that went backwards are unknown. Loopback is left out; adapters are never summed (a VPN adapter repeats traffic of the physical one). Windows adapters without a real link report exactly 4294 Mbps (the largest 32-bit value): only that value is unknown; 2.5, 5, 10 and 25 Gbps are shown. Physical disks are not mapped to drive letters (not guessed).
- Graph lines break at gaps longer than max(3 intervals, 5 s).
- Paths and usage are read every 30 s in two separate threads, so a hanging share delays neither the one-second samples nor usage; they travel in `slow` of live.json. `mai-watch demo` writes only into a new or empty folder or one carrying its marker file `.mai-watch-demo`. `~` in a config path is expanded by mai-watch itself (PowerShell passes it through).
- Independent review of stage 1 (pipeline, vfxpedia/mai-os#43): eight findings R1 to R8 (usage boundary and types, demo overwrite, unknown counted as 0, psutil nowrap, 10 Gbps hidden, path timing and freshness, ~ in PowerShell, damaged extra fields). Each reproduction is now a test, and removing each rule makes a test fail.

## 9e. AI session usage as a resource

The session gauges already record plan limits and spend under `~/.mai` (or `$MAI_HOME`). `usage.py` reads only `limits.json` (latest reading per account and window; after its reset time a reading is shown as unknown, not as current), `sessions/` (sessions updated in the last 24 h) and `costlog/<local date>/` (turns, cost and tokens per session, today). A file is read only if its real path stays inside the real gauge home, it is a regular file with one link and at most 4 MiB; at most 500 files per folder. Output is rebuilt per field with fixed types (session id, name and doing line as short strings; finite numbers in range), so prompt text, nested objects and credential content cannot pass (tests plant canaries in a prompt, in wrongly typed fields, behind a hard link and behind a junction). A missing token or cost value is unknown, not 0; sums carry the number of turns they cover; a session with no cost log today has unknown turns. A Codex costUsd of 0 without a costSource is unknown (older Codex gauges wrote 0 for no price); a Claude 0 is 0. Cost is the gauges' API price estimate. Without the folder the answer is "no usage source", never zero.

Measured on the reference machine: Claude 5-hour and 7-day percent, Codex 7-day percent, per session turns and cost (Claude) or tokens (Codex). Not measured: where these files live on Linux and macOS, a Codex 5-hour reading (the gauge does not record one yet), usage without the gauges.

## 9f. Judgments first, then the page (stage 2 and 3 of direction B)

`judge.py` turns the live samples and the slow state into one list of findings: level (bad, warn, info), kind, subject, a sentence, and the numbers it was decided on. Rules: a watched folder under 10 GiB free is bad, under 50 GiB or at least 95 % used is warn; a folder that does not answer is bad; a wired adapter that is up but linked under 1000 Mbps is warn (wireless and adapters without a reported speed are skipped); a GPU clock held back by power or thermal reasons is warn (`gpu_idle` is not a slowdown); a GPU at 85 C or more is warn; a GPU that held at least 1 GiB while every sample of the last 5 minutes was under 5 % use is warn, and only when the window is at least 80 % covered and no reading in it is unknown; RAM at 90 % or more is warn; a plan window at 80 % is warn and at 95 % bad; sampler and usage source problems are info. A rule without the data it needs says nothing. Thresholds are named in `judge.DEFAULTS` and can be passed in.

The list travels in live.json (`judgments`) for the page and at `/status.json` (`mai-watch-status-v1`, with counts) for agents and notifiers, so all three read the same judgment (stage 4 connects them).

The page now puts order to work: the attention list first; each GPU as a wide row with use and VRAM on one shared graph and temperature, power against its limit, clock and limit reason beside it; CPU, RAM, network and disk activity in a smaller band; storage sorted by free space; AI sessions with the plan windows as meters that state the age of the gauge's reading. Idle disks, adapters without link speed or traffic, and sessions idle for over an hour are folded. Disks are named by model and drive letter (`disks.py`: PowerShell Get-Disk and Get-Partition on Windows, lsblk on Linux, read once in the background at start; macOS keeps the OS name).

Independent review R9 to R12 (pipeline, vfxpedia/mai-os#43), fixed: the idle-VRAM rule now refuses a window with any gap longer than max(3 intervals, 5 s), the gap at which the graph breaks, so two end points or a hole in the middle never count as idle time (the interval is passed in); the cable sentence needs an adapter the OS calls wired (`nics.py`: Get-NetAdapter Virtual, HardwareInterface and PhysicalMediaType on Windows, /sys/class/net on Linux; PowerShell is told to write UTF-8, otherwise Korean adapter names never matched), an adapter of unknown kind gets a note without a cause, wireless and virtual get nothing; the page calls a row idle only when rates were read and stayed at zero, unknown rates stay in view, and only virtual adapters that were read at zero are folded; folded groups keep their open state across the one-second redraw.

Measured on the reference machine: the list gave H: 7.4 GiB free (bad), D: and I: nearly full, and the 100 Mbps link, the same as measured by hand; disk names matched Get-Disk; the page was checked in a browser. Removing each of 11 rules makes a test fail. Not measured: the idle-VRAM rule against a real held-but-idle job, Linux disk names on a real machine.

## 9g. Agents and notifications (stage 4 of direction B)

`mai-watch status` reads `/status.json` of a running mai-watch and prints one line per finding; exit 0 nothing at warn or bad, 1 something is, 2 not reachable or not a status document (never read as all clear). This is the interface for agents: a session checking a long run asks it instead of running its own nvidia-smi, df and so on, and gets the judgment the page shows.

Notifications (`notify.py`): mai-watch holds no messaging token. A command chosen by the owner receives each message on standard input as UTF-8, and in `notify_file` first when set (a relative `notify_file` in a configuration is relative to that file). `Notifier.update` proposes events and `Notifier.commit` records them only after the command succeeded (review R13), so a failed send is proposed again, carried in the next message with anything newer, and tried after a growing wait (30 s after the first failure, doubled per further failure, at most 30 min); a finding that met its hold but went away before any send succeeded is still delivered, as "came and went" when its absence is observed and as the announcement it was, marked "cannot be read now", when it cannot be judged (second recheck, A); a gap or stale stretch restarts the timers but never cancels a finding already due (second recheck, B); a command that times out may therefore deliver twice. A finding (identified by kind and subject) is announced after it has been observed for `hold_s`, again when it rises from warn to bad, quietly remembered when it eases, and announced as cleared after it has been observed absent for `hold_s`. A finding that cannot be judged right now is not absent, so its clear timer waits (review R14): the status document lists `observable` 'kind|subject' keys, built from the measurement each rule needs (a GPU row without a temperature is not observable for heat, a folder that does not answer or keeps only its last numbers is not observable for free space, a removed device for nothing), and `blind` names whole sources that cannot be read. Time counts only while observed: a gap between checks over 90 s or any stale stretch restarts the hold and the clear timers, and while samples are stale nothing is judged (review R15 and its recheck). `hold_s` must be a finite number of seconds, 0 or more; a bad setting stops mai-watch before anything starts (review R17). `/status.json` `notify` shows the last attempt, ok, detail, delivered count, pending count and failures in a row. Commands are split without a shell, keeping backslashes and empty quoted arguments.

`/status.json` now carries `sample_age_s`, `max_sample_age_s` (3 intervals, at least 10 s), `fresh`, `stale_reason` and `blind`. `mai-watch status` checks the document (an object, the schema, a list of well-formed judgments, a freshness flag) and recomputes the counts from the judgments, refusing a document whose counts disagree (review R16); stale samples, a malformed document and an unreachable mai-watch all exit 2.

Measured on the reference machine: with the existing Telegram sender as the command and its outbox as the file, one message with the four current findings, sender result `exit 0: sent ok=True`; arrival on the phone is confirmed by the owner, not by the sender's word. Review R13 to R18 (pipeline, vfxpedia/mai-os#43) each has its reproduction as a regression test, and removing each of 21 notifier and status rules makes a test fail (run with bytecode caching off, see os/tool-hazards.md in mai-os). Not done: a mai-gauge MCP tool over the same status (agents use the CLI now), notifications from the workload record (stale job) through the same path.

Every child program (nvidia-smi each second, the PowerShell disk and adapter queries, the notification command) is started with CREATE_NO_WINDOW on Windows. Measured: a console-less parent (pythonw, as a scheduled task runs it) calling nvidia-smi 10 times without the flag opened 10 visible console windows; mai-watch itself under pythonw for 20 s opened none.

## 9h. Desktop and mobile layout follow-up (2026-10-23, mai-os#55)

The overview and host band share a three-column grid. GPUs span the first two columns, attention occupies the third, and CPU, RAM and network occupy one column each. At narrower widths the overview becomes one column. At 390 CSS pixels both GPUs remain vertically stacked. Warning rows, GPU status and quota highlights never start inside a closed details group. Long storage and session tables retain folding.

The live sampler excludes compute rows with unavailable or non-positive VRAM, invalid PIDs and placeholder process names before reading process metadata. Each GPU retains at most three, sorted by VRAM descending and PID for ties. The viewer repeats the memory/name filter for older payloads. Unknown query and empty verified list have different messages; neither claims that an unmeasurable Windows workload is absent. These presentation limits do not change job or idle judgments.

Regression checks use the real renderer with a small DOM harness for visibility and process rows. An optional Chrome CDP runner measures actual geometry and screenshots at exact 1920x1080 and 390x844 CSS viewports, using a public-safe fixture. It checks shared grid edges, host heights, core-cell size, warning visibility, vertical GPU order and overflow. Failed baseline assertions are recorded alongside the passing new layout. No monitor restart is required for the check.

## 9i. Viewer recovery (0.2.0a2, owner approval 2026-10-23)

`viewer-connection.js` owns a bounded polling loop for each source (live resources and workload snapshots). Its six-second deadline covers headers and body parsing. A timed-out request is aborted, reports failure, and retries after three seconds. Regular requests never overlap within a source. A coalesced visibility/pageshow/online event replaces the pending request, invalidates the old generation and rejects late results before any DOM update. Workload rendering is separate from its read task for the same reason.

Live status updates on a separate one-second timer, so a pending fetch cannot leave an old green badge or frozen age indefinitely. It distinguishes last successful receipt from the latest sample timestamp. Fresh HTTP with stale samples remains stale. Unknown and future measurement times are not live. The explicit reload button navigates the page only, disables repeated clicks, retains the saved theme, and never restarts the monitor. It is not a remote execution endpoint. Both header controls have at least 44 CSS pixels of height.

The loopback binding, endpoint allowlist, no-store responses, local-only defaults and read-only monitoring model remain unchanged. Internet publication, remote control and account management are not included. External-release follow-ups are listed in the recovery review rather than silently added to this release.

## 10. Security and safety

- Read-only toward workloads. No stop or kill capability, and nothing is launched except two things the owner asks for: the read-only OS queries (nvidia-smi, PowerShell Get-Disk and Get-NetAdapter, lsblk) and, only when `notify_cmd` is set, the owner's notification command.
- Local only. Any server binds `127.0.0.1`. mai-watch itself opens no outbound connection; an owner-chosen notification command may (that is its job), with its own credentials, and what it does is the owner's responsibility.
- No secrets. The tool reads and writes no credentials and holds no messaging token. Status documents must not contain them; `validate` warns on fields whose names look like secrets.
- No synthetic load. Tests never create GPU load, because running GPU work on this machine needs a separate approval (see section 12).
- Paths come from configuration. Nothing depends on a user name, a drive letter, or a non-ASCII path.

## 11. Configuration

One TOML file (`tomllib` is in the standard library from Python 3.11): status directory, output directory, `interval_s`, thresholds, per-device `baseline_memory_mib`, notifier list. A documented default is written by `python -m mai_watch init` into a directory the user names.

## 12. Testing

Principle (known-answer first): every behavior has an input whose correct output is known before the code is written.

- Contract tests: valid and invalid status documents (committed under `schema/examples`) are checked against the JSON Schema by an independent validator, and by the runtime validator; both must agree on every example.
- Parser tests with fixed `nvidia-smi` outputs: both idle, one busy, a process list with `[N/A]`, `[Insufficient Permissions]`, a missing tool, empty output, a single GPU, a malformed row.
- Idle detection tests on time series with known intervals, including flapping around the threshold, a status document that goes stale, and a clock step.
- Mutation tests: for each rule, a deliberately broken variant must make at least one test fail. A test suite that passes on a broken rule is itself a defect.
- Cross-platform: the same tests run on Windows and Linux. The planned Linux migration is the second environment.
- Real-device check is read-only: run the collector while real work happens and compare the snapshot with `nvidia-smi` read at the same time. No load is generated for the test.

## 13. Packaging and distribution

- Location: `tools/mai-watch/` in vfxpedia/mai-tools (the Python package inside is still `mai_watch`). Run as `python -m mai_watch` from that folder. Dependencies: standard library, optional `psutil` and `pynvml`.
- The schema is versioned independently of the code. A breaking change increments `schema_version`.
- Distribution to other people is a later step: README, license, tests, and a tagged release. The license is the owner's decision (open question 2).

## 14. Milestones

| Milestone | Content | Exit criterion |
|---|---|---|
| M0 | This design, the status schema, valid and invalid examples, a contract test | Contract test passes; every invalid example is rejected for the stated reason. Committed. |
| M1 | Collector, parsers, idle detection, event log, `check`, fixtures, mutation tests | All tests pass on Windows; mutation tests fail the broken variants. |
| M2 | Static viewer and local serve | Rendered check on 1920, 1366 and 390 px wide, light and dark. **Done in part 10/18**: rendered in Chrome at about 1456 px and at 390 px (same-origin iframe), light mode, no console errors, no horizontal page overflow at 390 after one fix. Not rendered: dark mode, 1366 px, Edge, Firefox. |
| M3 | Real-device read-only check; notifier interface; a notifier plugin interface | Snapshot agrees with `nvidia-smi` within one sampling interval during real work. |
| M4 | independent verification, Linux run, README and license, tagged release | the reviewer reports no blocking finding; same tests pass on Linux. |

## 14a. M1 status and the first project's additional requirements (10/17, folded in 10/18)

M1 is implemented in `mai_watch/` (`status.py`, `nvidia.py`, `idle.py`, `collector.py`, `cli.py`). Tests: `python -I tests/test_mai_watch.py` (35, including mutation tests) and `python -I tests/test_schema_contract.py` (7). Read-only run against the real `nvidia-smi` on the test workstation on 10/18: both GPUs listed, memory within 1 MiB of a simultaneous `nvidia-smi` read, utilization within noise (2 and 5 against 0 and 6 a few seconds apart). That is a smoke check, not the M3 criterion.

| Lead requirement | Where it is |
|---|---|
| Per-GPU user processes and the time a GPU went idle | Snapshot device: `processes` (raw list), `user_processes` (view filtered by `ignore_processes`, never used for idle), `idle`, `idle_since` (first sample of the condition), `idle_for_s`, `idle_candidate_since`, `idle_reason` |
| Execution evidence: heartbeat age, artifact modification time, first progress | Snapshot workload: `heartbeat_age_s`, `artifact_mtime`, `artifact_age_s`, `first_progress_at` (first artifact mtime after `started_at`, or first `progress.done > 0`, then kept). New optional status field `artifacts` (list of paths, additive in schema v1) |
| Detection outside sessions | The collector is a standalone process that needs no agent session. Starting it at logon is open decision 3 and needs the owner's approval; until then someone runs `python -m mai_watch collect` |

Not done in M1, stated plainly: NVML source (pynvml is not installed, so it cannot be verified), the viewer (M2), the notifier, the registration of automatic start. A lock whose process cannot be checked is kept, never taken over (on Windows without psutil, `os.kill(pid, 0)` would terminate the process, so it is not used).

## 14b. M2 status (10/18)

`mai_watch/viewer.html` (one file, inline script and style, no external request, data written only as text, never as HTML) and `mai_watch/server.py`. `python -m mai_watch serve --config <file>` listens on `127.0.0.1:28765` by default and serves exactly five things: the page, `snapshot.json`, `collector_heartbeat.json`, `events.jsonl`; everything else, including `state.json`, is 404. The default port is 28765 because Windows had reserved the 8747 to 8846 range on the reference machine (a bind to 8765 failed with access denied); a bind error now prints that hint. A failed fetch shows a visible error instead of an empty page, and a stale collector heartbeat turns the top pill red (seen working: a one-shot collect left the pill at "stale" after 3 intervals, which is the designed behavior). Tests: loopback bind, the four-file whitelist, path traversal attempts, no external URL, no `innerHTML`, no em dash.

## 14c. Independent review, findings W1 to W5 (each probe is now a test)

| ID | Finding | Rule now |
|---|---|---|
| W1 | Two samples an hour apart with utilization 0 made an idle hour | A gap longer than `max_gap_s` (default 3 intervals, at least 30 s) is unobserved time. It cuts the candidate run; an open interval closes at the last observed sample with reason `observation_gap` and the unobserved seconds recorded. A clock step backwards is ignored; a step forwards shows up as a gap |
| W2 | Missing (None) samples after a low one still gave idle, because the average dropped them | An unknown sample is neither idle nor busy: it never reuses older low samples, cuts the candidate run, and an open interval closes as `unobservable` after `idle_resume_s` |
| W3 | With no GPU data from the first cycle, `check` had no alert | `require_gpu_source` (default true) raises `source_unavailable` even on the first cycle; `false` is for hosts without a GPU. `expected_device_uuids` raises `device_missing` for a device that never appeared |
| W4 | A fresh heartbeat next to an empty or old snapshot read as healthy | `check` also needs the snapshot schema and lists, a `generated_at` that belongs to the heartbeat cycle (within 1.5 intervals), the same collector run (pid and start time) and a time that is not in the future; a future heartbeat is `collector_clock`. Otherwise `snapshot_invalid` |
| W5 | `2026-99-99` passed validation and crashed the cycle | Times are parsed as real calendar times and numbers must be finite; one bad document is isolated as `workload_invalid`; a repeated `id` makes the later file invalid; a heartbeat more than `future_tolerance_s` ahead sets `future_heartbeat` and the alert `workload_clock_skew` |

Documentation corrections from the same review. A document whose state is `done` or `failed` has `liveness: ended` and is never stale, and a stale document never supplies a `hold_reason` (this was already so in the code; sections 4, 6 and 7 apply it). A fresh `running` document means the writer says it is running; it is not proof that the GPU makes progress, and heartbeat age, artifact age, first progress and measured utilization are shown side by side and never merged into one verdict. Viewer and server treat labels, hold reasons and process names as untrusted text, and the server serves exactly four paths. The tool name `mai-watch` is decided (section 17 item 1 is closed).

## 14d. Independent review (Datadog comparison), findings M01 to M07 (each probe is now a test)

the reviewer reproduced seven defects in mai-watch 49af062 (report kept in the private project repository). All seven were reproduced from its probe inputs before being fixed.

| ID | Finding | Rule now |
|---|---|---|
| M01 | GPU output that was all malformed gave `devices=[]`, `source=nvidia-smi`, `check=[]` | Output with no valid device row is a broken source (`source_unavailable`); partly malformed output raises the alert `source_problem` |
| M02 | An artifact path with an embedded NUL crashed the cycle; a huge JSON integer crashed validation | The OS refusing a path means a missing artifact; `validate` never raises and a number too large for a float is invalid |
| M03 | The viewer showed a future or malformed heartbeat and a snapshot from another run as green | Judgment moved into `viewer-health.js`, a pure function checked against Python `check` on 11 shared cases (good, no heartbeat, future, stale, malformed time, infinite interval, empty snapshot, old snapshot, other run, future snapshot, no snapshot); the page is red unless the list is empty |
| M04 | A running workload whose document vanished left no event and no alert | `workload_disappeared` event once and an alert for `missing_alert_s` (default 24 h); `workload_reappeared` when it returns; a finished job whose file is removed is not an alert |
| M05 | A new run of the same id inherited the old run's `first_progress_at` | Progress is kept per run (id and `started_at`) |
| M06 | `interval_s = Infinity` in the heartbeat made a 100-day-old sample pass | The interval must be a positive finite number, else `collector_missing` |
| M07 | A failed process query was shown as zero processes and no problem | A failed query gives an unknown list (`processes_known: false`, shown in the viewer) and a `source_problem` alert; an empty answer stays a known empty list |

Also from the review: the server serves `events.jsonl` as its last 128 KiB only, and `viewer-health.js` is the fifth path it serves. Not done, stated: clocks, power limit, P state and clocks-event bitmask fields; the idle report (the review says events alone cannot give an exact idle total, because the snapshot is overwritten and events hold transitions only, so a small metric history comes first); host metrics display; real-work M3; Linux run; viewer state rendering in dark mode and other widths.

## 15. Verification handoff

Requested after M1, not before: the reviewer checks that the tests are not tautologies (the expected values do not come from the code under test), that each mutation really changes behavior, and that the parser tests cover the measured WDDM output in section 5. Because pipeline's Codex budget is low, the request will be one document with the exact commands and the expected results, not a conversation.

## 16. Differences from the original proposal

| Original | Change | Reason |
|---|---|---|
| Name and scope: GPU monitor | General resource and workload monitor | Owner's direction; the schema is not RL-specific |
| Idle when no job process is running | Idle from utilization plus status documents; process list not used | Measured: the list is never empty under WDDM |
| UUID only in the collector | UUID required in status documents too | CUDA and nvidia-smi index orders can differ |
| No collector self-monitoring | Heartbeat, stale threshold, single-instance lock, supervision | A silent monitor looks like a quiet system |
| Alerts read at hourly heartbeat | Files first; a shared notifier later | Hourly reads delay a 10-minute alert by up to an hour |
| Korean terms for ledger and adapter fields | Standard English terms | Owner's direction |

## 17. Open decisions (owner)

### 0.3 bounded local UX extension

Approved scope: mai-os#55, owner conversation 2026-10-23. CPU grid is approximately half the measured former height, keeping the host grid intact. A background CPU scan every five seconds compares cumulative user/system time by PID plus creation time; first and stale scans are unknown, one core is 100%. It never requests command lines. A stalled scan cannot spawn a second scan, and a result older than fifteen seconds is withheld.

`product.py` owns identity-free diagnostic reconstruction and an in-memory incident set capped at 256 records / 24 hours. Safe exports copy only named numeric fields and generic strings authored by the program, never raw diagnostic strings or dictionaries. Normal live payloads remain private operational data. The single existing judgment list is decorated, not replaced, and unknown observations do not clear an incident. Continuous duration restarts after unknown or a sample gap exceeding max(3 intervals, 5 seconds).

Browser preferences select 1/5/10-minute retained graph windows, resource emphasis and supporting-table expansion. They never hide warnings or quota summaries. No database, external telemetry, internet authentication or remote action interface is introduced. Incident history resets on restart; this limitation is visible in the viewer. Retained samples also have an absolute 36,000-entry cap.

1. ~~Tool name~~ decided: `mai-watch` (folder), `mai_watch` (Python package).
2. License for distribution.
3. Registering the collector for automatic start on Windows logon (changes the machine).
4. Whether and when a terminal notifier is enabled.
