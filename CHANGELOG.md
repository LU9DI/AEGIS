## v0.26.0 — TLS certificate lifecycle and aggregate RPC rate limiting

- Added live TLS leaf-certificate rotation on the existing listener. A candidate context validates a certificate/key pair before the active listener context changes; the API returns the new leaf certificate SHA-256 fingerprint for deployment audit records.
- Added a per-replica global token bucket (default 100 requests/second, burst 128) and aggregate accepted/rate-limited counters without per-client IP/address/query tracking. TLS demo flags expose bounded rate/burst configuration.
- Added tests for successful certificate rotation observed by new handshakes, failed key-pair rotation leaving the prior certificate active, rate-limit exhaustion, counter privacy, configuration bounds, and rejection of rotation on HMAC-only servers.
- Added a red-team regression demonstrating that a malicious but correctly authenticated TLS replica can falsify a PIR answer while retaining the expected snapshot hash; the current protocol detects snapshot divergence, but does not prove honest computation.
- Operational guidance covers leaf renewal, trust-root overlap for CA rotation, rollback, and external edge controls. The global limiter is not per-client and cannot by itself prevent distributed denial of service.
- Limitations: demo listeners remain in one process; two-server PIR collusion still reveals the index; no authenticated database update/manifest publisher, independent-operator deployment, or production security is claimed.

# Project identity

## AEGIS branding transition (v0.22.0 research line; no protocol version change)

- Renamed the project identity to **AEGIS — Anonymous Encrypted Garlic-routed Internet Shield**. The shield metaphor expresses the intended focus on active resistance to mass surveillance.
- Renamed the Python distribution from `rea-anon-lab` to `aegis-anon-lab`; added AEGIS-prefixed console-script aliases while keeping all `rea-anon-*` commands working for compatibility. The import namespace remains `anonlab`.
- Updated current README, CLI descriptions, and newly generated benchmark metadata to identify AEGIS. Historical experiment data/report labels remain unchanged for provenance.
- Intentionally preserved legacy v1 protocol domain strings, AAD prefixes, relay identity hashing labels, directory protocol identifier, and KDF context. Rebranding alone must not change derived keys or wire transcripts; migrating these requires a separately versioned protocol change and interoperability tests.
- **Capability caveat:** AEGIS is the adopted project name/acronym, not a claim of complete garlic routing. The current prototype remains a custom, loopback-oriented, layered multi-hop relay experiment; garlic-clove batching/delivery semantics are not implemented.

---

## v0.22.0 — WINDOW_UPDATE sparse-credit flush timer follow-up (research package)

- Added configurable upper-bound flush timer for pending sub-threshold receive credit, preserving the 2 ms default.
- Added a paired, order-rotated three-condition matrix (0.5/2/5 ms), holding the 64 KiB credit threshold and default scheduler constant.
- Ten trials per configuration showed a +23.94% median paired bulk-goodput delta at 5 ms, but interactive p95 changes remained mixed (+0.18% early and +0.98% late); no default change was justified.
- Validation and raw results are recorded in `docs/WINDOW_UPDATE_TIMER_SENSITIVITY_V0.22.0.md` and `experiments/window-update-timer-sensitivity-v0.22.0.json`.
- Added cross-profile follow-up for `intercontinental` and `constrained` shaping profiles (two trials per timer/profile); results do not show a universal interactive-latency improvement, so the default remains 2 ms. See `docs/WINDOW_UPDATE_TIMER_CROSS_PROFILE_V0.22.0.md` and the paired JSON records in `experiments/`.
- Added a sparse-interactive follow-up with 250 ms between four small requests, testing 2 ms vs 5 ms for four paired trials each under both `metro` and `intercontinental` profiles (16 runs). The 5 ms timer reduced median paired bulk goodput by 7.80% and worsened early/late p95 by 10.87%/4.71% in `metro`; in `intercontinental`, goodput fell 1.05% and late p95 worsened 3.55%. Keep 2 ms as default. See `docs/WINDOW_UPDATE_TIMER_SPARSE_INTERACTIVE_V0.22.0.md` and `experiments/window-update-timer-sparse-matrix-v0.22.0.json`.

# Changelog

## v0.25.0 — TLS transport option for two-server PIR RPC

- Added optional TLS 1.2+ transport with server certificate chain and hostname verification. In TLS mode, requests/responses use TLS record integrity/confidentiality and the client does not receive server HMAC PSKs; the client remains anonymous at the TLS client-certificate layer.
- Added `aegis-pir-rpc-tls-demo`, using separate certificate identities for two loopback listeners, a configured CA, and explicit server hostnames.
- Kept legacy HMAC transport available only for loopback compatibility; remote binds require TLS, `allow_remote=True`, and no client-shared HMAC key. Client TLS contexts must enforce certificate and hostname verification.
- Bounded TLS handshake/shutdown and frame read/write duration to 5 seconds and listen backlog/active RPC handlers to 128; nonce/timestamp replay checks and snapshot consistency validation remain active.
- Added TLS tests for successful PIR reconstruction without client-shared HMAC secrets, wrong CA, hostname mismatch, TLS context requirements, and remote bind guardrails.
- Limitations: TLS does not hide client IP/timing/size metadata; two PIR servers can collude to recover the index; current TLS demo uses one host/process; no signed database update protocol, blind credentials, independent-operator deployment, or production readiness is claimed.

## v0.24.0 — authenticated loopback PIR RPC research prototype

- Added `aegis-pir-rpc-demo`, which exercises two separately bound loopback TCP PIR endpoints using distinct per-endpoint 256-bit pre-shared keys.
- Added HMAC-SHA256 message authentication with separate request/response domains, 256-bit request nonces, a 60-second timestamp window, a bounded replay cache, and fail-closed behavior on malformed or unauthenticated messages.
- The client sends masked query vectors only (never the selected index), correlates replies to nonces, and rejects replica dimension or snapshot-fingerprint mismatches.
- Added tests for retrieval, target-index absence, explicit collusion recovery, HMAC tampering, replay rejection, response modification, endpoint/key separation, loopback-only binding, and replica mismatch.
- Security boundary: this is a loopback harness, not a production or remote transport. HMAC does not encrypt traffic, shared keys are unsuitable for untrusted public clients, and an observer that sees both queries can recover the index. No TLS, independent-host guarantee, rate limiting, anonymous access path, or deployment readiness is claimed.


## v0.23.0 — route, PIR, and chunk-sharing research prototypes

- Added `aegis-route-select`: offline route scoring using measured link RTTs, geometry-derived lower bounds for missing measurements, capacity/load/failure penalties, and hard ASN/family/subnet diversity constraints. A pinned confirmed guard is mandatory; the selector does not automatically rotate guards.
- Added `aegis-pir-demo`: an information-theoretic two-server XOR PIR reference protocol over identical fixed-width replicated rows, with exhaustive small-domain distribution tests. The CLI demonstrates both server computations locally; it is not a distributed service.
- Added `aegis-share-demo`: a chunk-level 2-of-2 XOR share primitive with fixed-width chunks and client-local SHA-256 reconstruction integrity checks. This is not connected to AEGIS relay transport.
- Added architecture documents that explicitly distinguish implemented prototypes from non-implemented ZK credentials, FHE, native Rust/QUIC transport, live multipath routing and browser WebAssembly/WebTransport integration.
- Preserved legacy v1 cryptographic domain strings and kept the TCP relay implementation as the control. No production-anonymity, global-observer, or clearnet-equivalent-latency claim is made.
- Validation results are in `experiments/VALIDATION_AEGIS_V0.23.0.md`; the new prototypes are covered in `tests/test_route_selection.py`, `tests/test_pir.py`, and `tests/test_secret_sharing.py`.


## v0.22.0 — WINDOW_UPDATE sensitivity follow-up (research package)

- Added a paired, order-rotated threshold matrix for 16, 32, 64 and 128 KiB `WINDOW_UPDATE` credit batches while holding the default write scheduler constant.
- Reported bulk goodput/completion, early and late interactive RTT, exit-relay update-command counts, and flow-credit pauses over 1 ms.
- Added bounded-input validation, a default-threshold control, metadata/limitations, and regression tests for paired-delta analysis and connection cleanup.
- The byte threshold is isolated while the existing 2 ms sub-threshold flush timer stays fixed; this experiment does not claim a universally optimal threshold.
- Validation and raw results are recorded in `docs/WINDOW_UPDATE_BATCH_SENSITIVITY_V0.22.0.md` and `experiments/window-update-batch-sensitivity-v0.22.0.json`.

## v0.22.0 — relay-stage diagnostics follow-up (research package)

- Added opt-in, bounded relay-side stage metrics for command dispatch, downstream response waits, reply/event sends, destination reads/writes, and flow-credit waits.
- Added per-hop summaries to the mixed-workload benchmark, including control-operation counts and flow-credit pauses lasting at least 1 ms.
- Kept relay instrumentation disabled by default and excluded payloads, stream IDs, relay IDs, and addresses from its event records.
- Added regression tests for metric presence, bounded schema/privacy, and disabled-by-default behavior.
- Preserved the default write scheduler; an earlier three-trial metro A/B sample recorded an approximately 10.7% median bulk-goodput regression for round-robin, while the latest instrumented sample showed mixed latency results and only a 1.15% goodput change.


## 0.22.0 — bounded round-robin write scheduling (opt-in)

- Added an experimental per-circuit scheduler that sends at most one queued WRITE per ready stream per round, preserving FIFO command order within each stream and coalescing a bounded round into one socket drain.
- Added hard caps for scheduler backlog (512 commands and 8 MiB), a bounded diagnostic trace containing only ephemeral logical stream IDs, fail-closed handling after uncertain socket writes, and admission rejection without poisoning an otherwise healthy circuit.
- Kept round-robin scheduling opt-in (`TelescopingClient(fair_write_scheduling=True)`) because A/B results did not establish a consistent throughput or latency win. The previous batch dispatcher remains the default.
- Added `rea-anon-scheduler-bench`, a mode-interleaved A/B benchmark reporting throughput, finite-flow Jain index, tail latency, integrity, relay observability and cleanup.
- Three-trial A/B tests for 2/4/8 streams found Jain-index improvements of +0.0092 / +0.0036 / +0.0022, while goodput changed +4.47% / -8.93% / -1.44%; p95 latency changed -6.03% / +9.14% / +2.96%. The result is a trade-off, not a general improvement.
- Validation: 143 tests passed, 11 subtests passed. The round-robin integration test confirms interleaving across four streams, payload integrity and zero queued command/byte budget after completion. The scheduler admission-limit test confirms fail-fast backpressure does not close the circuit.
- This remains a single-host loopback research protocol, custom and unaudited; no WAN, Tor-equivalence or production anonymity claim is made.

## 0.21.0 — stream fairness observability

- Added per-stream completion time, returned bytes, derived goodput, and Jain completion-rate index to the loopback network benchmark.
- Added `rea-anon-fairness-bench`, a repeatable matrix over 1/2/4/8 streams with rotated trial order.
- Added seven tests for Jain index inputs, matrix validation, per-stream result presence, integrity, observability, and cleanup.
- The v0.21 metro matrix completed 12 runs successfully. The fairness index declined at 4 and 8 streams; this release records the finding rather than claiming that fairness has been fixed.
- Clarified that the metric is a finite-transfer completion-rate proxy, not a steady-state congestion-control guarantee.


## 0.20.0 — loopback network-condition testbed

- Added `rea-anon-network-impairment-bench` and a bounded IPv4-loopback TCP proxy that shapes one-way delay, deterministic-seed jitter, and shared aggregate bandwidth per proxy direction.
- Rate limits are shared across all concurrent TCP connections through a proxy rather than being assigned independently per connection. Added a maximum active-connection admission bound and queue-depth metrics.
- Added LAN, metro, intercontinental, and constrained synthetic profiles plus a sparse-write workload. All tested cases check payload integrity, relay observability, queue bounds, and complete cleanup.
- Exploratory matrix (two trials per profile, small payloads) showed median circuit p50 latency rising from 2.766 ms in the zero-delay profile to 377.340 ms in the intercontinental profile and 916.517 ms in the constrained profile; sparse high-delay writes were slower still. This exposes RTT sensitivity; it is not a real WAN estimate.
- Important limitation: the proxy operates on TCP stream read chunks, not IP packets; it does not simulate packet loss or TCP retransmissions. The direct control uses one shaped link while the circuit uses four, so this is a path-length diagnostic, not an equivalent privacy/performance comparison.
- Validation: 130 tests passed, 11 subtests passed; the network-condition matrix completed 12 runs with integrity, observability, cleanup, and queue-bound checks passing.
- The protocol remains custom, loopback-only and unaudited; no anonymity or production-security guarantee is claimed.

## 0.19.0 — coalesced read-window credits

- Accumulate consumed response bytes and issue authenticated `WINDOW_UPDATE` commands at a bounded threshold (default 64 KiB) instead of issuing one command for every 16 KiB read.
- Add a 2 ms delayed flush when the application needs more data but the byte threshold has not been reached, so sparse streams continue rather than deadlocking behind the window.
- Allow a single update to grant up to the 256 KiB maximum stream window; the relay rejects any update that would exceed the maximum available credit.
- Added configuration and wire-body boundary tests, a sparse-stream stall test, and a server-push test asserting fewer credit commands than chunks.
- Five randomized-order loopback trials with 8 × 256 KiB streams measured median throughput of 330.34 Mb/s (immediate updates), 412.80 Mb/s (32 KiB batching), and 493.27 Mb/s (64 KiB batching); median update counts fell 104 → 56 → 32. On a smaller 8 × 64 KiB workload, updates remained at 8 for each configuration and no robust gain was established. The benefit is workload-dependent and not a WAN forecast.
- Validation: 117 tests passed, 11 subtests passed. ZIP extraction/source tests and installed-wheel smoke tests are recorded in `experiments/VALIDATION_V0.19.0.md`.
- This remains a loopback-only custom protocol with no independent cryptographic audit and no production anonymity guarantee.

## 0.18.0 — cache immutable relay descriptors and profile the hot path

- Cache each bound `RelayNode`'s immutable `RelayDescriptor`; the cache key tracks the listener port/host, identity digest, and strong references to onion/identity private-key objects so endpoint/key replacement invalidates it safely.
- Added regression tests for repeated reads, access before bind, endpoint/digest invalidation, and onion-key replacement.
- Added `rea-anon-profile-hotpath`, a reproducible cProfile command that writes selected aggregate function counters/times and does not capture application payloads or local variables.
- cProfile showed `RelayDescriptor.__post_init__` calls drop from 1,429 to 7 and `_ensure_loopback` / `ipaddress.ip_address` calls drop from 1,458 to 36 in the matched loopback profile. Descriptor property cumulative time fell from 29.54 ms to 1.31 ms under cProfile.
- Five-trial, same-host 8 × 1 MiB comparisons showed median goodput changes of +14.3%, +17.2%, and +12.8% at pipeline depths 1, 2, and 4 respectively. Runs were separate (not interleaved); local variance/system drift remains a limitation. All integrity, observability and cleanup checks passed.
- Validation: 115 tests passed, 11 subtests passed. Wheel install and profile CLI smoke checks passed. See `docs/PERFORMANCE_PROFILE_V0.18.0.md` and raw experiments for details.
- This is an implementation optimization in a loopback-only, custom, unaudited research protocol; it does not establish anonymity, Tor-equivalent security, or WAN performance.

## 0.17.0 — bounded pipelined writes

- Added `DuplexCircuitStream.write_pipelined()` with ordered command framing,
  per-hop sequence correlation, payload/chunk validation, and a client-side
  maximum pipeline depth of four.
- Relays enqueue WRITE bytes in command order and handle their drain/ACK work in
  tracked tasks so subsequent bounded WRITE frames can be read before earlier
  ACKs travel back. Added per-stream command/byte limits and a per-circuit
  aggregate pending-write byte budget.
- Serialized client HALF_CLOSE/CLOSE with the write lock and rejected relay-side
  control messages that overtake pending writes.
- Added a new `rea-anon-pipeline-bench` command comparing maximum in-flight depths
  1, 2, and 4, with rotating test order and integrity/observability/cleanup checks.
- Benchmark (8 × 1 MiB streams, 64 KiB chunks, 5 trials per depth) measured
  234.45 Mb/s at depth 1, 220.15 Mb/s at depth 2, and 237.31 Mb/s at depth 4.
  The 1.2% depth-4 advantage is not robust, and a smaller workload made depth 4
  slower. The release therefore claims a functional bounded pipeline, not a
  proven speedup.
- Validation: 109 tests passed, 11 subtests passed. Results and residual risks
  are recorded in `docs/WRITE_PIPELINE_V0.17.0.md`,
  `docs/WRITE_PIPELINE_SECURITY_REVIEW_V0.17.0.md`, and `experiments/`.
- This remains a loopback-only, custom, unaudited, non-production protocol.

## 0.16.0 — larger bounded writes and three-way batching study

- Raised the maximum acknowledged client write from 64 KiB to 256 KiB; response events remain at 16 KiB and the read-credit window remains unchanged.
- Extended the paired benchmark to compare 16 KiB, 64 KiB, and 256 KiB writes with rotating trial order and per-workload acknowledgement counts.
- Changed the benchmark default workload to 256 KiB per stream so every configured batch size has a meaningful effect on acknowledgements per stream.
- Added an exact 256 KiB full-duplex echo test and retained local rejection of writes above the configured cap.
- Three-trial loopback comparison (8 × 256 KiB streams) measured 178.66 Mb/s at 16 KiB, 230.15 Mb/s at 64 KiB, and 246.17 Mb/s at 256 KiB; all nine integrity, observability, and cleanup checks passed.
- Validation: 106 tests passed, 11 subtests passed. Wheel build/install and CLI smoke checks passed; extracted-ZIP tests are recorded in the validation report.
- Added documentation of the throughput/memory trade-off and explicit limits; no WAN, Tor-equivalence, or production-security claim is made.

## 0.15.0 — acknowledged write batching

- Raised the maximum application write batch from 16 KiB to 64 KiB while preserving the 16 KiB response-event chunks and 64 KiB receive-credit window.
- Updated the duplex benchmark to vary write batch size, record acknowledgement amortization, and compare 16 KiB vs 64 KiB under matching stream/payload settings.
- Added a paired multi-trial benchmark command, `rea-anon-write-batch-bench`, for reproducible performance comparisons.
- Updated tests to exercise an exact 64 KiB write and reject writes above the cap.
- Five-trial paired loopback benchmark (8 × 64 KiB streams) measured 193.71 Mb/s median goodput at 64 KiB batches vs 152.46 Mb/s at 16 KiB (+27.1%); every integrity, observability and cleanup check passed. See the report and raw JSON in `experiments/`.
- Validation: 106 tests passed, 11 subtests passed.
- Security properties are unchanged in intent; larger individual commands increase per-command transient memory up to the explicit 64 KiB cap. No production or anonymity claim is made.

## 0.14.0 — experimental full-duplex streams

- Added `TelescopingClient.open_stream()` and `DuplexCircuitStream` for persistent bidirectional TCP streams over the existing three-hop lab circuit.
- Added stream OPEN/START/WRITE/HALF_CLOSE/WINDOW_UPDATE/CLOSE control operations and unsolicited, per-hop AEAD-wrapped data/EOF events.
- Added bounded per-stream read credit (64 KiB initial, 256 KiB maximum), 16 KiB chunks, and credit replenishment after application reads.
- Added event-sequence validation, relay stream-ID remapping, readiness gates to prevent stream events overtaking START acknowledgements, and stream cleanup.
- Added full-duplex tests for half-close, simultaneous stream isolation, 192 KiB server push beyond the initial window, size limits and benchmark cleanup.
- Added the `rea-anon-duplex-bench` loopback benchmark and security/validation documents.
- Validation: 105 tests passed, 11 subtests passed.
- Performance remains experimental: the v0.14 historical benchmark reported approximately 130.56 Mb/s median duplex goodput vs 2,324.10 Mb/s direct TCP on 8 × 64 KiB streams. This is not a Tor comparison or a security result.

## 0.13.0 — multiplexed one-shot streams

- Added concurrently correlated one-shot request/response streams, cancellation, and same-circuit benchmark.
- Validation: 100 tests passed, 11 subtests passed.

## Unreleased — mixed-workload scheduler evaluation

- Added `rea-anon-mixed-workload-bench` for a bulk transfer competing with an early interactive flow and a connection opened after a controlled delay.
- Reports bulk time-to-first-byte, goodput and completion time; interactive first-response RTT, p50/p95 RTT and flow completion; payload integrity; relay observability; and teardown status.
- A/B trials reuse the same deterministic shaper seed for both schedulers per trial and alternate condition order.
- Scheduler remains opt-in: the initial matched-seed, five-trial metro experiment shows a throughput regression with no consistent interactive-latency win.
- No package version bump; these are research and validation additions to the v0.22.0 worktree.

## Unreleased — verifiable PIR design work

- Added `docs/AEGIS_V0.27_VERIFIABLE_PIR_DESIGN.md` documenting the malicious-replica threat model, required proof statement, candidate construction families, snapshot lifecycle, fail-closed client behavior, red-team acceptance matrix, and release gates.
- This is a design-only artifact. No proof system or verified PIR implementation is claimed; v0.26.0 behavior and limitations remain unchanged.
