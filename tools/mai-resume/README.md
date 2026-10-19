# mai-resume

[한국어](README.ko.md)

Warns AI coding sessions shortly before a plan limit runs out, and wakes them again after the limit resets.

A session that hits its limit stops in the middle of work, and nothing inside the session can wake it: its own scheduled
reminders do not fire while the limit holds. mai-resume runs outside the sessions, so it is still alive when they stop.

## What it does

Every minute (`poll_s`) it:

1. lists the live agent panes in [Orca](https://www.onorca.dev) (`orca terminal list`), so new sessions are picked up
   without a hand-kept list. Claude panes and Codex panes are told apart by Orca's agent identity; each engine follows its
   own plan limits.
2. reads the plan limits file (`~/.mai/limits.json`, written by the mai-gauge status line) and each pane's screen.
3. **warns** every session of an engine once per limit window when the window passes `warn_pct` (93 % for five_hour,
   95 % for seven_day): finish up to a safe point, write a HANDOFF, stop, leave GPU jobs alone. A session that appears
   later in the same window gets the warning too. If the limits file is older than `limits_stale_s`, the lower
   `stale_warn_pct` is used, so a late file makes the warning early rather than late.
4. books a **resume** for any pane whose screen already says `You've hit your ... limit . resets <time>`, even when the
   limits file never showed the window filling up.
5. **resumes** every warned or stopped session once, `resume_grace_s` after the reset: re-read the HANDOFF and continue.

## Delivery rules

- Nothing is typed into a prompt that already holds text. Orca's screen read does not show unsubmitted text in a Claude
  prompt, but the prompt row's trailing space goes from 1 to 0 while text is there; mai-resume reads that, and looks again
  right before sending. A message that waits longer than `defer_give_up_s` is dropped and logged.
- A pane that is working gets the message as a queued prompt (Claude runs it after the current turn).
- The same message id (pane, kind, window) is never sent twice. Messages are one line, sent with the Orca executable and
  an argument list, never through a shell (through cmd a multi-line message was cut at its first line).
- One instance per machine (a localhost port lock). A heartbeat is written every round; a restart after an unexpected
  stop sends an alert through `notify_cmd`.

## Install

Python 3.9 or newer, no other packages.

```
pip install -e tools/mai-resume
mai-resume run --once --dry-run      # one round, logs what it would send, sends nothing
mai-resume status                    # heartbeat check, exit 1 when stale
```

Start at logon without a window:

- **Windows**: `powershell -ExecutionPolicy Bypass -File tools/mai-resume/autostart/register-windows.ps1 -Pythonw <pythonw.exe>`
  registers the scheduled task `mai-resume` (logon trigger plus a 5-minute repeat that restarts it if it is not running).
- **Linux**: `tools/mai-resume/autostart/mai-resume.service` is a systemd user unit; the steps are in its header.
- **macOS**: run `mai-resume run` from a LaunchAgent (not packaged yet).

## Files and settings

Everything lives in `~/.mai/resume/`: `config.json` (optional), `state.json`, `resume.log`.

| key | default | meaning |
|---|---|---|
| `warn_pct` | `{"five_hour": 93, "seven_day": 95}` | warn when a window reaches this percent |
| `stale_warn_pct` | 85 | used instead while the limits file is stale |
| `limits_stale_s` | 600 | limits older than this are stale |
| `resume_grace_s` | 180 | resume this long after the reset |
| `poll_s` | 60 | seconds between rounds |
| `defer_give_up_s` | 1800 | drop a message that could not be delivered for this long |
| `messages` | English text | `warn` and `resume` templates; `{now} {engine} {window} {pct} {reset}` |
| `only_handles` / `exclude_handles` | none | limit the guard to, or leave out, these Orca terminal handles |
| `notify_cmd` / `notify_file` | none | alert sender (text on stdin; `notify_file` is written first) |
| `orca` | found on PATH | the Orca CLI executable (`orca.exe` on Windows, `orca-ide` on Linux) |

## Tests

`python -I tests/test_core.py` (decisions with known inputs) and `python -I tests/test_runner.py` (retry, one instance,
restart alert, status, re-check before sending, with a fake Orca). Both run in `common/run_all_tests.py`.

## Known limits

- The typing check reads one screen row; it was measured on Claude Code 2.1.303 in Orca 1.4.230. A different terminal
  layout can change it. Codex prompts are read by their visible text and known placeholders only.
- Between the last look and the send there is still a moment (well under a second) in which a person could start typing.
- It needs Orca: panes outside Orca are not seen.
