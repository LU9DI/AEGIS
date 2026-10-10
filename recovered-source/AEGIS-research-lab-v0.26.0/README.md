# AEGIS — Anonymous Encrypted Garlic-routed Internet Shield

**Current lab version: 0.26.0**

> **Brand and acronym.** AEGIS stands for **A**nonymous **E**ncrypted **G**arlic-routed **I**nternet **S**hield. The aegis/égide metaphor represents an active, adaptive shield against mass surveillance. This is the project’s new identity and architectural direction—not a claim that garlic routing is already implemented. The current lab still uses experimental layered per-hop encryption and multi-hop relays; garlic-clove batching/delivery semantics are not implemented, and the protocol remains unaudited.

The distribution is now `aegis-anon-lab`; the internal Python module remains `anonlab` for continuity. Existing `rea-anon-*` console scripts are retained as compatibility aliases. Historical benchmark reports and raw experiment files keep their original MALEBOLGE labels so their provenance is not rewritten.

AEGIS is an experimental research lab. The core multi-hop relay testbed remains loopback-oriented; the separate PIR RPC prototype can opt into TLS on remote binds only through explicit API configuration. It explores encrypted framing, bounded full-duplex streams, signed relay metadata, and transport performance. It is not Tor-compatible and is **not safe for sensitive or production communications**.


## v0.26.0: TLS certificate rotation and aggregate rate limiting for PIR RPC

Adds live leaf-certificate rotation for an already-started TLS PIR endpoint. A temporary `SSLContext` validates the certificate/key pair before the active listener context is updated; the operation returns the new leaf certificate SHA-256 fingerprint. Failed validation leaves the active certificate in place. Clients must trust the chain and still verify the expected SAN/hostname. CA rotation should use an overlap period where clients trust old and new roots before servers switch.

Adds an aggregate token-bucket limit per replica (default 100 requests/sec, burst 128) and aggregate counters for accepted/rate-limited requests. The limiter stores no per-client IP, peer address, stream ID, or query identifier, reducing identity-linkage metadata, but a global limiter cannot stop distributed abuse and can affect all clients during overload. Active handlers/backlog, TLS handshake/shutdown timeouts and frame IO timeouts remain bounded. The TLS demo accepts `--max-requests-per-second` and `--request-burst`.

Certificate rotation is tested against new TLS handshakes and a mismatched certificate/key pair is verified to leave the existing certificate active. Rate-limit tests confirm requests beyond a tiny configured burst fail closed and aggregate counters do not contain peer identity. A red-team test demonstrates a critical remaining gap: a TLS-authenticated replica can return a false PIR answer while claiming the expected snapshot hash, and the current client cannot prove server-side computation correctness. This is not a remote multi-operator deployment, public PKI automation, verifiable PIR, signed database snapshot/update protocol, or production abuse defense.

## v0.25.0: TLS transport mode for two-server PIR RPC

Adds `aegis-pir-rpc-tls-demo`, which uses separate TLS server certificates, CA trust and DNS hostname verification for two independent listener endpoints. TLS mode does not distribute the server's HMAC pre-shared keys to clients, enforces TLS 1.2+, preserves nonce/replay and snapshot consistency checks, and bounds active handlers and frame read/write duration. The old `aegis-pir-rpc-demo` remains a local-only, unencrypted HMAC compatibility harness. The TLS demo still runs both listeners in one process and is not an independent-operator or production anonymity test. Example: `aegis-pir-rpc-tls-demo --ca-cert ./ca.pem --cert-a ./a.pem --key-a ./a-key.pem --cert-b ./b.pem --key-b ./b-key.pem --server-name-a replica-a.test --server-name-b replica-b.test`. See `docs/PIR_RPC_TLS_V0.25.0.md`.

## v0.24.0: authenticated loopback PIR RPC (research prototype)

This release extends the v0.23.0 routing/PIR/share prototypes with `aegis-pir-rpc-demo`: two separate loopback TCP listener endpoints, distinct per-endpoint pre-shared keys, HMAC-SHA256 request/response authentication with domain separation, nonce/timestamp replay checks, and replica-database snapshot comparison. The endpoint messages never include the selected record index. This is a local protocol harness, not remotely deployable: it does not encrypt traffic, deliberately rejects non-loopback binds, places both listeners in the same process, and must not be confused with independent operators or a production anonymity layer. See `docs/PIR_RPC_V0.24.0.md`.

```bash
aegis-pir-rpc-demo --records 64 --index 17 --record-bytes 32
```

## v0.23.0: route-scoring, PIR, and multipath primitives (research prototypes)

This release adds three isolated, local-only prototypes. They do **not** yet change the live relay transport or create a production anonymity network:

- `aegis-route-select` chooses a 3-hop candidate path using measured per-link RTT where available, a conservative geometry-based estimate for missing measurements, bandwidth/load penalties, and hard ASN/family/subnet diversity limits. It requires a pinned confirmed guard and never silently rotates the entry guard when that guard is unavailable. Endpoint coordinates are consumed locally and omitted from route-plan output. The result is a heuristic, not a ZK proof or a ping guarantee.
- `aegis-pir-demo` demonstrates the two-server XOR PIR algorithm in-process. `aegis-pir-rpc-demo` builds on it with authenticated requests/responses between distinct loopback listener ports and detects replica snapshot mismatch. Two colluding replicas still recover the index; the shared-key transport is not encrypted and must not be exposed to remote or untrusted clients.
- `aegis-share-demo` demonstrates fixed-width, chunk-level 2-of-2 XOR secret sharing. Each share alone is information-theoretically independent of the payload when the randomness is secure, but both shares are needed to reconstruct; a global observer who sees both paths can recover the payload. This is a local primitive demo, not a network transport.

Examples:

```bash
aegis-route-select
aegis-pir-demo --records 64 --index 17
aegis-share-demo --payload-bytes 65537 --chunk-size 4096
```

Detailed limits and migration plan: `docs/AEGIS_V0.23.0_ARCHITECTURE_DECISIONS.md`. Rust/QUIC/WebAssembly, ZK access credentials and FHE are **not implemented** in this release. A transport replacement is blocked on a Rust toolchain and a separate interoperability/threat-model effort. In browsers, QUIC access is through a browser API such as WebTransport, not arbitrary UDP sockets from Wasm.

## Network-condition testbed reference (v0.20.0)

The new `aegis-network-impairment-bench` command exercises the three-relay loopback circuit behind bounded TCP shapers. Profiles model one-way delay, bounded jitter, and an aggregate bandwidth cap shared across all connections per proxy and direction. The benchmark includes loopback, LAN, metro, intercontinental, constrained, and sparse-write cases.

The current exploratory matrix uses two runs per profile and is not a WAN prediction. The proxy shapes TCP byte-stream reads, not IP packets; it does not simulate packet loss or TCP retransmissions. The direct control has one shaped link while the circuit has four, so the result is a path-length diagnostic rather than an equivalent privacy/performance comparison. See `docs/NETWORK_IMPAIRMENT_V0.20.0.md`, `experiments/NETWORK_CONDITION_REPORT_V0.20.0.md`, and raw JSON in `experiments/`.

Run a profile:

```bash
aegis-network-impairment-bench \
  --profile intercontinental \
  --streams 2 \
  --payload-bytes 8192 \
  --output experiments/intercontinental.json
```

To test sparse application writes:

```bash
aegis-network-impairment-bench \
  --profile intercontinental \
  --streams 2 \
  --payload-bytes 4096 \
  --sparse-gap-ms 1 \
  --sparse-chunk-bytes 512 \
  --output experiments/intercontinental-sparse.json
```

The experimental `aegis-pipeline-bench` command compares maximum in-flight depths 1, 2 and 4 with rotating trial order. For meaningful results, hold payload size, chunk size, stream count, host, seed and environment constant; inspect both the duplex result and direct-TCP control.
To profile the local hot path without capturing application payloads, use `aegis-profile-hotpath`:

```bash
aegis-profile-hotpath \
  --streams 8 \
  --payload-bytes 262144 \
  --write-chunk-bytes 262144 \
  --pipeline-depth 4 \
  --output-prefix experiments/hotpath-profile
```

The command emits `.prof`, `.txt`, and `.json` summaries. cProfile overhead changes wall-time measurements; use the call/timing profile to locate costs, not as a throughput benchmark.

## Current focus: experimental round-robin write scheduling (v0.22.0)

The `TelescopingClient(fair_write_scheduling=True)` option enables a bounded client-side round-robin queue: each active stream receives one WRITE command per scheduler turn, stream order remains FIFO, and aggregate queued work is capped at 512 commands / 8 MiB. This mode is **opt-in**; the baseline batch dispatcher remains the default because the first A/B results showed small, mixed effects rather than a robust throughput win.

Compare baseline and round-robin scheduling with `aegis-scheduler-bench`:

```bash
aegis-scheduler-bench \
  --profile metro \
  --stream-counts 2,4,8 \
  --trials 3 \
  --payload-bytes 262144 \
  --write-chunk-bytes 65536 \
  --pipeline-depth 4 \
  --output experiments/scheduler-ab.json
```

The `aegis-fairness-bench` command remains useful for measuring equal-sized streams sharing an experimental three-relay circuit. It reports per-stream completion time, derived goodput and a Jain completion-rate index, with trial order rotated to reduce simple order bias. The index is a finite-transfer diagnostic, not a fairness proof.

```bash
aegis-fairness-bench \
  --profile metro \
  --stream-counts 1,2,4,8 \
  --trials 3 \
  --payload-bytes 32768 \
  --output experiments/fairness-matrix.json
```

This index is only a finite-transfer completion-rate proxy; it is not a proof of steady-state fairness or production congestion control. The v0.21.0 exploratory matrix had 3 trials each at 1, 2, 4 and 8 streams and observed lower Jain index and higher tail latency at larger stream counts. The v0.22.0 A/B benchmark found a small positive Jain-index delta (about +0.002 to +0.009) but mixed throughput/latency results, so the round-robin scheduler remains opt-in. See `docs/FAIR_SCHEDULER_V0.22.0.md` and `experiments/SCHEDULER_AB_REPORT_V0.22.0.md`.


### Mixed bulk + interactive workload

To evaluate whether a large stream competes with short interactive exchanges, run `aegis-mixed-workload-bench`. It measures the bulk transfer and two request/response streams, including one stream opened after the bulk flow has started:

```bash
aegis-mixed-workload-bench \
  --profile metro \
  --trials 5 \
  --bulk-bytes 262144 \
  --interactive-requests 5 \
  --request-bytes 128 \
  --request-gap-ms 5 \
  --stagger-after-ms 20 \
  --write-chunk-bytes 16384 \
  --pipeline-depth 4 \
  --seed 20261023 \
  --output experiments/mixed-workload-ab.json
```

Each trial uses the same configured shaper seed for baseline and round-robin, and condition order alternates. This is still a small exploratory sample. In the current five-trial metro run, round-robin reduced median bulk goodput by about 12.85% and increased median bulk completion time by about 14.75%, while interactive RTT results were mixed. The default remains unchanged. See `docs/MIXED_WORKLOAD_BENCHMARK_V0.22.0.md` and `experiments/mixed-workload-ab-paired-v0.22.0.json`.

### WINDOW_UPDATE credit batching sensitivity

The `aegis-window-update-bench` command compares 16 KiB, 32 KiB, 64 KiB (the current default), and 128 KiB receive-credit batching thresholds while holding the write scheduler fixed. It reports paired trial deltas for throughput and interactive latency, as well as exit-relay update-command counts and pauses waiting for flow credit. The 2 ms sparse-stream flush timer remains constant so this experiment isolates the byte threshold.

```bash
aegis-window-update-bench \
  --profile metro \
  --trials 3 \
  --batch-sizes 16384 32768 65536 131072 \
  --bulk-bytes 262144 \
  --interactive-requests 5 \
  --request-gap-ms 5 \
  --stagger-after-ms 20 \
  --pipeline-depth 4 \
  --seed 20261024 \
  --output experiments/window-update-batch-sensitivity-v0.22.0.json
```

The default 64 KiB threshold is mandatory as the control condition. Each trial rotates the order of thresholds and uses the same configured shaper seed across conditions; timing differences can still cause the TCP proxy to consume different random-delay sequences. Results remain exploratory loopback measurements, not a WAN forecast.

## Requirements

- Python 3.11+
- `cryptography` (install the `onion-lab` extra)
- `pytest` for tests

## Install and test

```bash
python -m pip install -e '.[onion-lab]'
python -m pytest -q
```

## Run the pipeline benchmark

```bash
aegis-pipeline-bench \
  --trials 5 \
  --streams 8 \
  --payload-bytes 1048576 \
  --chunk-bytes 65536 \
  --output experiments/pipeline-depth-1mib-5trials-v0.19.0.json
```

To compare the older 16 KiB, 64 KiB and 256 KiB acknowledged write sizes, also run
`aegis-write-batch-bench`. Both commands use IPv4 loopback and are not WAN tests.

The benchmark uses three relays and a destination on IPv4 loopback. It records integrity, relay-observability, cleanup, and `WINDOW_UPDATE` counts alongside throughput and latency. For credit batching, pass `--window-update-batch-bytes 1`, `32768`, or `65536` to compare immediate, 32 KiB, and 64 KiB updates. Compare only scenarios with the same payload, stream count, host, and environment. A benchmark result is not a WAN forecast and does not prove anonymity.

For the credit batching threshold study, see `docs/WINDOW_UPDATE_BATCH_SENSITIVITY_V0.22.0.md` and `experiments/window-update-batch-sensitivity-v0.22.0.json`. The 16 KiB threshold performed worse in the initial mixed-workload sample; 32 KiB and 128 KiB showed trade-offs, so 64 KiB remains unchanged pending more trials.

## Security limitations

- The protocol is custom and unaudited; this lab is not compatible with Tor.
- Loopback tests do not validate operation across real network paths, NATs, congestion, packet loss, or independently operated nodes.
- The exit relay can observe the destination and application bytes; neighboring relays can observe link metadata, timing, sizes, and hop-local stream IDs.
- No proof of traffic-analysis resistance, global-observer anonymity, fairness, or production congestion control is provided.
- Larger write frames increase transient memory per operation. Do not expose these relay listeners to the Internet.

See `docs/NETWORK_IMPAIRMENT_V0.20.0.md`, `docs/THREAT_MODEL.md`, `docs/ARCHITECTURE.md`, `docs/WRITE_PIPELINE_V0.17.0.md`, `docs/WRITE_PIPELINE_SECURITY_REVIEW_V0.17.0.md`, `docs/PERFORMANCE_PROFILE_V0.18.0.md`, `docs/WINDOW_UPDATE_COALESCING_V0.19.0.md`, and `docs/FAIR_SCHEDULER_V0.22.0.md` for more details.

## Mixed-workload scheduler sensitivity matrix

To compare the default and optional round-robin write schedulers across a small
set of shaped loopback workloads (profile, pipeline depth, and bulk size), run:

```sh
PYTHONPATH=src python -m anonlab.mixed_workload_matrix \
  --trials 5 --seed 20261023 \
  --output experiments/mixed-workload-matrix-v0.22.0.json
```

The matrix keeps the scheduler comparison paired by trial seed, alternates
execution order, reports both medians and paired per-trial deltas, and counts
which scheduler won per metric. It is designed for exploratory diagnosis; do
not use the output alone to promote a scheduler or claim real-WAN performance.

### Optional write-stage diagnostics

The client exposes bounded, payload-free timing events when initialized with
`TelescopingClient(collect_write_metrics=True)`. General client instances keep
this instrumentation disabled. The mixed-workload benchmark enables it and
reports queue wait, send-lock wait, frame preparation, socket `drain()`, and
end-to-end response-wait timing. Response-wait includes the returned stream
response through the experimental circuit; it is not a raw TCP ACK latency.
Instrumentation adds measurement overhead, so compare its timings as a stage
breakdown and do not equate them directly with uninstrumented throughput runs.


Relay-side measurements are also available in `relay_stage_diagnostics` for each
hop in the mixed-workload benchmark. They are opt-in, bounded, and report command
dispatch, downstream response waits, response/event sends, destination reads and
writes, and stream-credit waits without storing payloads or stream IDs. These
metrics are timing metadata and still reveal aspects of traffic behavior. See
`docs/RELAY_STAGE_DIAGNOSTICS_V0.22.0.md` for details and interpretation cautions.


### WINDOW_UPDATE sparse-credit flush timer sensitivity

The `aegis-window-update-timer-bench` command varies the maximum wait before flushing pending, sub-threshold receive credit. It keeps the 64 KiB credit threshold and default write scheduler fixed, using 0.5 ms, 2 ms (control) and 5 ms by default. This timer applies when `read_chunk()` is waiting with pending credit; it is not a timer on every `WINDOW_UPDATE`.

```bash
aegis-window-update-timer-bench \
  --profile metro \
  --trials 3 \
  --timer-values-ms 0.5 2 5 \
  --batch-bytes 65536 \
  --bulk-bytes 262144 \
  --interactive-requests 5 \
  --request-gap-ms 5 \
  --stagger-after-ms 20 \
  --pipeline-depth 4 \
  --seed 20261025 \
  --output experiments/window-update-timer-sensitivity-v0.22.0.json
```

The 2 ms control must be included for paired comparisons. Trials rotate condition order and share the configured shaper seed within each trial, but differences in event timing still alter the TCP proxy's actual timing trace. Results are exploratory local-loopback measurements, not a real-WAN prediction. The ten-trial follow-up showed a median paired bulk-goodput gain of 23.94% at 5 ms, but early and late interactive p95 changes were +0.18% and +0.98%, with five wins and five losses for each. Therefore, 2 ms remains the default; see `docs/WINDOW_UPDATE_TIMER_SENSITIVITY_V0.22.0.md` and `experiments/VALIDATION_WINDOW_UPDATE_TIMER_SENSITIVITY_V0.22.0.md`.

A subsequent cross-profile check used the `intercontinental` and `constrained` shapers with longer-spaced interactive requests and a 128 KiB bulk flow. With only two trials per timer/profile, 5 ms showed a small throughput benefit but no consistent p95 latency benefit across profiles; the 2 ms default is unchanged. Details and raw data are in `docs/WINDOW_UPDATE_TIMER_CROSS_PROFILE_V0.22.0.md` and `experiments/window-update-timer-cross-profile-v0.22.0.json`.

The sparse-interactive follow-up increases the gap between four small requests to 250 ms and runs four trials per timer in both `metro` and `intercontinental` profiles. In that workload, 5 ms reduced bulk goodput and worsened interactive p95 latency in both profiles, so 2 ms remains the default. Reproduce it with the two commands in `docs/WINDOW_UPDATE_TIMER_SPARSE_INTERACTIVE_V0.22.0.md`; raw individual and combined records are in `experiments/window-update-timer-sparse-*.json`. These remain small loopback experiments, not WAN predictions.
