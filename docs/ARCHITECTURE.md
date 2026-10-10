# AEGIS research architecture (historical notes through v0.22.0)

## Phase 0 — flow simulator (implemented)

- Deterministic workload generator.
- Transparent hop-latency, jitter, and bandwidth assumptions.
- Simplified per-hop FIFO / flow serialization model.
- Ingress/egress time-series observations.
- Maximum-lag Pearson correlation as a deliberately limited attacker.
- Two cover-traffic abstractions: independent edge noise and an ideal fixed-rate padded stream. Independent noise is not yet charged against hop congestion, so its latency output is not a performance forecast.
- JSON output so experiments can be repeated and compared.

## Phase 1 — local relay testbeds (partial implementation)

- Implemented: multi-process loopback TCP relay chain measuring persistent-connection small-message RTT and bulk echo goodput. The full-duplex path supports bounded WRITE pipelining at depths 1, 2, or 4, with ordered per-hop sequences and per-stream/aggregate pending-byte limits.
- Implemented: persistent experimental onion envelopes using ChaCha20-Poly1305, per-hop request-layer decryption, reverse-wrapped responses, configured next-hop allowlisting, and SHA-256 integrity checks. Protocol v2 also binds each message to a circuit ID and monotonic sequence, validates response sequence/circuit binding, and rejects duplicate circuit IDs within a relay process.
- v0.18.0: cached immutable relay descriptors on the hot path after cProfile showed repeated address/identity validation on every event. Same-host five-trial blocks showed a likely local implementation improvement, but they were not interleaved and are not a WAN forecast.
- v0.19.0: batch consumed-byte credit updates at 64 KiB with a 2 ms sparse-stream flush. Five randomized-order loopback trials reduced window-update commands from 104 to 32 and improved median goodput for 8 × 256 KiB, but an 8 × 64 KiB workload showed no reduction in update commands. Keep performance claims workload-scoped.
- Still needed: measure TCP/QUIC goodput, time to first byte, page-sized completion, CPU overhead, packet sizes, and queueing under controlled WAN delay/loss. Add packet traces and multiple independent hosts. Remaining profile hotspots include relay command handling, per-hop AEAD, read-credit updates and asyncio scheduling; do not raise the pipeline window without evidence.
- Add a multi-user relay pool before claiming cover traffic is independent.
- Capture experiment seeds, environment, commits, and raw traces.

## Phase 2 — protocol research (partially implemented)

- Added an isolated one-hop ntor-derived key-agreement experiment with a MALEBOLGE-specific directional AEAD key schedule and a local loopback benchmark. It is not integrated into the v2 onion relay circuit.
- Still needed: an independently reviewed telescoping extension protocol, forward-secret per-hop keys and directory authorization integrated into the live circuit, key rotation, production stream fairness/congestion control, exit isolation, distributed replay defense, and robust failure handling. Current protocol v2 still uses static-for-run pre-shared keys and a bounded process-local circuit-ID registry; it is not suitable for real traffic.
- Evaluate existing designs (including HORNET concepts) before proposing new primitives.
- Treat FHE as a targeted research branch for selected control-plane operations, not as a default per-packet data-plane operation.
- Evaluate mesh transport as an optional access/last-mile layer, not as a claim that local radios create a global Internet by themselves.

## Phase 3 — independent security review and limited alpha

Only after protocol review, key management, isolation, DNS handling, anti-leak checks, reproducible benchmarks, and threat-model review. The simulator is not a gate that can certify anonymity on its own.
