# AEGIS v0.23.0 — latency-aware route selection prototype

## Status

Implemented as a **local/offline planner** in `src/anonlab/route_selection.py`, exposed as `aegis-route-select`. It chooses a guard/middle/exit sequence from a caller-supplied topology. It does not connect to relays, verify signed descriptors itself, or prove anonymity. The caller must obtain candidate data from a separate authenticated directory and validate measurements.

## Selection model

1. Preserve a caller-specified **pinned confirmed guard**. If that guard is absent/unusable, fail closed instead of quietly selecting a new guard. This reduces guard churn and avoids treating each circuit as a fresh entry choice.
2. Filter out offline relays and relays below the minimum bandwidth.
3. Enumerate three-hop combinations and enforce hard limits on repeated relay family, ASN, and subnet; country is limited by policy but is not the main diversity primitive.
4. Prefer measured per-link RTT. For missing link measurements, compute a Haversine great-circle lower bound and add conservative unknown-link penalties. Geometry is a prior and lower bound only: terrestrial paths follow fiber routes, peering and congestion, not straight lines.
5. Score the end-to-end link estimates plus load, failure-rate, and bottleneck-bandwidth penalties. The weights are explicit policy parameters and need tuning with multi-host data.
6. Return only selected relay IDs and aggregate timing/capacity estimates. Do not export client/destination coordinates or raw link measurements in the plan report.

## Why ZK does not calculate the fastest route

A zero-knowledge proof can establish a statement about a witness without revealing that witness; it does not itself measure latency, establish topology truth, or optimize a graph. This prototype has **no ZK proof**. An eventual anonymous access credential could prove eligibility to a directory or gateway without linking a credential to a session, but that requires a separately specified credential system, anti-replay rules, and independent review.

## Threats and limitations

- Relay latency, bandwidth, country and ASN fields can be stale, inaccurate, or adversarially manipulated.
- Geography is not a ping oracle. The geometric RTT is an optimistic propagation floor, not an achievable target.
- A fastest-path policy can concentrate users on a small set of relays, reduce anonymity sets, and increase exposure to a malicious/compromised fast relay. Diversity/guard pinning are hard constraints for that reason.
- Selecting a geographically close exit may disclose target-region intent if target location or traffic class is sent to a directory. The selector is designed to run client-side and omit endpoint coordinates from its output; no remote interface should accept precise user coordinates.
- No traffic mixing, constant-rate cover traffic, dummy requests, path-observation defense or global-observer guarantee is implemented by this module.

## Run

```bash
PYTHONPATH=src python -m anonlab.route_selection
PYTHONPATH=src python -m anonlab.route_selection --input examples/route-topology-demo.json
```

The demo topology is synthetic. It is not a live route or a performance test.

## External design references

- Tor path selection uses bandwidth weighting and restrictions on relay reuse, family and subnet; entry-guard persistence helps limit profiling risk: https://spec.torproject.org/path-spec/path-selection-constraints.html and https://spec.torproject.org/guard-spec/.
- Nym's mixnet documents packet mixing, fixed-size Sphinx packets, cover traffic and deliberate delay as separate metadata-protection mechanisms; a fast geometric path alone does not supply these protections: https://nym.com/docs/network/mixnet-mode/traffic-flow.
