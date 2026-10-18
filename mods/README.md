# mods

Add-ons that run inside AI coding sessions, so a session can be left alone for a while without losing track of its context, limits, cost or work. Unlike the tools in `tools/`, these are loaded by the session engine itself.

| Mod | Engine | What it does | Status |
|---|---|---|---|
| [mai-gauge](mai-gauge/) | Claude Code | A strip above the prompt and `/gauge`: context use against the compact threshold, 5 hour and 7 day limits with a forecast, this turn's requests, tokens and cost. 50, 75 and 85 % notices, compact at a turn boundary above 85 %. A shared session board (`/sessions`). Holds five history-destroying git commands for an explicit yes (deletes and process kills: see the guide). | in daily use by its author; 81 tests |
| [mai-codex-gauge](mai-codex-gauge/) | Codex | Turn and session tokens and account limits from what the engine reports; cost only when the engine reports it. Same session board format as mai-gauge. | 0.2.2; 112 tests pass, 5 skipped; compact control at a work-unit boundary and some native hook behavior are not finished |

Detailed guides are in Korean for now: [README.ko.md](README.ko.md) for mai-gauge and [mai-codex-gauge/README.ko.md](mai-codex-gauge/README.ko.md). English versions are pending.

## Install mai-gauge (Claude Code)

```
/plugin marketplace add vfxpedia/mai-tools
/plugin install mai-gauge@mai-mods
```

The marketplace name stays `mai-mods` and the plugin name stays `mai-gauge`, so an existing install keeps its id. In a session that is already running, type `/reload-plugins`; no process has to be stopped.

## Install mai-codex-gauge (Codex)

From `mods/mai-codex-gauge`: `node src/setup.mjs plan`, then `install`, `doctor` and, if needed, `rollback` with the manifest that `install` wrote. Read the Korean guide first: installing changes the Codex home of the current terminal and asks the owner to trust exactly eight hooks.

## Where they write

Everything goes under the user's home in `.mai/` (`sessions/`, `units/`, `costlog/`). Nothing is written into a repository.

## Checks before a change

```
claude plugin validate mods/mai-gauge
claude plugin test mods/mai-gauge
npx -p typescript tsc -p mods/mai-gauge --noEmit      # needs the engine's type files, see below
cd mods/mai-codex-gauge && node --test tests/*.test.mjs
```

The type check needs `mods/mai-gauge/.claude-plugin/types/`, which Claude Code writes when it loads the mod (about 20 000 lines, not kept in the repository). On a machine where the mod was never loaded the type check cannot run; CI does not run it. Validate and test alone do not catch two functions with the same name; the type check does (TS2393), which once hid a three-day loss of turn cost records.

## Not measured

- mai-gauge on Linux or macOS sessions.
- mai-codex-gauge automatic compact at a work-unit boundary; whether every running Codex session uses the latest installed copy.
