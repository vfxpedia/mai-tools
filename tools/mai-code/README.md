> Classification: Tool usage
> Author: MAI maintainers · 2026-10-18
> Basis: mai-tools #1 · mai-os #49 · official local CLI contracts
> Summary: Analyze paper extracts and implement bounded modules with existing CLI login and retained evidence
> Status: Draft alpha 0.1.0a1. Windows native fixtures and three-OS offline CI measured; final maintainer review pending

# mai-code

mai-code prepares an owner-authored work unit, runs **official logged-in Codex or Claude Code** in an existing dedicated Git worktree, and retains original inputs, requests, raw streams, native session IDs and fixed-test receipts. It does not route provider APIs, copy credentials or replace your current conversations. It is not the upstream DeepCode product.

## Try without installation

Clone this repository at a reviewed revision. Enter `tools/mai-code`, then:

```text
python -m mai_code --help
python -m mai_code doctor
python tests/live/native_probe.py --root <absolute-empty-fixture-directory> --engine codex
```

The last command creates **only a labelled local test Git repository, worktree, unit and evidence packet**. It does not call a model without `--execute`. It never deletes the fixture. Python 3.11+, Git and the selected official CLI must already be installed. Run native login yourself if doctor cannot confirm a subscription. No key, token, configuration file or login is copied. Doctor runs only CLI version, help and auth-status commands, not model work.

Optional isolated installation, using an existing build backend (no network dependency installation):

```text
python -m venv --system-site-packages <new-venv>
<venv-python> -m pip install --no-index --disable-pip-version-check --no-build-isolation --no-deps .
<venv-mai-code> --help
```

Do not install globally to try it. If the build backend is missing, stop and install it yourself in the isolated environment. Uninstall with that environment's `python -m pip uninstall mai-code`; retain `.mai/mai-code` evidence and native session logs. Removing the package does not remove work or history.

## A real paper unit

The lead supplies the **exact paper/extract version, section/equation references, project Issue, module boundary, owned linked worktree and immutable test oracle**. For MARG, START or AME-2, first analyze the source, do not assume a paper identity or claim a reproduced method from its acronym. Use the fixture builder as a schema example, replace its TEST ONLY source/contract with approved extracts, and compute each file's SHA-256 before preparation. Include all scientific acceptance details in `contract`, whose required keys are `module`, `negative_test_id` and positive integer `negative_failures`.

Units use schema `mai-code-unit-v1` and exactly these fields: `schema`, `unit_id`, `issue_url`, absolute native `workspace`, nonempty `inputs` (`path`, lowercase SHA-256, nonempty `references`), `contract`, `outputs`, `engines`, `test_argv`, `test_framework` (`unittest`), `negative_control_argv`. `engines` supplies analyze/plan/implement, each with `engine` (codex/claude) and optional explicit `model`. The first two outputs are new analysis and plan JSON paths; remaining paths are implementation files. All are relative to the linked worktree. Do not list a test oracle as a writable output. Unknown unit keys, dirty/shared checkouts and escaping/foreign-OS paths fail.

```text
mai-code prepare <unit.json>
mai-code status <reported-run-path>
mai-code run <reported-run-path> --through analyze
mai-code run <reported-run-path> --through plan
mai-code run <reported-run-path>
mai-code verify <reported-run-path> --existing
```

`--through analyze` is the structure-review path for the lead. It does not implement a module. Preparation and status make no model call. Analysis and planning models must not edit workspace files; mai-code saves their validated JSON. The final run implements only declared output paths, then runs the **owner's fixed argv**, never a model-written shell command. Tests execute with no shell expansion and no dependency installer. An exit code alone is insufficient: verification requires nonzero unittest discovery and the declared negative-control assertion failure with zero unexpected errors.

## Failure and resume

Exit codes: 0 requested operation succeeded, 1 deterministic verification failed, 2 invalid/refused/incomplete operation. A prepared or analysis-only unit is **not** a passed implementation. A standalone verifier can pass its tests without marking incomplete stages as unit-passed.

For an ordinary stopped boundary use `mai-code run` or `mai-code resume`. A failed closed attempt can use `resume` only with its exact recorded native UUID, unchanged inputs/workspace and known process exit. No global `--last`, `--continue`, engine switch or automatic retry. A missing receipt or unknown lease requires human reconciliation; the tool never deletes a stale lease by guessing a PID is dead. Do not remove a lease while a child could still run. Preserve the original run and create a newly approved unit for changed inputs or acceptance criteria.

Workspace leases live in `.mai-code-locks` beside the physical worktree directory, keyed by its normalized absolute path. Different `--data-root` directories therefore share one lease. Its parent must be writable; a linked lock directory is refused. Old-format leases in an evidence root still block execution and are not migrated or removed automatically. Stop all old-version workers before using a new version on the same worktree. A failed attempt from an older version without a pinned receipt hash requires manual reconciliation.

Starting verification again invalidates the previous success before launching any test. An interrupted or failed launch cannot reuse that success; its previous receipt remains on disk. Unknown child liveness retains the workspace lease. Inspect and reconcile the incomplete attempt explicitly. Worktrees containing Git submodules/gitlinks are currently refused because their nested files are not covered by this version's inventory.

If Claude's native permission layer refuses an implementation write, the owner can explicitly grant only a declared file for that invocation: `mai-code resume <run-path> --allow-write module.py`. Repeat the flag for individually approved outputs. No wildcard, traversal, input, analysis/plan output or undeclared path is accepted. This creates a native `Edit(exact-path)` rule, which Claude uses for Write too, not a global setting or bypass mode. On Windows the rule's drive is normalized as `/c/...`, per the official permission contract. Existing deny/ask rules can still refuse it. Never substitute a shell write for a native refusal.

When a call exceeds its attention threshold, `attempts/<id>/lifecycle.jsonl` records the live PID and attention event while both streams continue draining. This is **not cancellation or completion**. `status` reports the current attempt. Native permissions can refuse a write, especially in non-interactive mode. Do not disable permissions/hooks to turn a refusal into success.

## Limits

- No model/account switching, quota bypass, scheduled wake-up, automatic repair, GPU training, package downloads, Git commit/merge/push, process termination or release publication.
- No USD calculation. Native usage and engine-provided USD are retained only when supplied.
- Native compaction can still occur. Retaining raw records does not put every historical token in active model context.
- File hashes detect contract violations after a call; they are not a sandbox, signature, approval or defense against the same OS user. Native controls still apply.
- Private paper extracts and raw logs stay outside Git by default. Inspect them before sharing. Run IDs/paths in examples are placeholders.
- See [DESIGN.md](DESIGN.md) for measurements and [THIRD_PARTY.md](THIRD_PARTY.md) for provenance. Draft means native/platform gates not yet all complete, not production-certified science.
