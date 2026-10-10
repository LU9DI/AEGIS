# AEGIS performance baseline — readiness audit (2026-10-10)

**Status: audit only; no new performance measurement is claimed by this document.** The historical simulator output in `experiments/baseline.json` explicitly marks itself as not a live-network test. It must not be used as a current implementation baseline.

## Existing runnable measurement harnesses

| Harness | Useful evidence already emitted | Current limitation for the baseline gate |
|---|---|---|
| `python -m anonlab.telescoping_benchmark` | Direct TCP echo versus three-hop circuit, circuit-build time, p50/p95 RTT, integrity and route-knowledge assertions, Python/platform metadata, JSON output | All sockets run on one host/loopback; fixed at three hops; no p99, CPU/RSS, retransmits, or real-WAN evidence |
| `python -m anonlab.network_impairment_benchmark` | Three-hop circuit and direct path under deterministic user-space latency/jitter/rate shaping; p50/p95, build/setup, goodput, bytes through shapers, integrity and cleanup checks | TCP remains reliable; no packet-loss/retransmission model; loopback only; direct and circuit traverse different shaped-link counts; no p99 or CPU/RSS |
| `python -m anonlab.mixed_workload_matrix` | Paired scheduler trials, multiple workload/profile cases, raw JSON trials, integrity/cleanup checks, platform/runtime metadata | Loopback scheduler experiment, not a full end-to-end baseline; finite small matrix and at most 10 trials; no real WAN, p99, CPU/RSS, or retransmit counts |
| `experiments/baseline.json` | Historical model outputs for illustrative latency/correlation/overhead scenarios | Simulator version 0.3.0, `is_live_network_test: false`; results are hypothetical and cannot establish current performance or privacy |

## Reproducible smoke commands

Run from a clean checkout after installing the package and its optional onion dependency:

```bash
python -m pip install -e '.[onion-lab]' pytest
python -m anonlab.telescoping_benchmark --bytes 65536 --trials 5 --seed 20261009 --output artifacts/telescoping-baseline.json
python -m anonlab.network_impairment_benchmark --profile metro --streams 4 --payload-bytes 65536 --seed 20261020 --pipeline-depth 1 --output artifacts/network-impairment-baseline.json
python -m anonlab.mixed_workload_matrix --trials 5 --seed 20261023 --output artifacts/mixed-workload-baseline.json
```

These are **local smoke/characterization runs**, not the complete accepted baseline. Capture the exact Git commit alongside outputs (for example, `git rev-parse HEAD`) and retain the raw JSON files. Run each command more than once only when the host is otherwise idle; do not compare results from different machines as if they were paired trials.

## Gaps that remain before closing Issue #11

- [ ] Add an orchestrator that records the commit SHA, dependency lock/version report, OS/kernel, CPU model/count, RAM, topology, configuration, warm-up, repetitions and failures into one manifest.
- [ ] Support matched one-, two- and three-hop configurations, plus a direct control under the same payload and impairment profile. Current end-to-end harnesses hard-code three hops.
- [ ] Add p99 and a documented percentile estimator; include confidence intervals or uncertainty estimates across independent paired trials.
- [ ] Capture process CPU time and peak RSS; collect TCP retransmissions only where the host exposes a reliable counter, otherwise record the field as unavailable rather than zero.
- [ ] Add small interactive requests during a large transfer and concurrent clients, preserving per-trial raw data and integrity/cleanup failures.
- [ ] Keep local user-space shaping results clearly separated from true multi-host/WAN measurements. A shaped loopback proxy is not a substitute for packet loss, real congestion control, independent operators or a live network.
- [ ] Write a privacy observation matrix per topology: what each relay sees, collusion assumptions, destination visibility, and which metadata/timing correlation remains possible. Passing a route-observation assertion is not an anonymity proof.
- [ ] Ensure the baseline command never enables unsafe remote PIR or skips security checks.

## Interpretation rules

1. Do not claim AEGIS is faster or more private based on historical simulator JSON, a single run, different hosts, or unmatched payload/topology.
2. Report measured results and model hypotheses in separate sections.
3. Any optimization must be compared against the same pinned code path, environment, payload, hop count and impairment configuration, with raw results retained.
4. A benchmark passing integrity/cleanup checks establishes only that the run completed as expected; it does not establish production security or anonymity.

This audit intentionally does not change protocol behavior or claim performance improvement. It provides a precise readiness gate for the next measurement implementation.
