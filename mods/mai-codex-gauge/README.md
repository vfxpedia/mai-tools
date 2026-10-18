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

## Tests

`node --test tests/*.test.mjs` (Node 22 or newer). 113 tests: 108 pass; 5 are skipped in a normal run because they drive a real Codex CLI or a real package install.

## Not finished or not measured

- Compact control at a work-unit boundary: the isolated tests pass, but a counterexample exists where the engine's own automatic compact runs in the middle of a unit.
- Whether every running Codex session uses the latest installed copy after an update.
- Behavior on macOS.
