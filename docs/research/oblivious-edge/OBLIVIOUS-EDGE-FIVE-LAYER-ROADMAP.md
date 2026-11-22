# AEGIS — Oblivious Edge: Five-Layer Research Roadmap

**Status:** research proposal; not implemented or adopted  
**Branch:** research/oblivious-edge-five-layer-roadmap  
**Purpose:** Preserve the complete proposed direction for research toward ≥90% of direct Surface Web performance (latency and goodput) while pursuing AEGIS's own explicit anonymity and privacy objectives. Tor is mentioned only as an illustrative example/reference where useful; AEGIS is not a Tor implementation or clone. These are goals, not established results.

> There is no single silver bullet. Each layer addresses a distinct bottleneck. Privacy and performance claims must be demonstrated independently, and no optimization may silently weaken the threat model.

## Goals and non-negotiable constraints

- Target at least 90% of direct Surface Web performance in latency and throughput/goodput, measured against fair, controlled baselines.
- Develop and validate AEGIS's own anonymity and privacy guarantees against its explicit threat model. Tor may be used as one optional external reference for selected comparisons, not as the product definition, architecture to reproduce, or sole success criterion.
- Do not trade away privacy/security to reach speed targets.
- Treat the project as production-oriented, but do not equate research approval with production readiness.
- Preserve the existing AEGIS/THOR baseline and PR #34 (OPEN, Draft). Do not alter PR #34 as part of this roadmap.
- Keep the transport research (P4c.1 → P4c.2 → P4d) independent from the EDGE architecture research. No adoption or production-path changes from this document.

## Five layers

### Layer 1 — Network architecture: Oblivious Edge

#### Idea A — Two-stage metropolitan separation of knowledge

Place two independently operated nodes in the same metro/IXP region, subject to verified topology and routing:

1. **Blind Ingress Relay:** lightweight forwarding/encapsulation. It sees the client's source IP and connection metadata, but is designed to see only encrypted traffic for the next stage—not the final destination.
2. **Attested Egress Enclave (TEE):** receives traffic via the ingress, processes destination and payload within the protected execution boundary, and initiates destination connections. It should not learn the client's real source IP.

Investigate OHTTP, MASQUE, or equivalent encapsulation; none is assumed to be suitable without analysis.

**Expected advantage:** separate source and destination knowledge while potentially avoiding the long geographic path of multi-country relay chains.

**Risks and assumptions:** timing/volume correlation; metadata and identifiers; malicious or compromised ingress/egress; operator collusion; external observers; TEE vulnerabilities, side channels, firmware and supply-chain risk; destination-side and egress observability. Operator independence alone is not a cryptographic guarantee.

#### Idea B — Geodesic corridor routing for international destinations

When policy requires an international exit, explore routing along geographically and topologically sensible corridors (e.g., São Paulo → Miami → Virginia as a candidate path), avoiding arbitrary continent-spanning detours.

Evaluate actual submarine cable/terrestrial paths, BGP/ASN routing, peering, congestion, jurisdiction, route diversity, failure behavior and latency. A straight geographic line does not establish the actual network path; example corridors are hypotheses, not measured routes or recommendations.

### Layer 2 — Invisible control plane: PIR, blind tokens, attestation

#### Idea C — PIR-based directory discovery and DNS privacy

Evaluate Private Information Retrieval (PIR), including SimplePIR/DoublePIR families, for privacy-preserving node-directory lookup and DNS-related discovery.

Questions: server-side query leakage, multi-server trust assumptions (if any), computational/communication cost, freshness, malicious responses, integrity/authentication, cache behavior, and whether queries can be linked to sessions. “Only at session setup” is not assumed: query frequency and cache misses must be measured.

PIR can hide which record was queried under its scheme/assumptions; it does not automatically hide the client's network identity, the selected edge, or later traffic.

#### Idea D — Blind-signature access tokens / Privacy Pass

Explore unlinkable tokens for abuse controls, quotas, and bandwidth admission without requiring user login or a stable tracking identity.

Investigate issuance, redemption, double-spend prevention, expiry, token binding, rate limits, revocation, issuer–redeemer collusion, abuse handling, privacy leakage, and operational cost. Token validation cost and unlinkability must be benchmarked and cryptographically reviewed; do not assume microsecond validation or perfect unlinkability.

#### Idea E — Remote attestation bound to ephemeral session keys

Client validates a hardware attestation quote and an ephemeral key binding before sending sensitive traffic. Research supported TEE platforms such as Intel TDX and AMD SEV-SNP, including exact threat models and platform limitations.

Define what attestation establishes (measurement/platform evidence, freshness, key binding, verifier policy) and what it does not (absence of vulnerabilities, side channels, malicious destinations, correct network behavior, or trustworthy operators). Include update, rollback, revocation, transparency, reproducible build, measurement, key lifecycle and fail-closed requirements. “Official audited binary” must not be asserted merely from a quote.

### Layer 3 — High-throughput transport (connected to THOR/P4d research, not adopted)

#### Idea F — Pipelined flow-control with cumulative offsets

Explore multiple outstanding flow-control updates using absolute/cumulative offsets (QUIC-like concepts) rather than relative increments. Specify monotonicity, duplicate and out-of-order handling, overflow safety, stream/connection limits, backpressure, fairness, cancellation, receiver memory bounds, and invariants.

This is a hypothesis. It must not be assumed immune to reordering or duplicates until specified and tested.

#### Idea G — Multipath QUIC and Fountain Codes

Investigate Multipath QUIC and fountain/erasure coding (e.g., RaptorQ) to reduce dependence on a single path and potentially avoid retransmission wait when data can be reconstructed from sufficient received symbols.

Evaluate realistic path independence, correlated loss, coding overhead, CPU, memory, latency, ordering, congestion control, fairness, packet amplification, protocol interactions, and whether recovery improves end-to-end goodput. Coding is not automatically faster or more efficient; use conventional retransmission baselines too.

#### Idea H — Zero-copy I/O and timer/scheduling work

Explore zero-copy paths, NIC/host/enclave integration, SR-IOV, DPDK, DMA boundaries, confidential-memory compatibility and timer/scheduler behavior. Measure copies, context switches, CPU, memory bandwidth, packet processing and security isolation.

The prior P4c timer quantization hypothesis (roughly 15.6 ms Windows behavior) is not yet proof of a universal timer cause. The 1 ms timer configuration must be measured on each environment and its resource/power/security tradeoffs documented. “Line rate” and “1 ms precision” are targets to validate, not claims.

### Layer 4 — Traffic-analysis resistance

#### Idea I — Crowd mixing with minimum concurrency

Explore shared egress/mixing policies with a minimum active-session threshold (k-anonymity-like temporal crowd). If an edge is below threshold, consider routing to a busier regional pool.

Do not equate k active sessions with k-anonymity. Investigate distinguishability by timing, volume, burst shape, direction, duration and user behavior; pool transitions; low-load leakage; failure and adversarial occupancy; collusion; and the added latency/bandwidth cost. Define fallback behavior that avoids privacy downgrade or silent isolation.

#### Idea J — Fixed-size cells and idle-only padding

Evaluate fixed-size traffic cells and dummy traffic injected during idle periods as a low-latency shaping candidate.

Idle-only padding may preserve bursts and silences, so it cannot be presumed to defeat website fingerprinting. Compare against stronger shaping baselines, measure traffic overhead and latency, and test with modern classifiers. Define cell size, scheduling, padding budget, burst behavior, and how shaping responds to sustained activity.

#### Idea K — Session and key rotation

Investigate short-lived ephemeral keys, circuit/session rotation, compartmentalization, forward secrecy and unlinkability.

Rotation itself may create linkable transitions, handshakes, timing patterns, resource costs, or failures. Specify scope, cadence, overlap, rekey, migration, identity continuity, replay protection and threat-model effects; do not assume frequent rotation automatically hides a volumetric signature.

### Layer 5 — Client-side latency and cold-start reduction

#### Idea L — Pre-attested warm tunnel pool

Explore a client-managed pool of 2–3 already validated, warmed sessions, ready before the user requests navigation.

Evaluate idle resource costs, attestation freshness, key rotation, expiry, concurrency, pool selection, privacy linkability, IP/exit diversity, stale state, failure recovery, background battery/CPU/network usage and platform restrictions. The “2–3” pool size is a proposal, not a validated optimum.

#### Idea M — Parallel resolution and speculative prefetch

After receiving initial page content, explore private-cache DNS resolution and safe speculative fetching of referenced domains while the browser parses content.

Respect browser security and privacy: avoid speculative requests that reveal browsing intent, trigger side effects, bypass user consent, expose cookies/credentials, or fetch third-party trackers. Measure actual dependency graphs and cache hit rates. DNS prefetch alone cannot remove dependency, server, rendering, or TLS costs.

## Consolidated matrix

| Layer | Ideas | Intended contribution | Research phase |
|---|---|---|---|
| Network | A: metro two-stage Oblivious Edge; B: geodesic corridors | Source/destination knowledge separation; reduce avoidable path distance | EDGE-01, EDGE-02, EDGE-04 |
| Control | C: PIR discovery/DNS; D: blind tokens; E: key-bound attestation | Reduce control-plane privacy leakage; anonymous admission; verify execution evidence | EDGE-01, EDGE-02 |
| Transport | F: cumulative-offset pipelining; G: Multipath QUIC + coding; H: zero-copy/timer work | Throughput, congestion/loss resilience, processing overhead | P4c.1 → P4c.2 → P4d, then separate follow-up experiments |
| Traffic analysis | I: crowd mixing; J: cells/idle padding; K: session/key rotation | Reduce traffic distinguishability and correlation | EDGE-03 |
| Client | L: warm pre-attested tunnel pool; M: parallel DNS/prefetch | Reduce cold-start and dependency delays | EDGE-02, EDGE-04 |

## Measurement and validation rules

### Performance

Compare direct Surface Web, current AEGIS/THOR baseline and candidate Edge/hybrid paths under matched conditions. Other privacy systems (including Tor) may be optional contextual references where methodologically appropriate, but are not the design target: source/destination, content/payload, duration, network conditions, cache state, browser/runtime, repetitions and workload.

Report:
- RTT and latency distributions p50/p95/p99;
- TTFB;
- goodput/throughput and retransmissions;
- handshake/circuit setup;
- CPU, RAM, energy where measurable;
- cell/padding/coding overhead and bytes;
- connection concurrency and multiplexing;
- packet loss, reordering, congestion, stability;
- browser FCP/LCP and full-load metrics for controlled static/dynamic pages;
- failures and exclusions, raw observations, confidence intervals and seeds.

The ≥90% goal must be operationalized separately for latency and goodput. Do not hide absolute timings behind ratios or average away bad tails.

### Anonymity and traffic-analysis evaluation

Use consented/appropriate datasets, reproducible captures, group-disjoint splits, multiple seeds, adaptive and open-world attackers, and baselines. Evaluate single-side and two-sided observers, low/normal/high concurrency, malicious/compromised nodes and operator collusion. Report top-1 accuracy, confidence, attack success, false positives, bandwidth overhead, latency and robustness across conditions. Toy classifiers or loopback-only data cannot establish network anonymity.

### General evidence rules

- Loopback is not WAN.
- Emulated RTT is not real Internet routing.
- A performance improvement is not anonymity evidence.
- TEE confidentiality is not network anonymity.
- PIR is not full traffic privacy.
- Blind tokens do not solve traffic correlation.
- Attestation does not prove software is vulnerability-free.
- No adoption from a single benchmark, a single seed, or a point estimate.
- Preserve failed, inconclusive and excluded trials with reasons.
- Reproducibility requires scripts, configuration, raw data, manifests and integrity checks.

## Proposed phases and gates

### EDGE-01 — Feasibility and threat model
Deliver architecture/data-flow, trust boundaries, adversary matrix, formal separation-of-knowledge analysis, physical/network feasibility, privacy risks, falsifiable hypotheses and gates. No code. Gate: approved_for_prototyping, rejected, or inconclusive with evidence.

### EDGE-02 — Prototype and real-page performance
Only after EDGE-01 approval. Isolated prototype and controlled browser corpus. Measure RTT, goodput, TTFB, FCP, LCP, full-load, resources and reliability. No anonymity claims.

### EDGE-03 — Fingerprinting and correlation
Evaluate WF classifiers, bidirectional timing correlation, fixed cells, cover traffic, concurrency/mixing and rotation. Quantify attack reduction against bandwidth/latency/resource cost. Privacy gate independent of EDGE-02.

### EDGE-04 — Comparative architecture
Compare AEGIS candidate architectures (Oblivious Edge, multi-stage/multi-hop variants, and hybrids) under common performance and AEGIS threat-model assumptions. External systems such as Tor may be included only as contextual references, not as the architecture AEGIS is intended to reproduce. Evaluate privacy, latency, throughput, cost, failure, operator trust, scalability and availability. Produce evidence-backed recommendation, not preselected winner.

## Dependencies and isolation

- P4c.1: stabilize test suite without weakening assertions.
- P4c.2: measure timers and decompose RTT, locks, scheduling, processing and ACK behavior.
- P4d: specify and test pipelined flow control in a separate experiment.
- EDGE-01 can proceed in parallel as theoretical architecture research.
- EDGE-02 may use transport variants only as labeled experimental arms; no unvalidated P4d optimization becomes assumed baseline.
- EDGE-03 does not depend on performance approval.
- EDGE-04 integrates results only when each evidence set is traceable and independently reviewed.

## Decision discipline

All ideas A–M are saved as hypotheses. None are implemented, accepted, deployed, or proven. Performance targets (≥90% of direct Surface) and AEGIS anonymity/privacy objectives remain defined by its own threat model; Tor is an illustrative reference only, not the target product or required architecture. Each future phase must report full commit SHA, changed files, test results, reproducible artifacts, limitations and a clear verdict. PR #34 remains untouched.
