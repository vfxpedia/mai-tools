# Changelog

## Unreleased

- Added mai-code draft alpha: strict units, linked-worktree checks, immutable stage evidence, exact native session continuation and owner-fixed unittest verification. No provider API billing, automatic Git mutation or global installation. Native and platform gates are recorded separately in its DESIGN.md.

- Added the session mods `mods/mai-gauge` (Claude Code, marketplace `mai-mods` at the repository root, ids unchanged) and `mods/mai-codex-gauge` (Codex 0.2.2), with test data scrubbed of personal names and paths and English READMEs; detailed Korean guides kept as README.ko.md.

- Naming rule: Python package `maiwatch` is now `mai_watch` (`python -m mai_watch`), config file `mai-watch.toml`, snapshot id `mai-watch-snapshot-v1`; mai-approve ids are `mai-approve-approval-v1` and `mai-approve-receipt-v1`, the old ids are still read.

- First import of mai-approve, mai-watch and mai-tabs, with the findings of two independent review rounds each fixed with a reproducing test.
- Fixed after the first cross-system review: the viewer named a wrong-shaped snapshot as a file read failure and dropped the real heartbeat (now named for what it is, tested through the real page script); a Windows process path was not reduced to its file name on Linux; mai-approve refuses approvals and requests written in another operating system's absolute path notation.
- Added the hygiene gate, the all-tests runner and the CI matrix.
