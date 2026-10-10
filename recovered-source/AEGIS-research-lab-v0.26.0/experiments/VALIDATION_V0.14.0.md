# Validation record — MALEBOLGE v0.14.0

- Added a continuous bidirectional TCP stream over a three-hop loopback circuit.
- Added independent per-hop stream mapping and event sequence numbers.
- Added a per-stream 64 KiB initial read-credit window (maximum 256 KiB), 16 KiB chunks, and explicit credit return on application consumption.
- Added OPEN / START / WRITE / HALF_CLOSE / WINDOW_UPDATE / CLOSE operations for duplex streams.
- Added tests for duplex echo with half-close, simultaneous streams on one circuit, a 192 KiB server push that requires credit updates, local write-size rejection, and benchmark teardown.
- Full pytest result: **105 passed, 11 subtests passed**.
- Loopback benchmark: `experiments/duplex-stream-v0.14.0.json`.
- Three-trial aggregate: `experiments/duplex-stream-trials-v0.14.0.json`; median goodput 130.56 Mb/s duplex vs 2,324.10 Mb/s direct TCP, with integrity, observability and cleanup checks true in all trials.

## Benchmark summary (one run, Linux x86-64, Python 3.13.5)

Configuration: 8 streams × 65,536 bytes, 3 loopback relays, 16 KiB chunks, 64 KiB initial receive window.

- Integrity verified: yes.
- Circuit build: 3.00 ms.
- Batch open of 8 streams: 6.24 ms.
- Duplex transfer wall time: 32.63 ms.
- Duplex useful-payload goodput: 128.56 Mb/s.
- Duplex stream latency p50/p95: 28.93 / 29.71 ms.
- Direct TCP baseline wall time: 2.49 ms.
- Direct useful-payload goodput: 1,683.18 Mb/s.
- Active streams after completion: 0.
- Active relay connections after client close: `[0, 0, 0]`.
- Relay observability check: passed.

This is a single-host microbenchmark, not a WAN result. Direct TCP is a lower-overhead baseline rather than an anonymity-equivalent comparison. The result shows that the prototype works but remains roughly an order of magnitude slower than direct TCP for this small concurrent workload. Per-chunk acknowledgement and per-read credit round trips are current bottlenecks.
