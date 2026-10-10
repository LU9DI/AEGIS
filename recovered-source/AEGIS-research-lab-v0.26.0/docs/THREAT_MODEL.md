# AEGIS threat model — historical research baseline v0.17.0

## Purpose

This document sets the initial research target. It is not a claim that the
simulator or a future implementation provides anonymity.

## Adversaries to distinguish

1. **Commercial trackers:** observe browser identifiers, cookies, storage,
   request behavior, and fingerprinting signals.
2. **Local network / ISP observer:** can observe subscriber identity, timing,
   volumes, and destination metadata available at that network point.
3. **Malicious relay:** controls one relay and tries to associate incoming and
   outgoing flows.
4. **Multi-point observer:** can observe both a user's access link and traffic
   near a destination or exit, and can correlate timing and volumes.
5. **Global passive observer:** has broad visibility across network links and
   attempts traffic correlation over long observation windows.

These adversaries are not interchangeable. A defense against browser
fingerprinting does not by itself defend against traffic analysis; encryption
of payloads does not hide all timing or volume metadata.

## Initial measurable claims

The simulator may explore whether specific parameters can reduce a simple
maximum-lag Pearson correlation score, how latency changes under different
hop assumptions, and how much synthetic traffic is added. It cannot establish
formal anonymity, resistance to a global observer, or security of a cryptographic
protocol.

## Explicit exclusions in v0.6.0

- The earlier protocol-v2 onion prototype uses ChaCha20-Poly1305 with pre-shared per-run keys. The separate telescoping harness does derive independent per-hop keys through the ntor-derived experiment, but its MALEBOLGE-specific KDF has no independent cryptographic review.
- Relay-to-relay transport is not mutually authenticated, descriptors are in-memory inputs rather than signed/expiring/revocable directory records, and replay protection is local to each live connection/process.
- TCP packets are transmitted only between IPv4 loopback listeners in one Python process; no public Internet, independent-host, or WAN route is tested.
- The telescoping harness now supports bidirectional loopback TCP streams and a bounded WRITE pipeline (depth ≤4), but remains a custom, unaudited transport—not a general-purpose browser proxy. Pending-write accounting is an admission bound, not an exact bound on Python/asyncio/kernel memory.
- No packet-size/direction sequence classifier, website fingerprinting,
  active probing, relay compromise, Sybil attack, or intersection attack is modeled.
- Independent cover noise is an optimistic abstraction; one circuit's own dummy
  packets can remain correlatable at both ends.
- The fixed-rate model assumes the visible rate is constant and omits packet
  direction, connection lifecycle, congestion events, failures, and side channels.

## Additional observations from the current telescope prototype

- In the tested path, the guard parses `EXTEND(middle)`, then `FORWARD(opaque)` for exit creation and application requests. The middle parses `EXTEND(exit)`, then `FORWARD(opaque)`. Only the exit parses the loopback echo destination. This is a parsed-command knowledge-boundary check, not a proof against packet capture or a colluding/global observer.
- Each relay authenticates its own envelope and enforces a per-connection sequence; replies are bound to the command sequence at each hop. The control protocol is custom, local to this lab, and not Tor-wire-compatible.
- The exit relay learns the selected destination and application payload. End-to-end HTTPS and browser-origin security are not implemented by this transport prototype.
- There is no general bidirectional stream lifecycle, multiplexing, congestion control, cover schedule, mixing, or demonstrated correlation defense.

## Security gates before any production use

1. Write a formal protocol specification and explicit security goals.
2. Define attacker capabilities and prove or justify each claim.
3. Have independent reviewers audit protocol and implementation.
4. Run adversarial tests in addition to performance benchmarks.
5. Never label a mode “anonymous” solely because payloads are encrypted or a
   simple correlation score is low.

## v0.17.0 pipeline-specific observations

- WRITE commands are queued in ascending sequence order. Each command receives its own authenticated ACK and response correlation key; ACKs may finish out of order. The current loopback benchmark did not establish a stable performance improvement from increasing the pipeline depth.
- The client bounds one pipeline batch to four commands. Each relay bounds pending writes by four commands and 2 MiB per stream, with a 16 MiB aggregate pending-byte limit per circuit connection. These are implementation safeguards, not a formal resource or fairness proof.
- HALF_CLOSE and CLOSE are serialized against client pipeline operations and relays reject them while writes are pending. Protocol fuzzing, forced TCP loss, WAN congestion tests and independent audit remain outstanding.


## v0.23.0 prototype additions — explicit threat boundaries

- **Route scoring:** measurements and coordinates can be stale or manipulated. A low-latency route can concentrate clients on a few relays. The selector pins a confirmed guard and applies ASN/family/subnet constraints, but it is a local heuristic, not a ZK proof or a traffic-analysis defense.
- **Two-server XOR PIR:** each server's query alone is uniform in the reference construction; two colluding replicas recover the requested index by XORing their query vectors. PIR does not hide source IP, request timing, or payload metadata from the transport.
- **XOR shares:** a relay that sees both shares—including a relay shared by both paths, or a common guard before paths diverge—can reconstruct the payload. A global observer can also reconstruct it. Share size/count, timing, and the client's access-link identity remain observable; current code does not send shares over the network.
- **FHE/ZK/QUIC/Wasm:** no full homomorphic-encryption engine, zero-knowledge credential system, Rust/QUIC transport, browser WebAssembly client, or WebTransport integration is implemented in v0.23.0. These are planned research branches, not current threat mitigations.


## v0.24.0 authenticated PIR RPC additions — explicit threat boundaries

- **PIR RPC:** message integrity is HMAC-SHA256 authenticated under endpoint-specific pre-shared keys with request/response domain separation, timestamps and a bounded nonce cache. The transport is loopback-only and is not encrypted. Sharing its HMAC key with arbitrary public clients would permit those clients to forge messages; it is not a server identity mechanism for a public service.
- **Replay protection:** the nonce cache is in-memory and bounded. It is a prototype guard, not a persistent/distributed anti-replay ledger under arbitrary request volume or process restarts.
- **Replica agreement:** responses include a content snapshot fingerprint and dimensions so the client can detect mismatched data. A digest can fingerprint low-entropy datasets; production should analyze an opaque signed database-version commitment instead.
- **Deployment:** the two listener sockets run on loopback in one process. No TLS, remote deployment, independent operator/host validation, rate limit, privacy-preserving logging, or integration through AEGIS anonymity circuits is implemented. A network observer that sees both PIR queries can XOR them and reveal the requested index.
