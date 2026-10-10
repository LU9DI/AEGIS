# AEGIS v0.23.0 — architecture decisions and staged roadmap

## What is implemented now

| Idea | v0.23.0 status | Boundary |
|---|---|---|
| Geometry/latency-aware path choice | Offline route-scoring prototype | Measured RTT wins over geometry estimates; pinned guard and ASN/family/subnet diversity are mandatory constraints. No ZK proofs, directory integration, or live route change. |
| PIR | Two-server XOR PIR reference protocol | Fixed-width replicated rows; O(N) query and server work; depends on non-collusion. In-process demo only. |
| Bit splitting | Chunk-level 2-of-2 XOR sharing primitive | Correctness and integrity-check prototype; no networked multipath, per-path AEAD, or metadata defence. |
| FHE | Not implemented | Too broad to add without selecting supported query circuits, parameter sets, key-management, side-channel model, and benchmarking target. PIR is the appropriate first data-retrieval experiment. |
| ZK credentials | Not implemented | Need an explicit statement/credential format, issuance, unlinkability, replay resistance, revocation, and verification threat model. Route scoring itself is not a ZK computation. |
| Rust + QUIC | Not implemented in this environment | `rustc`, `cargo`, and `aioquic` are unavailable in the current build environment. Existing Python/TCP path is retained as control until a separate implementation can build and pass cross-host tests. |
| WebAssembly/browser | Architecture plan only | Wasm runs computation but does not by itself expose raw UDP sockets. Browser connectivity requires supported browser APIs and a compatible endpoint (for example, HTTPS WebTransport over HTTP/3). |

## Why latency and privacy must be co-optimized

Geographic distance only supplies an optimistic propagation lower bound. Real paths depend on fiber topology, interconnect/peering, congestion, relay capacity, queueing and failure. A route selected only for the lowest measured RTT can repeatedly concentrate clients on the same fast relays and reduce anonymity sets. AEGIS therefore keeps a pinned confirmed guard, imposes network-family diversity, and prefers measured link RTT over geolocation guesses. No remote service should receive precise client coordinates merely to produce a route score.

A ZK proof can prove a narrowly defined claim (such as possession of an eligible credential) without revealing a witness. It cannot on its own tell the client the true RTT or prove advertised relay metrics are honest. Future ZK access credentials should be separate from route optimisation and must include anti-replay and unlinkability tests.

PIR hides a record index from each individual server under its protocol assumptions, not the client's IP or request timing. In the XOR prototype the two servers must not collude. The same property does not translate into “the whole web delivered at full speed”: the index must correspond to a fixed and replicated dataset, and costs scale with its number of records.

XOR sharing makes each individual share look random, but the two shares together reveal the data. Multipath diversity helps only if paths are meaningfully independent; shared ASNs, shared relays, traffic correlation, or a global observer can defeat the assumption. The current code tests the primitive locally and does not claim live multipath protection.

## Staged transport plan

1. Keep the current Python/TCP transport as an unchanged control.
2. In an environment with Rust toolchain access, create a separate transport crate using a maintained QUIC implementation such as `quinn`; keep circuit framing and cryptographic transcript versioned independently from QUIC/TLS. Do not claim that QUIC eliminates all head-of-line effects: stream-level isolation helps, but congestion control, retransmission and endpoint/relay processing delays remain.
3. Build relay-to-relay and client-to-relay QUIC test pairs on loopback, then separate-host LAN and controlled WAN links. Test packet loss, MTU/path migration, anti-amplification, congestion, flow-control limits, cancellation, key rotation, and malformed inputs before comparing against TCP.
4. Only after the native transport works, expose a browser-compatible edge. Wasm can run a crypto/state-machine core, while WebTransport provides a browser HTTP/3 transport where supported in a secure context. This is not raw QUIC access from arbitrary Wasm, and browser compatibility and deployment headers must be tested.
5. Keep a separate browser threat model: extension access, XSS, service-worker compromise, fingerprinting, WebRTC/IP leaks, local-storage secrets, timing, and browser update trust. “Runs in the browser” does not itself make a client anonymous.
6. Only consider FHE after selecting an application-specific operation. It is not an appropriate default for arbitrary page rendering, scripts and general-purpose browsing. Benchmark query construction, server compute, result size and client decryption against PIR and ordinary encrypted fetch.

## Acceptance gates before any live network claim

- Independent review of protocol transcript/key derivation, directory trust, route selection, credential/ZK proofs, and share framing.
- Cross-host tests with independently controlled paths; reproducible WAN latency/loss/congestion results.
- Threat-driven tests for one malicious relay, colluding relays, one PIR server colluding, global timing observer, route manipulation, guard failure and retry behavior.
- Anonymity-set/traffic-analysis evaluations, not just throughput charts.
- No user coordinate or destination-interest fields in relay telemetry; data minimization and audit of logs.

## References

- Tor path-selection constraints and guard persistence: https://spec.torproject.org/path-spec/path-selection-constraints.html and https://spec.torproject.org/guard-spec/
- QUIC core and loss recovery/congestion control: https://www.rfc-editor.org/rfc/rfc9000.html and https://www.rfc-editor.org/rfc/rfc9002.html
- Rust Quinn QUIC implementation: https://github.com/quinn-rs/quinn
- Browser WebTransport API (HTTP/3; secure context and browser support): https://developer.mozilla.org/en-US/docs/Web/API/WebTransport_API
- Two-server PIR foundations: https://doi.org/10.1145/293347.293350
- Nym mixnet traffic flow: https://nym.com/docs/network/mixnet-mode/traffic-flow
