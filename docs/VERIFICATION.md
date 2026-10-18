# Verification gates

A tool is **releasable** only when every gate below holds. A tool that has not passed all of them stays marked `draft` in its own README, and nothing outside this repository should depend on it.

| Gate | What must be true | How it is checked |
|---|---|---|
| G1 Own machine | The author ran it on real input on one machine and recorded what was measured. | The tool's DESIGN.md states measurements, with the date and the kind of machine. Shape only, no names. |
| G2 Known answers | Tests start from inputs whose answers were written before the code ran, not from the code under test. | Review of the tests; mutation checks: break the rule on purpose and the matching test must fail. |
| G3 Independent review | A reviewer who did not write the tool tried to break it and every finding was either fixed with a test that reproduces it or recorded as an accepted limit. | Findings table in DESIGN.md, each with its test. |
| G4 Three systems | The full suite passes on Windows, Linux and macOS, or the tool states which one was not run. | CI matrix; `docs/PLATFORMS.md` is updated from real runs only. |
| G5 No personal data | No machine name, user name, home path, e-mail address or secret in code, examples, fixtures or documents. | `python common/hygiene_check.py`, itself covered by known-answer tests; run in CI. |
| G6 English first | The README and DESIGN.md are written in English; other languages are additions. | Review. |
| G7 User layer | The result is checked where the user meets it: the extension in a browser, the page in a browser at several widths, the command in a fresh shell. | Recorded by hand or by a script; stated as measured or not measured. |
| G8 Not measured is written | Everything that was not run is listed as not measured. | The Status line at the top of each DESIGN.md and README.md. |

## Reviewer checklist (for G3)

1. Are the expected values independent of the code under test?
2. Does each mutation really change behavior, and does a test notice?
3. What does the tool report when its source is broken, empty or missing? It must not report health.
4. Where is the same rule enforced a second time (another file, another language, another page)? Is that copy tested against the first?
5. What claim in the documentation is stronger than what was measured?

## Process for a new tool

1. Write `DESIGN.md` (English): purpose, non-goals, measured facts, schema, test plan.
2. Build it on the author's machine and record the measurements (G1).
3. Write known-answer tests first, then the code (G2).
4. Ask for independent review (G3) and answer every finding with a test.
5. Run the matrix and the hygiene gate (G4, G5), then update `docs/PLATFORMS.md`.
6. Only then change the status from `draft` to `release candidate`.
