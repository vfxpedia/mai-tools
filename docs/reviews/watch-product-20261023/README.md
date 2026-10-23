Category: verification
Author: pipeline, 2026-10-23
Evidence: owner-approved completion scope, mai-os#55 and #43
Summary: CPU attribution, diagnostics, warning context, local preferences and bounded history
Status: verification in progress, not yet deployed

# 0.3.0a1

## Scope and deliberate boundaries

- Existing desktop host grid and heights stay fixed. CPU core area is approximately half its measured previous height, top three CPU consumers below it.
- Background CPU time differences, PID creation identity, first reading unknown, stale expiry. One core = 100%.
- Explicit diagnostic allowlist and generic capability guidance. Download never contains names, paths, session titles, commands or raw logs.
- Existing judgments gain evidence, observed duration and next check; unknown never means cleared.
- Local-browser preferences for graph duration, emphasis and supporting tables. No arbitrary layout editor and no hiding of warnings/limits.
- Incident history: at most 256 records / 24 hours, memory only, reset on restart. Sample history retains the configured window with a 36,000-entry ceiling.
- No internet exposure, authentication system, remote workload control, new dependency or outbound telemetry.

## Evidence

- Known-answer tests cover CPU deltas/ranking, PID reuse, counter reset, missing scans, identity-free JSON, real HTTP export, actual renderer, unknown/gap incident behavior, retention and caps.
- Full local suite after review fixes: 526 tests, failed files 0. Five existing optional Codex integration skips; 14 new product tests run without skips.
- Browser checks use actual production scripts at 1920 and 390 px with a public-safe fixture, not private running-session data. Before/after screenshots and geometry are adjacent.
- Actual browser interactions cover preferences surviving reload, a downloaded JSON file, existing timeout/reconnect/reload behavior and theme retention.
- Independent review found shared psutil Process-info races, an unknown-window incident false resolution and warning-detail collapse. All were reproduced by failing tests and fixed. Background scans are serialized with each other, never with the sampler; incident observability distinguishes missing evidence from an actual recovery reading; warning open state uses a stable key.
- Reused/reset-only process lists now remain unknown. Repeated incidents retain previous cleared episodes within the same total cap.
- Remaining performance limit: the maximum 36,000-sample / eight-GPU / 0.2-second configuration is not a real-time guarantee. Slow reads or calculation extend the interval. Basic judgment work no longer holds the sampler lock and diagnostics do not repeat a full judgment pass.
- Final CI and deployment results will be recorded after measurement.

## Unmeasured

Physical mobile device, non-Windows browser rendering, multi-user internet service, durable cross-restart incident storage and market demand are not measured or claimed. Existing Windows user approval covers own-dashboard deployment, not public package-index publication.
