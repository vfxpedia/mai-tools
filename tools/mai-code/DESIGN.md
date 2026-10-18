> Classification: Tool design and verification
> Author: MAI maintainers · 2026-10-18
> Basis: Approved implementation plan · mai-tools #1 · mai-os #49
> Summary: Versioned units, immutable process evidence, conservative leases and fixed-test verification
> Status: Draft alpha. Windows native integration and WSL offline measured; independent review and CI pending

# Design

The sequential stages are analyze, plan, implement, verify. A strict owner-authored unit pins source extracts, references, output paths, native engines and test argv. A prepared packet holds its full original unit, baseline Git identity and file hashes. Native CLI discovery resolves official npm shims to native executables, checks capability/help and subscription status without reading authentication files. Child environment filtering removes parent session attribution, preserves the effective CLI home and rejects API-mode conflict names without reporting their values.

Each attempt has an exclusive directory with input request, original stdout/stderr, parsed events and a closed receipt. Inputs are copied and hashed before execution. JSON receipts cannot be overwritten. Current state is atomically replaced; append-only events retain transitions. Parent hashes connect closed receipts. Raw log hashes and current workspace bytes are checked again before advancing. Unknown PID/lease state never authorizes cleanup. A crash before a receipt is not replayable work.

The observer concurrently drains both pipes to binary files, then interprets bounded JSONL records. Oversized or malformed records fail the stage but remain losslessly available in the raw stream. An attention timer records a live PID and does not terminate, retry or detach a child. Native completion is separate from stage contract validation. Stage answers must have stage, summary, assumptions, references and exact change manifest. Models cannot supply verification commands.

The verifier runs fixed unittest argv and a fixed negative control. It rejects zero tests, an import error mistaken for a negative result, a different failed test and unexpected error counts. Known affine fixture: x=[1,2], w=[3,4], b=1, target=10 gives prediction 12, loss 4, dW=[4,8], db=4 and dX=[12,16]. Finite differences use 1e-6 and absolute tolerance 1e-5. Shape mismatch and non-finite inputs are invalid. These are TEST ONLY mathematical facts, not results for MARG, START or AME-2.

## Gates and measurements

| Gate | Evidence | Current result |
|---|---|---|
| G1 Real input | Local subscription CLI probes and owned affine fixture | Windows Codex 0.162.1 and Claude 2.1.302: full stages, 4 mathematical tests, declared negative control and exact-ID failed-stage continuation passed |
| G2 Known answers | Seven offline test files, process fixtures, fixed affine oracle | Windows 46/46 after recovery fixes. Hash-check removal and lease-exclusion removal each failed their known-answer mutation probe before the reboot |
| G3 Independent review | One whole-branch reviewer and regression findings | Four Important findings recovered and independently reproduced. Covered by RED then GREEN regression tests. Reviewer final summary was interrupted by reboot; final sign-off pending |
| G4 Systems | Shared runner on Windows/Linux/macOS | Windows and WSL offline core measured; hosted CI pending. WSL native Codex unavailable, Claude subscription not confirmed; no credential copy or native call there |
| G5 Hygiene | Repository hygiene gate and archive inventory | Staged source hygiene: zero findings. Wheel contains package and metadata only; source archive final check pending |
| G6 English first | README, DESIGN, provenance | Written |
| G7 User layer | Fresh-shell CLI and isolated package install | Install-free CLI and isolated venv console entry measured; native `resume` passed both engine fixtures |
| G8 Limits stated | This table and README | Missing measurements explicitly pending |

Not measured: scientific equivalence to any paper, GPU experiments, unattended long-duration quotas, native macOS login, independent Ubuntu desktop login, adversarial same-user filesystem modification. Existing other MAI tools and Mods are not recertified by mai-code's tests.

Native experiment budget was 4 Codex calls and 5 Claude calls including failed attempts. Codex's prose change manifest was correctly rejected; a strict file-path enum and corrected stage-baseline comparison allowed an exact-ID continuation without changing the generated module. Claude's initial Write denial was preserved. After the owner explicitly approved only the synthetic output file, a native exact-path grant was tested. Its first Windows spelling failed; the documented drive normalization fixed it. No broad tool allow, bypass mode or global permission edit was used. Original failed attempts, prompts, streams and native histories remain retained.

Existing Mods attribution was checked separately: Claude fixture IDs appeared in shared sessions/units; Codex exec fixture IDs did not. This does not prove all native lifecycle hooks fired, and no gauge installation/configuration was changed to hide that gap. The reusable executor remains usable independently of the unfinished compact-boundary or hook integration work.

## Accepted boundaries

The wrapper is not a security boundary. An engine or a fixed test is still a local executable under its native permissions. Unknown error codes remain unclassified, not invented quota errors. Source/lease corruption stops execution. Manual reconciliation does not mean silent lease deletion or automatic code cleanup. No automatic provider/key fallback, no token-price table, no global state updates.

## Recovery review findings (2026-10-18)

| Finding | Result and regression evidence |
|---|---|
| R1 Failed receipt or raw stream could be changed before native continuation | Failed receipts are pinned in current state and the closing event. Both resume routes validate receipt, parent and evidence hashes before creating an attempt. `test_failed_attempt_receipt_and_raw_log_are_pinned` failed for both mutations before the fix |
| R2 Separate evidence roots allowed simultaneous writers in one worktree | Lease location now derives from the physical worktree rather than the evidence root. `test_different_data_roots_cannot_lease_same_workspace` observed two successful processes before the fix and exactly one afterward |
| R3 Failed repeat verification retained a past passed/complete result | New verification first removes the current success reference and records a running attempt. Failure retains an incomplete event and blocks existing-result reads. Previous receipts remain. `test_repeat_verification_launch_failure_invalidates_pass` failed before the fix; interruption also retains the lease in `test_verification_unknown_child_keeps_lease` |
| R4 Tracked gitlinks hid nested edits from inventory | Preparation and every inventory refuse gitlinks/submodules until recursive ownership is designed. `test_gitlink_is_refused_before_unmeasured_child_content` uses a real local submodule and failed before the fix |
| CI1 Permission-rule test compared a logical temporary path with a canonical path | Hosted Windows short-name and macOS `/var` paths exposed the same test-oracle error. Expected fixture path is now physically resolved, while the drive-format assertion remains independent. Production rule generation is unchanged |

The reviewer had reproduced R1 through R4 before a machine reboot. Its final report, including any final Minor or Declined-to-judge list, was not persisted. The recovered intermediate report is not represented as a completed final sign-off. These fixes were remeasured by the implementer; release stays draft until the maintainer closes that review gate.

Leases require a writable physical worktree parent. The lock directory itself cannot be a symlink/junction. Old evidence-root locks are left in place and remain a refusal condition; old running versions must be stopped by their owner before version migration. This is coordination among cooperative local processes, not protection from a same-user attacker, filesystem races or cross-machine shared storage.
