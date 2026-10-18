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
| G2 Known answers | Seven offline test files, process fixtures, fixed affine oracle | Windows and WSL core measured; explicit mutation probes in progress |
| G3 Independent review | One whole-branch reviewer and regression findings | Pending |
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
