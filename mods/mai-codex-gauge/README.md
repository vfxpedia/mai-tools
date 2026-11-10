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

## Tests

`node --test tests/*.test.mjs` (Node 22 or newer). 117 tests: 112 pass; 5 are skipped in a normal run because they drive a real Codex CLI or a real package install.

## Not finished or not measured

- Compact control at a work-unit boundary: the isolated tests pass, but a counterexample exists where the engine's own automatic compact runs in the middle of a unit.
- Whether every running Codex session uses the latest installed copy after an update.
- Behavior on macOS.
