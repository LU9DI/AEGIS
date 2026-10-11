# AEGIS performance baseline — readiness audit (2026-10-10)

**Status: local characterization runner added; no new performance measurement is claimed by this document.** The historical simulator output in `experiments/baseline.json` explicitly marks itself as not a live-network test. It must not be used as a current implementation baseline.

## Existing runnable measurement harnesses

| Harness | Useful evidence already emitted | Current limitation for the baseline gate |
|---|---|---|
| `python -m anonlab.telescoping_benchmark` | Direct TCP echo versus three-hop circuit, circuit-build time, p50/p95 RTT, integrity and route-knowledge assertions, Python/platform metadata, JSON output | All sockets run on one host/loopback; fixed at three hops; no p99, CPU/RSS, retransmits, or real-WAN evidence |
| `python -m anonlab.network_impairment_benchmark` | Three-hop circuit and direct path under deterministic user-space latency/jitter/rate shaping; p50/p95, build/setup, goodput, bytes through shapers, integrity and cleanup checks | TCP remains reliable; no packet-loss/retransmission model; loopback only; direct and circuit traverse different shaped-link counts; no p99 or CPU/RSS |
| `python -m anonlab.mixed_workload_matrix` | Paired scheduler trials, multiple workload/profile cases, raw JSON trials, integrity/cleanup checks, platform/runtime metadata | Loopback scheduler experiment, not a full end-to-end baseline; finite small matrix and at most 10 trials; no real WAN, p99, CPU/RSS, or retransmit counts |
| `experiments/baseline.json` | Historical model outputs for illustrative latency/correlation/overhead scenarios | Simulator version 0.3.0, `is_live_network_test: false`; results are hypothetical and cannot establish current performance or privacy |

## One-command local characterization run

From the repository root, install the package and optional research dependency, then run:

```bash
python -m pip install -e '.[onion-lab]' pytest
bash scripts/run_performance_baseline.sh
```

Optional environment variables: `TRIALS` (default 5, range 1–10), `PAYLOAD_BYTES` (default 65536, range 1–1048576), `SEED` (default 20261009), `PROFILE` (default `metro`), and `OUT_DIR` (custom output directory). Example:

```bash
TRIALS=3 PAYLOAD_BYTES=65536 SEED=20261009 PROFILE=metro bash scripts/run_performance_baseline.sh
```

The runner records a manifest with commit SHA, tracked-source dirty status, Python/platform, CPU metadata where available, logical CPU count, Linux memory metadata where available, `pip freeze`, and the configuration. Untracked output files do not mark the source tree dirty. It saves raw JSON from the telescoping comparison, repeated shaped-network runs with separate seeds, and the mixed-workload matrix. Results go into a timestamped directory under `artifacts/` unless `OUT_DIR` is set. The PR validation workflow now syntax-checks the shell script and executes a small smoke run, then checks each harness's integrity/cleanup result.

This is a **local characterization suite**, not the complete accepted baseline. It deliberately records limitations and does not claim to collect CPU/RSS or TCP retransmission counts. The network impairment proxy shapes a reliable byte stream; it is not packet-loss simulation or a live WAN. Preserve the manifest and all raw JSON files. A dirty checkout is recorded, not rejected, so archive the source diff if running with local modifications.

## Gaps that remain before closing Issue #11

- [ ] Support matched one-, two- and three-hop configurations, plus a direct control under the same payload and impairment profile. Current end-to-end harnesses hard-code three hops.
- [ ] Add p99 and a documented percentile estimator; include confidence intervals or uncertainty estimates across independent paired trials.
- [ ] Capture process CPU time and peak RSS; collect TCP retransmissions only where the host exposes a reliable counter, otherwise record the field as unavailable rather than zero.
- [ ] Add small interactive requests during a large transfer and concurrent clients to the end-to-end baseline, preserving per-trial raw data and integrity/cleanup failures.
- [ ] Keep local user-space shaping results clearly separated from true multi-host/WAN measurements. A shaped loopback proxy is not a substitute for packet loss, real congestion control, independent operators or a live network.
- [x] Draft a privacy observation matrix per topology: [`AEGIS_PRIVACY_OBSERVATION_MATRIX.md`](AEGIS_PRIVACY_OBSERVATION_MATRIX.md) records expected visibility, collusion assumptions, destination visibility, traffic-correlation risks, and required measurement fields. **The matrix is a threat-model worksheet, not evidence that every property is implemented or an anonymity proof.**
- [ ] Validate the matrix against packet captures, runtime instrumentation and code review; run traffic-correlation experiments with false-positive/false-negative analysis.
- [ ] Ensure baseline runs never enable unsafe remote PIR or skip security checks.

## Interpretation rules

1. Do not claim AEGIS is faster or more private based on historical simulator JSON, a single run, different hosts, or unmatched payload/topology.
2. Report measured results and model hypotheses in separate sections.
3. Any optimization must be compared against the same pinned code path, environment, payload, hop count and impairment configuration, with raw results retained.
4. A benchmark passing integrity/cleanup checks establishes only that the run completed as expected; it does not establish production security or anonymity.

This work adds a reproducible local runner and an explicit readiness gate; it does not change protocol behavior or claim performance improvement.
