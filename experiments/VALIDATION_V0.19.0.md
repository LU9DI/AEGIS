# MALEBOLGE v0.19.0 validation

- Python compile check: `python -m compileall -q src tests` — passed.
- Source suite: `pytest -q` — **117 passed, 11 subtests passed**.
- Paired randomized large-workload benchmark: five trials per threshold with 8 streams × 256 KiB and thresholds 1 byte, 32 KiB and 64 KiB — all 15 runs passed integrity, relay-observability and cleanup checks. Median goodput was 330.34 / 412.80 / 493.27 Mb/s; median window-update counts were 104 / 56 / 32. See `window-update-batching-v0.19.0.json`.
- Smaller workload: five trials per threshold with 8 streams × 64 KiB — all 15 runs passed all checks; median update count was 8 for all configurations, so no batching gain in update count was measured. See `window-update-batching-small-v0.19.0.json`.
- Sparse-stream regression: two 16 KiB destination writes separated by 20 ms completed with correct content; the bounded 2 ms timer flushed below-threshold credit and prevented a stall.
- Wheel: built `rea_anon_lab-0.19.0-py3-none-any.whl` without network build isolation and installed into a fresh virtual environment. Installed duplex-benchmark smoke tests at the default 64 KiB threshold and 32 KiB both reported version 0.19.0, data integrity true, relay-observability true, and zero active relay connections after close.
- ZIP artifact: extracted the final package into a clean directory and reran `pytest -q` — **117 passed, 11 subtests passed**.
- Security limits remain: custom unaudited protocol; test traffic stays on IPv4 loopback; no Tor compatibility, global-observer anonymity, or WAN performance claim.
