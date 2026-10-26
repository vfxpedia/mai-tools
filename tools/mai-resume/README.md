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
3. **stops** every session of an engine once per limit window when a fresh reading passes `warn_pct` (93 % for
   five_hour, 98 % for seven_day): finish up to a safe point, write a HANDOFF, stop, leave GPU jobs alone. A session that
   appears later in the same window gets it too. Between `notice_pct` (85 % for seven_day) and the stop, it sends a
   **notice** once instead: keep doing the current work (owner 10/20). A reading older than
   `limits_stale_s` never stops anyone: at `stale_warn_pct` or above it sends only the notice, marked as old. A window
   that was already stopped gets no later notice. (10/20: a stop at seven_day 85 % would have left codex idle for five
   days with 14 % unused.)
4. books a **resume** for any pane whose screen already says `You've hit your ... limit . resets <time>`, even when the
   limits file never showed the window filling up.
5. **resumes** every warned or stopped session once, `resume_grace_s` after the reset: re-read the HANDOFF and continue.
6. **keeps the prompt cache alive**: a Claude session that has been idle for `keepalive_s` (55 minutes, inside the
   one-hour cache lifetime) gets one short nudge. Idle means the end of its screen shows the `done hh:mm` line Claude Code
   leaves after a turn and no progress mark. A working session keeps its own cache, so its clock just restarts; any
   warning or resume message also counts as a nudge. No nudge while a limit window is held (warned, before the resume)
   or the pane shows the limit line: requests are refused then, so a nudge keeps no cache and only spends the limit.
   A pane seen for the first time only starts its clock.

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
| `warn_pct` | `{"five_hour": 93, "seven_day": 98}` | stop when a fresh reading reaches this percent |
| `notice_pct` | `{"seven_day": 85}` | keep-working notice from this percent up to the stop |
| `stale_warn_pct` | 85 | a stale reading at or above this sends only the notice |
| `limits_stale_s` | 600 | limits older than this are stale |
| `resume_grace_s` | 180 | resume this long after the reset |
| `poll_s` | 60 | seconds between rounds |
| `defer_give_up_s` | 1800 | drop a message that could not be delivered for this long |
| `keepalive_s` | 3300 | nudge an idle Claude session after this long; 0 turns it off |
| `messages` | English text | `warn`, `resume` and `keepalive` templates; `{now} {engine} {window} {pct} {reset}` |
| `only_handles` / `exclude_handles` | none | limit the guard to, or leave out, these Orca terminal handles |
| `targets_file` | `~/.mai/resume/targets.txt` | allow list, read every round: one pane id per line (whole handle or its start, `#` starts a note). If the file exists only those panes get anything, an empty file means none; without the file every pane is watched and the log says so. Added 10/20 after resume and keep-alive restarted long-finished work in old sessions |
| `notify_cmd` / `notify_file` | none | alert sender (text on stdin; `notify_file` is written first) |
| `orca` | found on PATH | the Orca CLI executable (`orca.exe` on Windows, `orca-ide` on Linux) |

## Tests

`python -I tests/test_core.py` (decisions with known inputs) and `python -I tests/test_runner.py` (retry, one instance,
restart alert, status, re-check before sending, with a fake Orca). Both run in `common/run_all_tests.py`.

## Fallback guard (`fallback/limit_guard.py`)

The first prototype of this guard, kept as a standby for Claude sessions. It sends the same three kinds of message
(stop before the limit, resume after the reset, keep-alive) but **only while mai-resume is not running**: every round it
tries to bind mai-resume's lock port `127.0.0.1:28766` and, if that port is already in use, it sends nothing and records
no warning (one `STANDBY` line in its log). When the port is free it logs `ACTIVE` and takes over. One pane, one tool:
list the same Claude sessions here only as the standby.

It checks by binding, not by connecting: mai-resume listens with a backlog of one and never accepts, so connect probes
fill the queue and then time out while mai-resume is alive (measured 10/26; `tests/test_fallback.py` reproduces it).

```
mkdir -p ~/.mai/limit-guard && cp tools/mai-resume/fallback/config.example.json ~/.mai/limit-guard/config.json   # then fill sessions
python tools/mai-resume/fallback/limit_guard.py --once --dry     # one round, sends nothing
python tools/mai-resume/fallback/limit_guard.py                  # loop every poll_s
```

Files: `~/.mai/limit-guard/config.json`, `state.json`, `guard.log`, keys as in `config.example.json`
(`primary_lock_port` 0 turns the check off). The Orca CLI is `ORCA_CLI_COMMAND`, else `orca.exe` under
`%LOCALAPPDATA%\Programs\orca` on Windows and `orca-ide` elsewhere (the bare `orca` on Linux is the GNOME screen reader).
It reads Claude limits only and has no typing check of its own, which is why it stays silent while mai-resume runs.
Tests: `python -I tests/test_fallback.py`.

## Known limits

- The typing check reads one screen row; it was measured on Claude Code 2.1.303 in Orca 1.4.230. A different terminal
  layout can change it. Codex prompts are read by their visible text and known placeholders only.
- Between the last look and the send there is still a moment (well under a second) in which a person could start typing.
- It needs Orca: panes outside Orca are not seen.

## Sending one line to another session

`python -m mai_resume send --to <handle> --text <text> [--wait 600]` sends only when the prompt is empty and the screen reads the same twice 5 s apart, and checks once more right before sending. If the pane does not go quiet within `--wait` seconds nothing is sent and the exit code is 4. Added 10/20 after a session report was sent into a pane the owner was typing in.
