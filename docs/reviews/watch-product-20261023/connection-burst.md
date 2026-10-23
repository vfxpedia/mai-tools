Category: runtime correction
Author: pipeline, 2026-10-23
Evidence: real HTTPS reload failure and independent loopback connection burst
Summary: bounded accept queue prevents page assets being dropped during reload
Status: correction under verification

# 0.3.0a2 connection burst

After 0.3.0a1 passed fixture browser tests and three-OS CI, actual HTTPS reload exposed a runtime integration failure. The document could remain at reading because viewer-live.js received HTTP 502. Network instrumentation found no JavaScript exception. Twelve parallel requests, 36 total, produced nine loopback URL errors and two tailnet HTTP 502s. The stdlib server queue was five.

A controlled regression creates the listening server without starting its accept loop and connects twelve clients, representing a browser asset burst arriving before the accept loop is scheduled. Before the correction only five clients connected on Windows; the assertion failed. ViewerServer now sets a bounded queue of 32, retaining loopback binding and the same handler. The same test must accept all twelve. No Tailscale configuration, GPU workload or other agent is changed.

Actual parallel-request and desktop/mobile reload results are to be measured after deployment and recorded in mai-os#55. A failed probe is not accepted as completion.
