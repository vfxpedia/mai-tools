# mai-codex-gauge

A Codex plugin that shows the turn and session tokens and the account limits that Codex itself reports, and writes the same session board file as the Claude Code mod `mai-gauge` (`~/.mai/sessions/<id>.json`), so sessions of both engines can see each other. Cost in USD is shown only when the engine reports it; it is never estimated.

Version 0.2.2. Detailed guide (Korean): [README.ko.md](README.ko.md).

## Use

```
node src/setup.mjs plan    --account codex:ACCOUNT
node src/setup.mjs install --account codex:ACCOUNT
node src/setup.mjs doctor  --session EXACT_SESSION_ID --native true
node src/setup.mjs metrics --session EXACT_SESSION_ID
node src/setup.mjs rollback --manifest ABSOLUTE_BACKUP_MANIFEST
```

`install` writes a recovery manifest first and changes only the Codex home of the current terminal (`CODEX_HOME`, else `~/.codex`). The owner trusts exactly the eight hooks it installs; nothing trusts them on the owner's behalf. On Linux, `bin/bootstrap-linux.sh` installs from a package file after the owner approves.

### Companion panes for existing sessions

Run `node src/setup.mjs sync --home ABSOLUTE_CODEX_HOME --exe ABSOLUTE_CODEX_EXE --sessions ID1,ID2 --loop` once per account, alongside the individual `watch --session ID` panes. Supply only exact, existing session IDs you have verified belong to that Codex home and login. If the home has a managed provider socket, `--exe` may be omitted.

The collector checks the owned rollouts about every five seconds, reads account limits at most once per minute, and shares that display snapshot only with the listed sessions. An idle snapshot does not write to limit history or create a turn. Account limits can appear before a session sends its first prompt. Token counts remain per session and absent windows remain unavailable. This does not restart an agent, fix native hook trust, or perform checkpoint/compact actions. Omit `--loop` for a single diagnostic sync.

### Automatically attach in Linux Orca

Install the plugin and review its exact hooks. This opt-in service is for a desktop Orca terminal session using the default Codex home. Confirm the paths to Node 22+, Codex, and `orca-ide` in the unit before installing it. Use one collector for this home; do not leave an earlier manual `sync --loop` running for the same sessions.

```sh
install -Dm644 ~/.codex/mai-codex-gauge/autostart/mai-codex-gauge-sync.service ~/.config/systemd/user/mai-codex-gauge-sync.service
systemctl --user daemon-reload
systemctl --user enable --now mai-codex-gauge-sync.service
systemctl --user is-enabled mai-codex-gauge-sync.service
journalctl --user -u mai-codex-gauge-sync.service -n 20 --no-pager
```

After a trusted `SessionStart` runs in a new or resumed Codex CLI tab, the collector checks the tab, pane and terminal identities and can open a companion underneath. In versions that run the hook on the first turn, just opening a tab is not enough. The collector titles each companion `mai-codex-gauge <session ID>`. If Orca restores the tab and the titled lower pane contains only a recognized empty shell prompt, the collector sends the watch command to that pane once per shell instance. It leaves running gauges, untitled or unrelated panes, and unrecognized prompts alone. It does not replay a split or shell input after an ambiguous response. A terminal that inherits a foreign `CODEX_THREAD_ID` is refused by the hook; start a new shell or clear that inherited variable before launching a new Codex CLI.

Orca opens a new split at 50/50; its public CLI has no height option. Drag the divider once to set the lower pane to 124 px. Orca remembers the divider as part of the tab layout; the collector does not resize restored panes. Enabling the unit runs the collector on the next user login; that does not by itself start Orca or resume a Codex session. To disable automatic attachment and sync, run `systemctl --user disable --now mai-codex-gauge-sync.service`. Existing panes are not closed by this command.

## Tests

`node --test tests/*.test.mjs` (Node 22 or newer). To include isolated native lifecycle tests, set `MAI_CODEX_TEST_EXE` to the absolute path of the native Codex executable.

## Not finished or not measured

- Compact control at a work-unit boundary: the isolated tests pass, but a counterexample exists where the engine's own automatic compact runs in the middle of a unit.
- Whether every running Codex session uses the latest installed copy after an update.
- Behavior on macOS.
