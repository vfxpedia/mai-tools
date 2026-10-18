Status: draft. M0 (schema, examples, contract tests) and M1 (CLI, hardening, 43 known-answer tests) are implemented and independently reviewed on Windows and Linux (WSL). Not yet measured: integration with a real launcher, and how an AI-assisted shell treats an owner-written approval file.

# mai-approve design (M0)

Principle: **Start with myself. Validate with evidence. Generalize for others.**

## What it is

A tiny command the owner types in his own shell to write one time-limited standing approval file. Unattended runs read it. Nothing is run nightly. Agents never write it.

## Files in M0

| Path | Purpose |
|---|---|
| `schema/approval.v1.schema.json` | JSON Schema 2020-12 for `mai-approve-approval-v1` |
| `schema/make_examples.py` | Writes 3 valid, 9 invalid, 3 semantic examples. Owns the hash rule |
| `tests/test_schema_contract.py` | Schema check, semantic check, 4 mutation checks |

Run: `python -I tools/mai-approve/tests/test_schema_contract.py` (needs `jsonschema`; a missing package fails, it does not skip).

## Semantic rules the schema cannot express

JSON Schema cannot compute a hash or compare two dates, so the launcher check (M1) must enforce these, and the contract test already does:

1. `sha256` equals the SHA-256 of the canonical content (sorted keys, compact separators, UTF-8, `sha256` field removed).
2. `valid_until` is after `granted_at`.
3. The window is at most 31 days. The CLI default is 7 days.
4. `valid_until` is in the future at launch time (M1, needs a clock, not testable on a static example).

## Mapping to the first launcher's current consent file (as reported by the launcher team, not re-read)

| Current field | Lives in | Proposal |
|---|---|---|
| `by`, `recorded_at`, `scope` | per-unit consent file | `granted_by`, `granted_at`, `scope` of the standing approval |
| `eula_accepted`, `attending_until_end` | per-unit consent file | **Open.** The schema has no field for them yet. Proposal: the owner types them once at `grant` time as named statements and they are sealed by the hash. Needs the gate owner's answer on whether a standing statement meets the condition |
| `go_for_this_one_run` | per-unit consent file | Not standing by nature. Proposal: replace by the launcher's run receipt plus `limits.max_runs_per_unit`. Needs the gate owner's answer |
| `quote`, `asked_by_lead_at` | per-unit consent file | Not needed. `note` carries the owner's own words, typed by the owner |

## Honest limits

This is a coordination and audit mechanism. A process running as the same OS user can write the same bytes, so it is not a security boundary. The guard against forged approvals remains the classifier and the owner reading the audit log. Whether the classifier treats a file written from the owner's shell as the owner's authorization is to be measured with the #46 probes.

## Next (M1)

CLI `grant`, `revoke`, `extend`, `show`, `check`; append-only audit log with a hash chain; known-answer tests for expired, tampered, missing, out-of-limits, excluded action.

## Gate owner ruling (2026-10-18) folded into v1

Ruling: yes. Terms and unattended permission come from the owner's standing approval, the single-run limit comes from execution design rules, and no per-run re-consent or extra human approval is added. Limits it states: a hash is evidence of content match, not a signature, and the ruling does not replace verification of the real gate.

| Gate owner requirement | Where it lives |
|---|---|
| `eula` and `execution_mode` stated separately, not inferred from `scope` or `note` | `eula` object (accepted, license, subject, consent_source) and `execution_mode` in the approval. `grant` refuses without `--eula-accept` plus license, subject and source |
| `valid_until` exact (2026-10-24T14:59:00Z), date-only must not turn into UTC midnight or 7 days | `grant --until` accepts only a full UTC timestamp and refuses a date. `--days` applies only when `--until` is absent. Linux migration start is handled by `revoke` |
| Receipt carries `experiment_unit_id` and `attempt_kind`; counts are fixed to one unit and never reset | `mai-approve-receipt-v1`; `limits.count_per` is the constant `experiment_unit_id`; `check` counts receipts per unit across all approvals, so a new run id or `extend` resets nothing; a reused run id is refused |

Expiry or revoke during a run: the launcher calls `check` again at its own checkpoints; the stop rule is the launcher's (launcher side).

## M1 usage

```
mai-approve grant --scope lab --until 2026-10-24T14:59:00Z --allowed-path <dir> --unattended   --eula-accept --eula-license "NVIDIA Omniverse License" --eula-subject <who> --eula-source <where it was agreed>
mai-approve receipt --scope lab --unattended --path <dir> --device <id> --experiment-unit unit-b --attempt-kind normal --run-id <id>
mai-approve finish  --scope lab --run-id <id> --status ended|failed|aborted
mai-approve check   --scope lab --inquiry          # only: is the approval live?
```

`receipt` is the launcher's gate: it re-checks everything and reserves the run in one step under a store-wide lock, then writes the receipt. `check` is an advisory read of the same rules (a second launcher can still take the last run between a `check` and a `receipt`, so a launcher must use `receipt`, not `check`). A run request must state what it will do: every `--path`, every `--device` (when the approval limits devices), the `--experiment-unit`, and every excluded-category `--action` it involves; `check --inquiry` is the only form without them. Exit 0 allowed, 2 refused (JSON line on stdout, reason on stderr). Store: `~/.mai/approvals` (or `MAI_APPROVE_DIR`). Tests: `python -I tools/mai-approve/tests/test_cli.py`, `test_hardening.py`, `test_schema_contract.py`.

## Independent review, findings A1 to A7 (all probes reproduced as tests)

| ID | Finding | Fix |
|---|---|---|
| A1 | `run_id` of `../../../x` wrote a receipt outside the store | run id must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` and the resolved receipt path must stay in the receipt folder |
| A2 | check and write were not atomic: limit 1, two launchers both allowed, count 2 | store-wide lock around check, count, receipt, audit; 8 simultaneous processes in 3 rounds, exactly one succeeds; `finish` records the end but never frees a run (every started attempt counts) |
| A3 | a corrupt receipt was skipped, count read as 0 | any receipt that is unreadable, fails its contract, or whose `run_id` does not match its file name stops counting with `receipt_corrupt` |
| A4 | runtime validation was weaker than the schema (max_runs -1 passed) | runtime now enforces the schema's types, required fields, minimums and unknown-field rule; never raises; a 400-case fuzz proves the runtime never accepts what the schema rejects |
| A5 | devices not checked, `--path` optional, links not resolved | run requests must state path, unit and (when limited) devices; every requested device must be approved; paths are compared after resolving symlinks and junctions (tested with a real junction) |
| A6 | claimed to detect missing lines, but a cut-off tail is invisible | claim narrowed to edited or removed lines inside the log; `audit-head` prints the head hash for the owner to record elsewhere and `audit-verify --expect-head` catches a cut-off tail |
| A7 | an approval written on Windows, checked on Linux, matched by reading `C:/x` as a relative path under the current folder (the reverse for POSIX paths on Windows) | `foreign_path_notation`: an approval whose allowed paths, or a request whose paths, are in another system's absolute notation is refused. An approval is not moved between systems; the owner grants again on the new machine. Liveness checks (`--inquiry`) do not read paths and are unaffected |

Test sensitivity: with the lock removed the race test fails, with the run id pattern removed the traversal test fails (checked on mutated copies).

Still open: the first launcher's gate does not use this yet (launcher side); whether an AI-assisted shell treats an owner-written file as the owner's authorization is not measured; the `eula` block of the approval was shaped by the first project's license consent and may need to become an optional generic `consent` block before wider use; relative request paths resolve against the caller's current directory.
