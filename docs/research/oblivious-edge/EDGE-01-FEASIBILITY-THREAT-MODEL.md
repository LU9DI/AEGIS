# AEGIS — EDGE-01: Feasibility & Threat Model

**Status:** authorized research phase; investigation/specification only  
**Branch:** research/oblivious-edge-five-layer-roadmap  
**Implementation:** none; no production changes authorized

## 0. AEGIS-native design principle

This is an AEGIS-native architecture investigation. AEGIS is not a Tor implementation, clone, fork, or attempt to reproduce another network's design. Tor and other systems may be optional external references for selected mechanisms or comparative context only. AEGIS's architecture, threat model, guarantees, and success criteria must be defined independently.

The project goal remains at least 90% of direct Surface Web performance in both latency and goodput, alongside strong, explicitly specified anonymity and privacy guarantees. These are goals, not measured results or current claims.

## 1. Scope and isolation

EDGE-01 covers threat modeling, architecture/data-flow specification, cryptographic and protocol feasibility, network-topology feasibility, trust-boundary analysis, falsifiable experiment design, and a documented decision.

It does not authorize implementation, production changes, THOR transport changes, P4c/P4d modifications, PR #34 changes, default-branch writes, merge, deployment, rebase, force-push, or history rewrite. PR #34 must remain OPEN and Draft. If baseline state differs from expectations, stop and report; do not repair or overwrite.

## 2. Architecture hypothesis

Investigate, without presuming success, a two-stage metropolitan design.

### 2.1 Blind Ingress Relay

The ingress sees the client's source IP and ingress-side connection metadata. It should forward opaque encrypted traffic and must not learn the final destination hostname/IP or plaintext application payload. Analyze whether framing, packet sizes, timing, connection reuse, error behavior, retries, identifiers and logs undermine this separation.

### 2.2 Egress Enclave

The egress processes the destination and application data needed to establish outgoing connections, but should not receive the client's real source IP or stable client identity. Analyze the selected TEE's actual limits. Attestation is evidence about measured platform/software state under a vendor trust chain; it is not proof of bug-free code, absence of side channels, safe network behavior or trustworthy operators.

### 2.3 Control-plane dependencies

Model node discovery, directory, DNS/name resolution, PIR, blind-token issuance/redemption, remote attestation, ephemeral key binding, revocation, updates and rollback separately. Do not assume PIR, blind signatures or attestation automatically hide session metadata or traffic relationships.

## 3. Required architecture artifacts

Produce:
1. architecture diagram with client, ingress, egress enclave, control plane, verifier, token issuer, directory/PIR service, DNS resolver, destination and network observers;
2. sequence diagrams for token issuance, attestation, session setup, data transfer, rekey/rotation, failure, revocation and teardown;
3. message/field inventory: source, recipient, visibility, lifetime, persistence, linkability and integrity/authentication;
4. trust-boundary map across operator, ASN, facility, hardware, firmware, software and administration;
5. explicit visibility map for source IP, hostname, destination IP, timing, packet length, direction, volume, connection IDs and tokens.

Mark unknowns rather than replacing them with assumptions.

## 4. Threat model

Analyze independently and in combination:
- malicious/compromised ingress;
- malicious/compromised egress software;
- compromised TEE boundary or exploitable enclave workload;
- malicious cloud/facility operator;
- compromised firmware, microcode, boot chain or supply chain;
- observers near client-to-ingress, ingress-to-egress and egress-to-destination paths;
- observer with simultaneous visibility at multiple points;
- ingress/egress operator collusion;
- destination website or destination-side observer;
- active attacker able to delay, replay, reorder, selectively drop, manipulate congestion or craft responses;
- low-load/isolated-user attacker;
- attacker exploiting tokens, timing, identifiers, DNS/cache behavior or session rotation.

For each, document capabilities, observation points, direct observations, inferences, preconditions/cost, mitigations, residual risk and whether the attack is prevented, constrained, detectable or merely harder. Distinguish single-node compromise from global/passive observation and collusion.

## 5. Separation-of-knowledge matrix

Create a matrix for Client, Ingress, Egress TEE, Control Plane and External Observer covering:
- client source IP;
- destination hostname and IP;
- plaintext payload;
- packet timing, direction and size;
- session identifiers;
- token issuance/redemption linkage;
- DNS/PIR query contents.

Use precise values: visible, encrypted but metadata visible, inferable, unavailable under stated assumptions, or unknown.

Analyze session linkage, token/attestation identifiers, timing/volume correlation, multiplexing, retries, pooling, rotation, and actual independence of operators (ownership, network path, jurisdiction, logging, control plane and infrastructure). Do not claim correlation is prevented merely because no single relay sees both IP addresses in plaintext.

## 6. TEE and attestation feasibility

Compare relevant platform choices, including Intel TDX and AMD SEV-SNP only where deployment models support them. Document protected assets, host/operator visibility, I/O and NIC/DMA path, memory/register protection limits, side channels, quote contents, verification chain, reproducible builds, ephemeral-key binding, freshness/nonces, verifier policy, revocation, patching, rollback resistance and fail-closed behavior.

Identify what remains outside the enclave and why. Do not assume SR-IOV, DPDK or zero-copy can safely deliver packets directly into encrypted enclave memory; document IOMMU, DMA, driver, host and TEE constraints.

## 7. Control-plane feasibility

### PIR
Specify single-server/multi-server assumptions, query/response sizes, compute, bandwidth, latency, integrity against malicious responses, freshness, directory updates, cache behavior, replay, client network metadata leakage and linkage to subsequent sessions.

### Blind tokens
Specify issuer/redeemer roles, unlinkability assumptions, collusion, uniqueness/double-spend handling, rate limits, expiry, revocation, quotas, session binding, metadata leakage and failure modes.

### DNS
Distinguish hiding the query from the resolver from hiding the destination from ingress/observers. Analyze cache/prefetch leakage, authenticated answers, integrity, freshness and where resolution occurs.

## 8. Network and physical feasibility

Do not equate geographic proximity or same-IXP placement with a guaranteed 1–3 ms path. Define how candidate deployments will measure client-to-ingress, ingress-to-egress and egress-to-destination latency distributions; ASN/peering/routes; congestion; path changes; loss; reordering; MTU; queueing; capacity; failure domains; jurisdiction and operator independence.

For international corridors, use actual route and path evidence, not straight-line distance or assumed cable paths. Geodesic selection is a heuristic to test, not proof of the realized network path.

## 9. Low-concurrency and traffic-analysis risks

Treat temporal crowd thresholds as hypotheses, not guarantees. Define independent active user/session, attacker knowledge, ability to create/suppress sessions, distinguishability, low-load behavior, transitions to busier regional pools, fallback leakage, and timing/size/direction/burst/duration signals.

A count of k sessions is not sufficient evidence of k-anonymity. Specify attacks and measurable outcomes before proposing a threshold.

## 10. Falsifiable hypotheses for later phases

Define experiments for at least:
- H1: ingress cannot recover final destination from protocol fields, logs or control-plane metadata under a single-ingress compromise model;
- H2: egress cannot recover the client's real source IP or stable identity under a single-egress compromise model;
- H3: single-side compromise does not reveal a source-destination pair without additional observations, under stated assumptions;
- H4: two-sided observers can/cannot correlate sessions at measured rates under defined traffic and concurrency distributions;
- H5: the metro ingress-egress hop has a measured latency distribution compatible/incompatible with the performance budget;
- H6: attestation/key binding rejects unapproved measurements under the stated vendor trust model;
- H7: PIR and blind-token operations meet specified privacy, freshness and performance requirements.

For each hypothesis specify experiment, control, attacker capability, dataset, sample-size rationale, metrics, proposed acceptance threshold and rationale, exclusions and reproducibility artifacts. Do not invent thresholds without justification.

## 11. EDGE-02/03/04 handoff

EDGE-02 may prototype only components whose trust assumptions and interfaces are specified. Measure real browser TTFB, FCP, LCP and full-load in addition to RTT/goodput, using matched direct and AEGIS conditions.

EDGE-03 must test traffic analysis and correlation with appropriate datasets, group-disjoint splits, multiple seeds, open-world/adaptive attackers, single-side and multi-point observers, and low/normal/high concurrency. Report attacker performance and uncertainty alongside cover-traffic bandwidth, latency, CPU and energy costs.

EDGE-04 compares AEGIS-native candidates (Oblivious Edge, multi-stage/multi-hop variants and hybrids) under the AEGIS threat model. External systems are optional context, not design targets.

## 12. Required deliverables

- docs/research/oblivious-edge/EDGE-01-THREAT-MODEL.md
- docs/research/oblivious-edge/EDGE-01-DATA-FLOW.md
- docs/research/oblivious-edge/EDGE-01-DECISION.md
- architecture and sequence diagrams with editable source;
- dated evidence/reference register;
- explicit open-questions list;
- risk register with severity, likelihood, evidence and next action;
- decision matrix for continue, modify, reject or inconclusive.

No source-code prototype is part of EDGE-01.

## 13. Decision gate

Possible outcomes:
- approved_for_prototyping: coherent threat model and interfaces justify a bounded EDGE-02 prototype; this is not production approval or an anonymity claim;
- inconclusive: material assumptions/evidence remain unresolved; list exact missing evidence;
- rejected: structural flaw or unacceptable unmitigated risk invalidates this proposal; preserve findings.

Approval requires explicit AEGIS-native threat model, complete data-flow and knowledge matrix, single-node compromise and multi-point correlation analysis, TEE/attestation limits and key-binding design, PIR/token/DNS assumptions, realistic network measurement method, falsifiable EDGE-02/03 hypotheses, and independent review of critical claims.

## 14. Final report

Report baseline branch and full SHA; working-tree status and files; dated sources; architecture and threat model; assumptions versus verified facts; findings by adversary; quantitative estimates with derivations and uncertainty; unresolved risks; decision with criterion-by-criterion rationale; and explicit confirmation that no production code, PR #34, P4c/P4d artifacts, deployment or default branch were changed.

Do not invent measurements, test results, citations, SHAs or approvals. Preserve contradictory evidence and explain it.

## 15. Completion discipline

All ideas remain hypotheses until independently validated. The ≥90% Surface performance objective and AEGIS-native anonymity/privacy objectives remain unchanged. No idea is implemented, accepted or deployed by this document.
