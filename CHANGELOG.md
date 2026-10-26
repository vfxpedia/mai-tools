# Changelog

## Unreleased

- mai-resume: a keep-alive that waited in pending (text in the prompt) is dropped when the pane is working by the time it could go, or has finished a newer turn since it was decided. On 10/26 one decided at 15:46 went in at 16:13 into a working session, which answered idle and stopped. The default keep-alive text now says to carry on with work in progress and reply idle only when there is none. Owner rule (10/26): keep-alive only for a pane resting after a finished turn; a nudge not delivered within `keepalive_stale_s` (300 s) is dropped and the next round decides again; on a resting Claude pane the gray suggestion shown after the marker no longer counts as typing for the keep-alive (warn and resume still wait on any visible text). The site pane had waited behind a suggestion 17 times on 10/26.

- mai-resume: `fallback/limit_guard.py`, the first prototype kept as a Claude-only standby that sends nothing while mai-resume holds its lock port 127.0.0.1:28766 and takes over when the port is free. The check binds the port instead of connecting, because mai-resume listens with a backlog of one and never accepts, so connect probes time out while it is alive (measured 10/26). Example config, tests.

- mai-resume: opens the codex gauge (`mai-codex-gauge watch --session <id>`) in a split next to each allow-listed codex pane that has none, once per pane incarnation; the session id comes from the gauge's own `~/.mai/sessions` files, a tab that already shows the gauge (title Mods or its rows in the preview) gets none, and a gauge pane the owner closes is not opened again.

- mai-resume: right before typing, the guard also compares the prompt row with this round's first read; if it moved, someone is typing and the message waits a round (same rule as `send`).
- mai-watch viewer: a plan limit reading older than 30 minutes is shown grey with «old reading (N h ago), may have reset» instead of a hot meter. Codex records its limit only when a codex turn runs, so after an early reset the page kept showing 86 % hot for 10 hours.

- mai-resume: `send` command for one line into another session, only when nobody is typing there (empty prompt, same screen twice 5 s apart, checked again right before sending; exit 4 when it never goes quiet).

- mai-resume: an allow list file (`~/.mai/resume/targets.txt`, read every round) limits which panes get anything; the resume message asks to continue only work the limit stopped and otherwise reply idle, the keep-alive asks for the word idle and no work. A message given up after 30 min is not queued again, and a pane gets one resume per reset.

- mai-resume: the seven-day window stops sessions only at 98 %; from 85 % it sends a keep-working notice. A stale limits reading never stops anyone and sends only the notice, marked as old. A window already stopped gets no later notice. Before, a stale codex reading at 85 % stopped four codex sessions for five days with 14 % of the week unused.

- Added mai-resume: warns AI coding sessions in Orca before a plan limit runs out, wakes them after the reset and nudges idle Claude sessions every 55 minutes so their prompt cache survives (not while a limit holds). Finds sessions from Orca itself, follows each engine's own limits, reads the stopped-limit screen line, never types into a prompt that holds text (trailing-space check measured on a real pane, re-checked right before sending), one instance per machine, heartbeat and restart alert. Windows scheduled task and Linux systemd user unit under `tools/mai-resume/autostart`.

- Added mai-code draft alpha: strict units, linked-worktree checks, immutable stage evidence, exact native session continuation and owner-fixed unittest verification. No provider API billing, automatic Git mutation or global installation. Native and platform gates are recorded separately in its DESIGN.md.

- Added the session mods `mods/mai-gauge` (Claude Code, marketplace `mai-mods` at the repository root, ids unchanged) and `mods/mai-codex-gauge` (Codex 0.2.2), with test data scrubbed of personal names and paths and English READMEs; detailed Korean guides kept as README.ko.md.

- Naming rule: Python package `maiwatch` is now `mai_watch` (`python -m mai_watch`), config file `mai-watch.toml`, snapshot id `mai-watch-snapshot-v1`; mai-approve ids are `mai-approve-approval-v1` and `mai-approve-receipt-v1`, the old ids are still read.

- First import of mai-approve, mai-watch and mai-tabs, with the findings of two independent review rounds each fixed with a reproducing test.
- Fixed after the first cross-system review: the viewer named a wrong-shaped snapshot as a file read failure and dropped the real heartbeat (now named for what it is, tested through the real page script); a Windows process path was not reduced to its file name on Linux; mai-approve refuses approvals and requests written in another operating system's absolute path notation.
- Added the hygiene gate, the all-tests runner and the CI matrix.
