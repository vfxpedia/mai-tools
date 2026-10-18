Status: draft (M1). 43 + 2 tests pass on Windows, Linux (WSL and CI) and macOS (CI). Not measured: use inside a real launcher.

[한국어](README.ko.md)

# mai-approve

A standing approval that the owner writes once, with an expiry, so that an unattended run can ask "am I allowed to start this?" without waking anyone up.

- The owner runs `grant`: which folders, which devices, how many runs per experiment unit, until when. The file is sealed with a SHA-256 hash.
- A launcher runs `receipt` right before it starts a run. It is refused when the approval is missing, expired, revoked, for another folder, for an excluded action, or when the unit has used its runs. A new run id does not reset the count.
- Every change is appended to a hash-chained audit log.

It is a coordination and audit tool, not a security boundary: a process running as the same OS user can write the same files.

## Try it in five minutes

Use a throwaway store so nothing real is touched. Run from `tools/mai-approve`. PowerShell shown; on Linux or macOS use `export MAI_APPROVE_DIR=...` and `/` paths.

```powershell
$env:MAI_APPROVE_DIR = "$HOME\mai-approve-demo\store"
mkdir "$HOME\mai-approve-demo\lab\runs" -Force | Out-Null
$lab = "$HOME\mai-approve-demo\lab"

# 1. the owner grants for one day: one run per experiment unit, unattended allowed
python -m mai_approve grant --scope demo --days 1 --allowed-path $lab --runs-per-unit 1 --unattended `
  --eula-accept --eula-license "Example License" --eula-subject owner --eula-source "typed by the owner"

# 2. a launcher asks before starting: allowed (exit 0)
python -m mai_approve receipt --scope demo --unattended --path "$lab\runs" --experiment-unit exp-1 --attempt-kind normal --run-id run-1

# 3. the same unit again with a new run id: refused, "runs_exhausted" (exit 2)
python -m mai_approve receipt --scope demo --unattended --path "$lab\runs" --experiment-unit exp-1 --attempt-kind normal --run-id run-2

# 4. a folder outside the approval: refused, "path" (exit 2)
python -m mai_approve check --scope demo --path $HOME --experiment-unit exp-1

# 5. an excluded action: refused, "excluded" (exit 2)
python -m mai_approve check --scope demo --path "$lab\runs" --experiment-unit exp-1 --action data_deletion

# 6. close the run, check the audit log, revoke
python -m mai_approve finish --scope demo --run-id run-1 --status ended
python -m mai_approve audit-verify
python -m mai_approve revoke --scope demo
```

What you should see (measured 2026-10-18 on Windows): step 1 prints `"ok": true` with `valid_until` one day ahead and the file path; step 2 `"ok": true`; steps 3 to 5 print one `mai-approve refused (...)` line and exit 2; `audit-verify` prints `"ok": true` with the number of lines; after `revoke`, `check --inquiry` answers `missing`. Delete `$HOME\mai-approve-demo` when done.

## Commands

| Command | Who | What |
|---|---|---|
| `grant` | owner | write the approval (`--until` or `--days`, max 31 days; all six exclusions on by default) |
| `extend`, `revoke`, `show` | owner | change the end, end it now, print it |
| `check` | anyone | ask without recording; `--inquiry` only asks whether the approval is live |
| `receipt` | launcher | ask and record the run; this is the gate a launcher must use |
| `finish` | launcher | record how the run ended |
| `audit-verify`, `audit-head` | owner | verify the hash chain; record the head elsewhere to also catch a cut-off tail |

Default store: `~/.mai/approvals`, or the folder in `MAI_APPROVE_DIR`. Exit code 0 means allowed, 2 means refused (reason in JSON on stdout).

## Rules worth knowing

- Paths are compared after resolving links and junctions. An approval written on one operating system is refused on another (`foreign_path_notation`); grant again on the new machine.
- Six action categories are excluded unless the owner removes them: paid or external resources, data deletion, killing foreign processes, system or security settings, external sends, out-of-scope experiments.

Design and review history: [DESIGN.md](DESIGN.md). Tests: `python -I tests/test_cli.py`, `tests/test_hardening.py`, `tests/test_schema_contract.py` (needs `jsonschema`).
