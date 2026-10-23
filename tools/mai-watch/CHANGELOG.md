Category: release notes
Author: pipeline, 2026-10-23
Evidence: mai-os#55, approved mobile recovery scope
Summary: user-visible changes and retained boundaries
Status: preview

# mai-watch changes

## 0.2.0a2

- Reload page next to Theme, with a labelled 44-pixel touch target and repeated-click protection.
- Reconnect on page return and network-online events, with no duplicate polling loops.
- Abort reads that exceed six seconds, including stalled bodies; retry after three seconds.
- Show received age separately from measured age, and keep aging while requests wait.
- Preserve theme across reload. Keep the existing local-only, read-only defaults.
- Retain desktop card alignment and vertically stacked mobile GPUs from the preceding layout update.

Full checks and release boundaries: [verification](../../docs/reviews/watch-recovery-20261023/README.md).
