# Mixed-workload scheduler sensitivity matrix — MALEBOLGE v0.22.0

Date: 2026-10-09

## Executive result

The matrix compares the default scheduler with the opt-in round-robin scheduler across four workload/profile configurations. Three paired trials were run per scheduler per configuration (24 total executions). The test harness reported successful data integrity, relay observability, resource cleanup, and late-stream overlap in every run. The results are exploratory and inconsistent: round-robin does not produce a reliable interactive-latency improvement, so the default remains unchanged.

## Method

- Four cases: loopback / pipeline depth 1 / 256 KiB; metro / depth 1 / 256 KiB; metro / depth 4 / 256 KiB; metro / depth 4 / 1 MiB.
- Same trial seed for the two scheduler conditions within each case; execution order alternates by trial.
- Four 128-byte interactive requests per early and late stream, separated by 3 ms.
- The loopback case uses a 1 ms stagger because its 256 KiB bulk transfer can finish before 20 ms; metro cases use 20 ms. Each run records whether the late stream actually started during bulk transfer.
- Reports include medians and the median of paired per-trial percentage changes. With only three trials per case, these numbers should not be treated as statistically conclusive.

## Results

| Scenario | Bulk goodput baseline → RR (Mbps) | Paired goodput delta | Early RTT p50 delta | Early RTT p95 delta | Late RTT p50 delta | Late RTT p95 delta |
|---|---:|---:|---:|---:|---:|---:|
| loopback / pipe 1 / 256 KiB | 113.373 → 104.536 | -10.27% | +0.80% | +27.12% | +10.44% | +3.29% |
| metro / pipe 1 / 256 KiB | 2.394 → 2.383 | -0.43% | -1.50% | +1.11% | -0.61% | +2.89% |
| metro / pipe 4 / 256 KiB | 6.139 → 6.398 | -0.71% | +0.85% | +3.09% | +8.63% | +0.85% |
| metro / pipe 4 / 1024 KiB | 7.891 → 7.750 | -1.78% | -1.75% | +0.38% | +0.40% | +0.13% |

Positive RTT deltas mean round-robin latency was worse; negative deltas mean it was better. The “paired delta” is the median of the three same-seed per-trial percentage changes, rather than a ratio computed from two independent medians.

### Detailed medians

| Scenario | Bulk completion baseline → RR (ms) | Early RTT p50 baseline → RR (ms) | Early RTT p95 baseline → RR (ms) | Late RTT p50 baseline → RR (ms) | Late RTT p95 baseline → RR (ms) |
|---|---:|---:|---:|---:|---:|
| loopback / pipe 1 / 256 KiB | 18.50 → 20.06 | 1.57 → 1.51 | 1.80 → 2.37 | 1.57 → 1.67 | 2.12 → 2.29 |
| metro / pipe 1 / 256 KiB | 876.18 → 879.99 | 100.64 → 99.12 | 121.88 → 124.42 | 108.88 → 110.84 | 120.50 → 123.99 |
| metro / pipe 4 / 256 KiB | 341.61 → 327.80 | 96.72 → 100.12 | 111.30 → 118.25 | 96.08 → 107.50 | 127.10 → 130.81 |
| metro / pipe 4 / 1024 KiB | 1063.08 → 1082.39 | 109.93 → 108.01 | 128.45 → 126.68 | 110.62 → 111.36 | 135.87 → 139.95 |

## Interpretation and decision

No configuration shows a repeatable, across-the-board win. On loopback, round-robin materially increases interactive p95 in this small sample while lowering bulk goodput. On the metro profile, a few p50 values improve slightly, but several p95 measures worsen, particularly for the delayed stream under pipeline depth 4. At 1 MiB, most RTT paired deltas are near zero to mildly worse, while bulk goodput falls slightly. With three trials and shaped loopback timing, these observations are diagnostic rather than conclusive.

**Decision: keep round-robin opt-in. Do not change the default scheduler or promote a new version based on this experiment.** The next engineering target should be understanding the scheduler’s write queue and frame-dispatch behavior, then isolating queue wait, serialization time, relay processing, and return-path delay with direct instrumentation rather than optimizing against noisy end-to-end medians.

## Validation

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: 147 tests passed in 22.987 s; no ResourceWarning escaped as an error.
- `PYTHONPATH=src pytest -q`: 149 passed, 11 subtests passed in 23.46 s.
- Matrix: 24/24 scheduler runs completed; integrity/observability/cleanup checks passed in all runs; late streams overlapped bulk transfer in all cases.

## Limits

All relay, proxy, and destination processes run on one host via IPv4 loopback. The shaper acts on TCP byte-streams and does not model IP loss/retransmission or a real WAN. The finite-flow microbenchmark is not a proof of steady-state fairness, anonymity, resistance to a global observer, or production security. MALEBOLGE remains an experimental research lab and has not undergone an independent cryptographic audit.
