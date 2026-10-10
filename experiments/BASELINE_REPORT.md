# Baseline experiment — v0.1

**Status:** output of a flow-level simulation, not a live network benchmark or an anonymity proof.

Configuration: 180 s synthetic workload, 1.4 mean requests/s, seed `20261009`, 100 ms bins, maximum-lag search window ±3 s. All profiles use the exact same 244 generated flows (52.394 MB payload).

| Profile | p50 modeled latency | p95 modeled latency | Min hop capacity | Max-lag Pearson | Added traffic / payload |
|---|---:|---:|---:|---:|---:|
| `direct_reference` | 13.89 ms | 21.18 ms | 500 Mb/s | 0.9318 | — |
| `onion_reference` | 251.65 ms | 717.25 ms | 10 Mb/s | 0.8157 | — |
| `candidate_fast_hypothesis` | 51.10 ms | 92.73 ms | 100 Mb/s | 0.6134 | — |
| `candidate_independent_noise_hypothesis` | 51.10 ms | 92.73 ms | 100 Mb/s | 0.1850 | 3.00× |
| `candidate_fixed_rate_hypothesis` | 160.87 ms | 372.43 ms | 100 Mb/s | 0.0592 | 8.07× |

## Interpretation

- The hypothetical high-capacity three-hop profile produces lower modeled latency than the illustrative onion-routing profile because it was deliberately assigned lower per-hop delay and a 100 Mb/s bottleneck instead of 10 Mb/s. This is a sensitivity result, not evidence that an implemented network can achieve it.
- Independent edge-noise reduced the simple correlation score from the unprotected candidate profile, but the added traffic is counted rather than charged to link queues in v0.1. Its latency row must not be read as a real performance prediction.
- The idealized fixed-rate profile produces a low simple volume-correlation score, but sends a persistent 20 Mb/s stream across the modeled observation window and incurs a large modeled latency/traffic cost. The abstraction omits multiple metadata and active attacks.
- Pearson correlation is not a probability of deanonymization. No security conclusion follows from a low value, and values should only be compared within this exact simulation model.

## Next required validation

Build a local multi-process relay testbed; charge cover traffic to shared link capacity; measure real TCP/QUIC goodput, time-to-first-byte, transfer completion, CPU, and packet traces; add multi-user multiplexing; and test against stronger traffic-analysis attacks before making any privacy or speed claim.

Full machine-readable output: [`baseline.json`](baseline.json).
