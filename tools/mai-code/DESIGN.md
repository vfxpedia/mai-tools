> Classification: Tool design and verification
> Author: MAI maintainers · 2026-10-18
> Basis: Approved implementation plan · mai-tools #1 · mai-os #49
> Summary: Versioned units, immutable process evidence, conservative leases and fixed-test verification
> Status: Draft alpha. Independent review, native integration and platform measurements pending

# Design

The sequential stages are analyze, plan, implement, verify. A strict owner-authored unit pins source extracts, references, output paths, native engines and test argv. A prepared packet holds its full original unit, baseline Git identity and file hashes. Native CLI discovery resolves official npm shims to native executables, checks capability/help and subscription status without reading authentication files. Child environment filtering removes parent session attribution, preserves the effective CLI home and rejects API-mode conflict names without reporting their values.

Each attempt has an exclusive directory with input request, original stdout/stderr, parsed events and a closed receipt. Inputs are copied and hashed before execution. JSON receipts cannot be overwritten. Current state is atomically replaced; append-only events retain transitions. Parent hashes connect closed receipts. Raw log hashes and current workspace bytes are checked again before advancing. Unknown PID/lease state never authorizes cleanup. A crash before a receipt is not replayable work.

The observer concurrently drains both pipes to binary files, then interprets bounded JSONL records. Oversized or malformed records fail the stage but remain losslessly available in the raw stream. An attention timer records a live PID and does not terminate, retry or detach a child. Native completion is separate from stage contract validation. Stage answers must have stage, summary, assumptions, references and exact change manifest. Models cannot supply verification commands.

The verifier runs fixed unittest argv and a fixed negative control. It rejects zero tests, an import error mistaken for a negative result, a different failed test and unexpected error counts. Known affine fixture: x=[1,2], w=[3,4], b=1, target=10 gives prediction 12, loss 4, dW=[4,8], db=4 and dX=[12,16]. Finite differences use 1e-6 and absolute tolerance 1e-5. Shape mismatch and non-finite inputs are invalid. These are TEST ONLY mathematical facts, not results for MARG, START or AME-2.

## Gates and measurements

| Gate | Evidence | Current result |
|---|---|---|
| G1 Real input | Local version/auth probes and owned fixture | Probes measured; real model experiment pending |
| G2 Known answers | Seven offline test files, process fixtures, fixed affine oracle | Core tests measured on Windows; mutation audit pending |
| G3 Independent review | One whole-branch reviewer and regression findings | Pending |
| G4 Systems | Shared runner on Windows/Linux/macOS | Local Windows measured; CI and WSL pending |
| G5 Hygiene | Repository hygiene gate and archive inventory | Pending |
| G6 English first | README, DESIGN, provenance | Written |
| G7 User layer | Fresh-shell CLI and isolated package install | CLI help/prepare/status measured; install pending |
| G8 Limits stated | This table and README | Missing measurements explicitly pending |

Not measured: scientific equivalence to any paper, GPU experiments, unattended long-duration quotas, native macOS login, independent Ubuntu desktop login, adversarial same-user filesystem modification. Existing other MAI tools and Mods are not recertified by mai-code's tests.

## Accepted boundaries

The wrapper is not a security boundary. An engine or a fixed test is still a local executable under its native permissions. Unknown error codes remain unclassified, not invented quota errors. Source/lease corruption stops execution. Manual reconciliation does not mean silent lease deletion or automatic code cleanup. No automatic provider/key fallback, no token-price table, no global state updates.
