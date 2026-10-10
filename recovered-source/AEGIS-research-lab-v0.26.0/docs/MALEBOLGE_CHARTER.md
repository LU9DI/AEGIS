# MALEBOLGE — project charter

## Identity

**MALEBOLGE** is the working name of the open-source research effort to investigate a high-performance anonymous communication network. **REA (Reverse Engineer Anything)** is a separate reverse-engineering agent that can help inspect existing implementations; it is not the network protocol.

## North-star objective

Investigate whether an architecture can deliver strong, explicitly scoped anonymity with user-perceived performance closer to conventional Internet access than current practical anonymous-routing systems. This is a research goal, not a claim that the anonymity trilemma has been solved.

## Engineering principles

1. **Measure before claiming.** Report latency distributions, goodput, bytes of cover traffic, CPU/memory use, reliability, and adversary success together.
2. **Define the adversary.** Distinguish browser trackers, access-network observers, malicious relays, multi-point observers, and global passive observers.
3. **Separate layers.** Keep browser privacy, transport, relay routing, key management, cover traffic, and optional mesh links as independently testable components.
4. **No bespoke cryptography without review.** Use established constructions and protocol designs where possible; experimental protocol changes require explicit threat analysis and independent review before real use.
5. **Do not overstate simulation.** Loopback benchmarks are local microbenchmarks, not WAN performance or anonymity evidence.
6. **Fail safely.** Experimental relays remain loopback-only until authentication, access control, abuse resistance, operational security, and deployment threat models have been reviewed.
7. **Open and reproducible.** Preserve test seeds, raw results, environment details, versioned protocol notes, and documented limitations.

## Current status

MALEBOLGE v0.7.0 includes a flow-level simulator, loopback TCP and AEAD benchmarks, an isolated ntor-derived key-agreement experiment, and a telescoping three-relay proof of concept. The telescope test opens one client connection to the guard, adds later relays through the circuit, and carries loopback-only echo payloads through the exit. Forty-three tests pass on the research host. These results validate local control flow and data integrity, not anonymity or public-network security.

The telescoping harness's MALEBOLGE-specific KDF is custom and unaudited; relay-to-relay channels are not mutually authenticated; descriptors are pinned in process memory rather than a signed, revocable directory; and traffic-correlation resistance has not been measured. The earlier protocol-v2 circuit still uses pre-shared per-run keys. No component should be used for sensitive traffic or exposed to public interfaces.

## Next gate

Before any distributed/WAN test, specify and independently review key derivation and relay link authentication, add signed relay descriptors with expiry/revocation, harden partial-extension and resource-exhaustion behavior, and replace the one-shot loopback echo operation with bounded bidirectional streams and flow control. Then run adversarial traffic-analysis experiments with an explicit attacker model. Before any public alpha, require independent security review and a written deployment/abuse-resistance plan.


## v0.7.0 resource and concurrency milestone

The testbed enforces a bounded active-connection count per relay and a per-hop command budget, and it now includes two-client concurrency tests plus an 8-/32-/64-client loopback benchmark. These checks establish local resource limits and concurrency behavior only. They do not establish anonymity, relay trust in a distributed network, or resistance to global traffic correlation.
