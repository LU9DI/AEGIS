# AEGIS production-network gap audit

**Status:** initial repository audit; not a security certification or a claim that the listed systems are production-ready.  
**Baseline inspected:** repository sources and design notes available on 2026-10-14, including `docs/THREAT_MODEL.md`, `docs/ONION_PROTOTYPE.md`, `docs/ROADMAP.md`, `src/anonlab/onion_protocol.py`, `src/anonlab/onion_relay.py`, and the loopback relay/benchmark implementation.

## Executive finding

AEGIS contains useful research components—simulation, loopback relay testbeds, layered AEAD envelopes, sequence checks, route-scoring experiments, and extensive transport benchmarks. These are not yet a complete public anonymity network. The current onion path is deliberately loopback-only and depends on keys pre-shared by local benchmark orchestration. A successful loopback benchmark establishes behavior and performance only for that testbed; it does not establish resistance to network observers, a secure distributed key exchange, or browser-level performance.

**Immediate engineering decision:** keep public exposure disabled. Specify and review the protocol and threat model before enabling independent-host relay traffic.

## Gap matrix

| Area | Observed baseline | Production gap / risk | Required evidence before closing |
|---|---|---|---|
| Security goals and threat model | `docs/THREAT_MODEL.md` lists ISP, malicious relay, multi-point and global observers, and explicitly excludes several attacks | Threat assumptions and measurable goals are distributed across historical version notes; no evidence that the complete live network satisfies them | Versioned threat model with attacker capabilities, trust assumptions, metadata visibility by hop, non-goals and testable security claims |
| Handshake and key lifecycle | Onion envelope uses ChaCha20-Poly1305; relay keys are pre-shared by local test orchestration | No authenticated ephemeral key exchange or demonstrated forward secrecy; key rotation and compromise recovery are not implemented in this prototype | Adopt a reviewed handshake/library; transcript and downgrade tests; key confirmation, per-hop derivation, rotation and compromise analysis reviewed independently |
| Wire protocol | Custom binary request/response envelopes with version, circuit ID, sequence and AEAD authentication | Custom framing is not a reviewed or interoperable protocol; envelope integrity does not solve traffic analysis | Written state machine and wire specification; fuzzing; parser differential tests; malformed/truncated/oversized-frame tests; independent protocol review |
| Replay and circuit state | Sequence checks per live connection and process-local circuit-ID registry | Registry resets on restart, is process-local, has a fixed capacity and does not create a distributed replay defense; operational exhaustion behavior needs broader testing | Explicit replay model tied to ephemeral keys and circuit lifecycle; restart/reconnect/reordering tests; bounded state and exhaustion tests |
| Relay identity and directory | Directory and signed-descriptor research modules exist separately | The onion prototype does not consume a production signed, expiring, revocable directory or establish independent relay identity | Authenticated descriptor schema, signatures, expiry/revocation, key rotation, consensus/trust model, stale/malicious directory tests |
| Path selection | Route scoring includes latency and diversity heuristics in research modules | Heuristics are not a demonstrated defense against Sybil, operator concentration, collusion or latency-driven centralization | Generated-topology and adversarial simulations; guard persistence; operator/ASN/subnet diversity; documented trust and failure assumptions |
| Distributed operation | Relay and destination processes are started on loopback for tests | No validated independent-host network, bootstrap, public discovery, safe upgrades or failure recovery | Three-or-more independently configured relay nodes across hosts; authenticated circuit establishment; network impairment and restart/failure integration tests |
| Streams and congestion | Research code explores bidirectional streams, multiplexing, flow control and batching | These pieces are not a production-integrated general browser transport; no complete operational congestion strategy is demonstrated | End-to-end stream lifecycle/isolation, multiplexing, congestion control, cancellation, backpressure, bounded memory and starvation tests |
| Exit and application safety | The terminal relay connects to a configured loopback destination in the lab | Exit sees destination and application payload; browser proxy behavior, DNS handling, origin isolation, abuse controls and exit policy are not a deployable product | Explicit exit threat model, DNS-leak tests, origin/circuit isolation, egress policy, abuse response and privacy-preserving operational logging review |
| Traffic analysis | Simulator can explore simplified correlation metrics | No demonstrated realistic defense against packet timing/volume correlation, website fingerprinting, active probing or intersection attacks | Reproducible adversarial experiments with packet direction/timing/volume, baselines, sample sizes, false positives/negatives and stated observer visibility |
| Performance | Raw TCP and onion benchmarks measure loopback paths | Loopback latency/goodput cannot be compared directly with Tor or direct browser page loads; no controlled WAN evidence | Same-host/region/destination comparative methodology; WAN impairment and multi-host runs; p50/p95/p99, throughput, failures, CPU/memory and page-load metrics when a browser exists |
| Operational readiness | Local scripts and CI validate package, tests and artifacts | No demonstrated production deployment, telemetry/alerting, incident response, operator onboarding, upgrade/rollback or key-compromise response | Operational runbooks, threat-reviewed logs/metrics, incident procedures, secure releases, dependency/SBOM process, staged rollout and rollback tests |
| Supply chain and maintenance | Package and test suite run in CI | Passing source/recovery CI does not establish dependency safety, reproducible release builds or long-term maintenance | Pinned/reviewed dependencies, vulnerability response, release provenance, reproducible build checks and maintained security contact/process |

## Ordered engineering milestones

### M0 — protocol and threat-model freeze
- [ ] Consolidate security goals, attacker capabilities, metadata leakage and explicit exclusions into one versioned specification.
- [ ] Document circuit state transitions, handshake, per-hop keys, replay rules, stream semantics and failure handling.
- [ ] Record security decisions and alternatives; identify assumptions requiring external cryptographic review.
- **Exit gate:** reviewers can determine what each relay/client/observer learns and which claims are testable without reading implementation details.

### M1 — secure single-circuit foundation
- [ ] Select a reviewed authenticated ephemeral key-establishment design; do not invent a new handshake/KDF for performance.
- [ ] Define nonce/key separation, forward secrecy, key rotation, circuit teardown and restart behavior.
- [ ] Add protocol fuzzing and tests for tampering, replay, downgrade, truncation, invalid state transitions, resource exhaustion and connection failure.
- **Exit gate:** specification-to-test traceability and independent review of the design before enabling cross-host operation.

### M2 — controlled distributed network
- [ ] Add signed/expiring relay descriptors and a documented directory trust/revocation model.
- [ ] Run independently configured relay processes across at least three hosts; validate circuit construction, bidirectional traffic, failure recovery and stream isolation.
- [ ] Add rate limits, resource quotas, egress restrictions and safe-by-default deployment configuration.
- **Exit gate:** reproducible integration suite passes under loss, latency, churn, restart and malicious-input scenarios; still not a public launch authorization.

### M3 — privacy and adversarial evaluation
- [ ] Test colluding relays, guard/exit compromise, Sybil/concentration, active probing, intersection, timing/volume correlation and operational metadata leaks.
- [ ] Publish experimental setup, attacker visibility, sample sizes, baselines, confidence/uncertainty and limitations.
- [ ] Obtain independent cryptographic and traffic-analysis review.
- **Exit gate:** no unresolved critical/high findings for the proposed threat model; limitations and residual risks documented.

### M4 — performance and operational readiness
- [ ] Compare AEGIS, Tor and direct browsing under equivalent conditions; keep loopback microbenchmarks as a separate control.
- [ ] Measure p50/p95/p99 latency, goodput, browser page-load performance where applicable, resource use, failures and privacy regressions.
- [ ] Implement deployment/upgrade/rollback, incident response, abuse handling, observability and operator guidance.
- **Exit gate:** independent review and reproducible evidence support each published claim; public launch remains a separate decision.

## Non-negotiable safety constraints

- Do not expose the current research relay to the Internet or route personal/sensitive traffic through it.
- Do not treat AEAD, a successful test suite, or low loopback latency as proof of anonymity.
- Do not claim superiority to Tor or near-direct browsing speed without equivalent, reproducible measurements.
- Do not optimize by silently reducing path diversity or removing privacy protections.
- Keep each milestone bounded, testable and separately reviewable. Do not mix public deployment with unfinished protocol research.

## Immediate next implementation task

After M0 is reviewed, choose one bounded M1 task and its acceptance tests. The preferred direction is to integrate a reviewed authenticated ephemeral handshake/key schedule behind a protocol boundary, while preserving the existing loopback harness as a non-production test fixture. This audit does not prescribe an unreviewed custom cryptographic construction.
