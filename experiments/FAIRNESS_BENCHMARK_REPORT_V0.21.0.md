# MALEBOLGE fairness benchmark — v0.21.0

## Summary

Added `rea-anon-fairness-bench` plus per-stream observability in the network-condition benchmark. The experiment executes three repeated trials for each of 1, 2, 4 and 8 equal-sized streams under the same synthetic `metro` profile, rotating the stream-count order per trial.

- Test matrix: 12 total circuit runs.
- Profile: 5 ms one-way configured delay, ±1 ms jitter, 200 Mb/s aggregate directional cap per proxy.
- Payload: 32 KiB per stream.
- Integrity checks: passed in all runs.
- Relay observation checks: passed in all runs.
- Relay and proxy cleanup: passed in all runs.

## Median summary

| Streams | Circuit goodput (Mb/s) | Jain completion-rate index | p50 stream latency (ms) | p95 stream latency (ms) |
|---:|---:|---:|---:|---:|
| 1 | 2.378 | 1.000 | 76.725 | 76.725 |
| 2 | 3.722 | 0.981 | 84.515 | 95.231 |
| 4 | 3.812 | 0.881 | 110.981 | 229.142 |
| 8 | 4.907 | 0.857 | 161.971 | 242.811 |

The score is based on finite-transfer per-stream completion goodput. It is a signal for further diagnosis, not a fairness proof. Results and individual stream metrics are in `experiments/fairness-matrix-metro-v0.21.0.json`.

## Finding

The circuit's aggregate goodput improves as more streams share the circuit, but completion rates become more unequal at higher stream counts and tail latency grows. The next engineering target should be queue/command scheduling and lock/credit wait profiling. Do not immediately raise concurrency limits: the current data are too small to justify it.

## Limitations

Loopback-only; user-space byte-stream shaper; no IP packet loss/retransmissions; not a real WAN experiment; direct path is not privacy-equivalent; protocol remains custom and unaudited.
