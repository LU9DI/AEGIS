# AEGIS performance and anonymity baseline protocol

**Status:** reproducible experiment plan; this document does not report benchmark results and does not certify anonymity or production readiness.

## 1. What is being compared

The current repository is a Python anonymous-network research prototype, not a browser engine. It cannot yet be compared directly with Microsoft Edge's page-rendering speed. A local TCP relay RTT, a circuit-build time, and browser page-load time are different measurements.

Keep three tracks separate:

1. **Transport microbenchmarks:** local relay forwarding, circuit setup, stream latency, goodput, scheduling and resource cleanup.
2. **Network experiments:** multiple hosts and controlled WAN-like profiles, including latency, jitter, bandwidth, loss, concurrency and failures.
3. **Privacy/security evaluation:** relay knowledge boundaries, identity/IP leakage, traffic correlation, collusion, metadata retention, and fail-closed behavior.

Do not combine results from these tracks into one headline score. Do not describe loopback tests as Internet measurements or anonymity proofs.

## 2. Reproduce the current local baseline

Use a clean checkout and record the exact commit SHA before running anything. On a supported Python 3.11+ environment:

```sh
python -m venv .venv
```

Activate the environment, then install the project and its optional cryptography dependency:

```sh
python -m pip install --upgrade pip
python -m pip install -e ".[onion-lab]"
python -m pip check
```

First inspect the supported arguments for each installed entry point; do not copy flags from another version:

```sh
aegis-relay-bench --help
aegis-network-impairment-bench --help
aegis-mixed-workload-matrix --help
aegis-concurrency-bench --help
aegis-profile-hotpath --help
```

Run the commands supported by the checked-out version and preserve their complete output. If a command emits JSON, store the unmodified JSON alongside the exact command, environment and commit SHA. Avoid editing output files by hand.

The existing local relay benchmark explicitly measures raw loopback TCP forwarding without encryption, a live Internet route, or an anonymity layer. The impairment benchmark shapes a local TCP stream and documents that it does not reproduce packet loss, radio behavior, real TCP congestion or a geographically distributed WAN. These results are useful for regression comparisons only within the same test conditions.

## 3. Required metadata for every run

Record:

- commit SHA, dirty/clean working-tree state, command line and all parameters;
- Python/runtime, dependency versions, OS/kernel, CPU model/core count, RAM, power mode and virtualization/container details;
- network topology, interface and link profile, number of relay hops, stream count, payload sizes and concurrency;
- seed and whether the run uses synthetic payloads;
- warm-up count, measured trial count, cache state and trial ordering;
- failures, timeouts, retries, data-integrity results and cleanup/resource-leak results.

Do not publish a summary without retaining the raw per-trial measurements.

## 4. Metrics and reporting rules

Where applicable, report:

- circuit-build and connection-establishment time;
- time to first byte and complete-transfer time;
- RTT and completion-time p50, p95 and p99;
- goodput in Mbps and bytes transferred per successful operation;
- CPU and peak/steady-state memory;
- error, timeout, retry and integrity-failure rates;
- concurrent-flow completion and a clearly labelled fairness proxy;
- variance or spread across repeated runs.

Use paired runs when comparing two implementations or scheduler settings. Alternate or randomize condition order to reduce warm-cache and machine-load bias. Report the number of trials and the distribution, not only the best run or mean. Never treat a faster run as a win if it skipped validation, dropped data, leaked resources, or weakened a security control.

## 5. Staged network testing

### Stage A — deterministic local regression

Run existing loopback tests with fixed inputs and seeds. Confirm payload integrity, cleanup, bounded resource use, and repeatable outputs. These tests characterize implementation overhead only.

### Stage B — controlled impairment

Use the supported impairment profiles and record the exact profile parameters. Test interactive and bulk traffic together, multiple stream counts, concurrency, and pipeline settings. A user-space proxy is not a substitute for packet-level loss, retransmission, congestion, or radio-network testing.

### Stage C — multi-host experiment

Use independently hosted test nodes under controlled administration. Record region, provider, route, RTT, bandwidth and system load. Include latency/jitter/bandwidth limits, packet loss where it can be measured reliably, node failure, reconnect, overload, and malicious/malformed relay behavior. Never infer global-observer resistance from a small multi-host test.

### Stage D — browser-level comparison (future work)

A fair Edge comparison requires an actual AEGIS browser or browser integration and a fixed workload on the same Surface device, OS, power mode, network and browser versions. Measure navigation milestones, page rendering, JavaScript, memory, CPU and energy across repeated cold/warm runs. Compare the same pages and cache states. Do not use network circuit RTT as a substitute for page-load or rendering metrics.

## 6. Privacy and security gates

Performance tests do not prove anonymity. Before making a Tor-level claim, specify the attacker model and test at least:

- whether a destination can learn the client's real IP;
- DNS, IPv4/IPv6, WebRTC or other direct-connection leakage in any browser integration;
- which relay learns client identity, destination, payload, circuit membership and timing;
- whether colluding relays or observers can correlate ingress and egress traffic;
- whether request size, timing, retries, cache behavior or logs expose sensitive metadata;
- behavior under malicious relay responses, replay, malformed frames, resource exhaustion, node churn and partial failure;
- whether privacy/security failures stop the operation safely rather than silently falling back to direct networking.

An OHTTP-style relay/gateway split, E2EE, PIR, encrypted transport and anti-fingerprinting controls solve different problems. None alone establishes Tor-equivalent anonymity. A claim of stronger anonymity requires an explicit threat model, independent protocol review and adversarial testing.

## 7. Optimization decision rule

For each proposed optimization:

1. State one primary metric and the expected trade-off before testing.
2. Keep the security/privacy configuration fixed between paired runs.
3. Run correctness, adversarial and resource-bound tests before interpreting performance.
4. Compare repeated paired results, tail latency and regressions—not only aggregate throughput.
5. Reject a change that improves speed by introducing direct-network fallback, weakening cryptographic checks, widening relay knowledge, increasing unbounded resource use, or making failures fail-open.
6. Keep the optimization experimental until its result is reproduced on the target deployment and independently reviewed where security-sensitive.

## 8. Current non-claims

This plan does **not** establish that AEGIS is as fast as Edge, as anonymous as Tor, resistant to a global passive observer, or ready for sensitive/production use. The existing code and benchmark suite must be evaluated at their actual scope. The goal is to produce evidence that can support or falsify each claim, not to assume the result in advance.

## 9. Capture a first machine-readable baseline

From the repository root, after installing the project dependencies, run:

```sh
python scripts/run_transport_baseline.py
```

The runner invokes the existing loopback raw-TCP relay benchmark and writes a timestamped JSON artifact under `experiments/baselines/`. The artifact preserves the exact command, raw stdout/stderr, stdout SHA-256, exit status, commit SHA, working-tree state, runtime/platform metadata, and parsed per-trial benchmark output. A caller-specified `--output path.json` is also supported. Existing artifacts are never overwritten; choose a new path for each run. A nonzero benchmark exit status is preserved and returned by the runner.

Example for a shorter smoke-sized run (not suitable as a final performance result):

```sh
python scripts/run_transport_baseline.py --bytes 65536 --trials 3 --latency-samples 10
```

Use default or larger payloads and repeated independent runs for the actual baseline. Record power mode, CPU/RAM details, virtualization, dependency lock state, and background load alongside the generated artifact; host metadata cannot reliably infer all of these. Review `working_tree_dirty` before treating results as a commit-specific comparison. This runner is deliberately limited to the existing raw loopback relay benchmark and does not broaden the project's privacy or performance claims.

