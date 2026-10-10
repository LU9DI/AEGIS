# Using REA for this research program

The `morluto/rea` repository is the **reverse-engineering agent** (CLI/MCP), not the anonymous network's protocol implementation. Keep the network prototype in a separate research repository so experiments, threat-model decisions, dependencies, and security claims do not get mixed into REA's provider-neutral tooling.

## Recommended analysis loop

1. Obtain the source or an authorized local build of a target (start with Arti/Tor, HORNET reference implementations, and relevant browser privacy components).
2. Use REA to inventory modules and boundaries, trace selected request paths, inspect crypto / relay state transitions, and capture the evidence for each finding.
3. Separate direct observations from hypotheses and unknowns. In particular, do not infer anonymity from the presence of encryption or from high forwarding throughput.
4. Implement a minimal version in the separate lab, behind loopback-only test fixtures.
5. Run deterministic unit tests and measured local tests. Compare against the same payloads, hop count, machine, and workload. Preserve raw JSON outputs.
6. Advance to a distributed testbed only after protocol framing, key lifecycle, replay behavior, timeouts, failure semantics, and resource limits have adversarial tests.

## Questions REA should help answer

- Which bytes and state does each relay learn on receiving and forwarding a request?
- Where is the destination revealed, and to which component?
- How are keys generated, bound to a circuit, rotated, and destroyed?
- Can an old packet be replayed? Can a relay redirect an envelope to an unintended destination?
- What metadata remains observable (addresses, packet lengths, direction, timing, connection lifetime, errors, and congestion)?
- Which measurements are code-derived facts, which are empirical observations, and which are only assumptions?

## Non-goals

Do not patch REA's MCP domain or provider interfaces to embed the network protocol. Do not describe a local single-machine relay chain as an anonymity network. Do not claim resistance to a global observer until the threat model and correlation evaluation support that claim.
