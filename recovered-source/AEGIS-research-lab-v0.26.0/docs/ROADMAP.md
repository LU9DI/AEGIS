# AEGIS Research Roadmap

**Current experimental release: v0.24.0.** The previous v0.22.0 line remains the transport-performance baseline.

## v0.24.0 additions

- Added loopback-only two-endpoint PIR RPC with per-replica HMAC-SHA256 authentication, request/response domain separation, timestamp and bounded-nonce replay checks, and replica snapshot comparison. The demo binds only to loopback and is not encrypted or production-deployable.

## v0.23.0 additions

- Offline route scoring uses observed link RTT, a geometry-only lower bound for missing data, load/bandwidth/failure penalties, and hard relay family/ASN/subnet diversity. A pinned confirmed guard is required.
- Two-server XOR PIR reference implementation for fixed-width replicated records, with an exhaustive small-domain test showing each server's query distribution is independent of selected index.
- Chunk-level 2-of-2 XOR secret-sharing primitive with client-local manifest and SHA-256 reconstruction integrity check.
- CLI demos and threat/limits documentation. None of these components has been wired into live circuit forwarding.

## Existing transport baseline

- Experimental, local loopback three-relay TCP circuit with layered per-hop encryption, authenticated framing, bounded full-duplex streams, flow control, write batching/pipelining, signed relay descriptors and optional fairness scheduling.
- Previous network-shaper tests shape TCP byte streams and are not real IP packet loss or a WAN model.
- 64 KiB receive-credit threshold and 2 ms sparse-write flush timer remain the current defaults; experiments found no consistent reason to change these settings.

## Next work, in order

1. Stress/benchmark route scoring over generated topologies: stale or falsified relay metrics, guard loss, topology churn, speed/privacy trade-offs, and concentration of selected relays.
2. Replace the loopback PIR RPC harness with a reviewed authenticated-confidential transport for independently hosted replicas; establish opaque/signed database-version commitments, quotas, privacy-preserving logs, and malicious/colluding-replica tests. The current HMAC demo is not suitable for public clients and does not encrypt traffic. Do not send actual web requests through the same identity-visible transport and then claim IP anonymity.
3. Test 2-of-2 shares under simulated reordered/lost/corrupted chunks and disjoint-path failure. Add authenticated share framing only after protocol review.
4. Build a Rust QUIC transport as a separate crate once toolchain/package access is available. Retain current TCP as the A/B control until cross-host protocol tests pass.
5. Design anonymous access credentials and ZK proof goals explicitly; no ZK cryptography is added until proof statements, issuers, revocation, replay prevention and unlinkability are defined.
6. Benchmark any application-specific FHE use against PIR/plain encrypted fetch; no generic FHE claim for full-page browsing.
7. Research WebAssembly/WebTransport as a browser frontend only after transport, browser threat model, and deployment compatibility are specified.
8. Conduct independent cryptographic and traffic-analysis review before public network access.

## Non-goals and claims

AEGIS does not currently implement full garlic routing, FHE, ZK credentials, native QUIC, a WebAssembly browser client or live multipath transfer. No proof of absolute anonymity, clearnet-equivalent latency, or resistance to a global passive observer is claimed. The v0.24.0 PIR RPC is loopback-only and must not be interpreted as a remotely deployable authenticated service.
