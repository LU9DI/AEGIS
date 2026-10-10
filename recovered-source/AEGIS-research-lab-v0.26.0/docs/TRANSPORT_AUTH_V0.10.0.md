# MALEBOLGE transport identity authentication — v0.10.0

## Scope

This milestone adds a loopback-only, nonce-bound Ed25519 identity-authentication exchange before the experimental `CREATE` handshake. It is a transport-authentication experiment, not TLS, not a standardized protocol, and not production-ready.

The expected identity public key is carried by the verified directory descriptor. `RelayDescriptor` checks that the public key hashes to the declared 20-byte relay identity. `DirectoryVerifier` creates descriptors only after relay and authority signatures, validity windows, sequence state, and revocation checks have succeeded.

## Handshake

The framed `LINK_HELLO` contains a mode, target relay identity digest, initiator identity digest/public key (zero-filled for anonymous client mode), a fresh 32-byte nonce, and a 64-byte initiator signature (zero-filled for client mode).

- **Mode 0 — client to guard:** the client sends no client identity. The relay checks that the hello names its own identity, claims the nonce in a bounded local replay guard, and signs the hello transcript. The client verifies the signature using the relay identity public key pinned in the verified descriptor.
- **Mode 1 — relay to relay:** the initiating relay includes its identity public key and signs the hello transcript. The receiving relay verifies the signature and checks that the 20-byte identity digest is derived from the supplied public key. The receiving relay signs the complete hello transcript and its own identity digest; the initiator verifies this response against the target's descriptor key.

The challenge nonce binds each authentication exchange to that connection attempt. Reuse of a nonce in the receiving process is rejected. The receiver's signature covers the exact hello, including the initiator signature, so modification or mode downgrade causes transcript verification to fail.

The relay-link flow does not make the client identify itself to the guard. That distinction is intentional: transport server authentication must not require the anonymous client to present a persistent identity.

## Route integration

`TelescopingClient.connect_verified_route()` now refuses verified-route objects whose descriptors lack identity public keys. The guard endpoint is authenticated before `CREATE` is sent. On each extension, the current relay authenticates the next hop against the target identity public key carried in the encrypted extension command; if using a verified route, the current relay must also possess its own Ed25519 identity private key to authenticate as the initiating relay.

Legacy low-level descriptor APIs remain usable by controlled tests. If a manually constructed descriptor has no identity public key, those legacy calls skip transport identity authentication. Do not expose these APIs as a public client interface.

## Important limits

- The lab is restricted to literal IPv4 loopback endpoints. This work did not enable WAN listeners.
- The link exchange authenticates key possession and target identity. It does **not** make the receiving relay verify the initiating relay's directory-authority certificate or revocation state. Relay admission/authorization needs a separate, explicit policy before distributed deployment.
- The replay guard is process-local, bounded, no-eviction, and resets on restart. An attacker can exhaust it; a public-network strategy needs rate limiting and durable or freshness-backed replay handling.
- Link authentication supplies no transport confidentiality. Application/circuit payload confidentiality still comes from the experimental per-hop AEAD framing, whose key schedule and protocol have not received independent review.
- Static Ed25519 signatures authenticate the descriptor identity; they do not hide which relay peers connect, when they connect, or how much traffic they exchange.
- A successful test does not prove resistance to global passive observers, colluding entry/exit relays, active disruption, traffic correlation, or website fingerprinting.
- The MALEBOLGE-specific key expansion remains unaudited and is not Tor-wire-compatible.

## Tests added

- The descriptor rejects an identity public key that does not hash to the declared relay ID.
- A guard refuses to send `CREATE` when a listener signs the response using the wrong identity key.
- A relay rejects an initiating relay hello with a tampered signature before claiming replay state.
- A previously accepted relay hello nonce is rejected if replayed on a new TCP connection.
- The signed-directory three-hop integration path confirms that the guard keeps client mode anonymous and that middle/exit hops receive relay-authenticated transport hellos.

## Gate to next milestone

Before a distributed testbed: add authority-certified peer-descriptor verification at relays, key/descriptor rotation and revocation propagation, anti-rollback/freshness witness integration, rate limits that account for replay-guard state, and independent protocol review. Only after those gates should the team test across separately administered hosts.
