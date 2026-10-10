# AEGIS v0.27.2 — Caller-pinned RPC snapshot fingerprint (research)

## Change

`retrieve_two_server_pir_rpc()` now accepts the optional `expected_snapshot_sha256` argument. When supplied, it validates the argument as a lowercase SHA-256 hex digest and rejects the transfer unless the fingerprint returned by both endpoints matches the caller's pinned value. The default remains `None` for backward compatibility.

## What this protects

- Detects accidental use of a different database snapshot when the expected fingerprint was obtained through an independent trusted channel.
- Makes snapshot pinning explicit at the API boundary rather than relying only on agreement between two endpoints.
- Does not alter the request wire format and does not disclose the target index.

## Critical limitation

This is **not** verifiable PIR and is not proof of correct evaluation. The existing RPC response fingerprint is self-reported by each endpoint. A malicious endpoint can return a wrong answer while claiming the expected fingerprint and producing a valid transport MAC/TLS response. Even two matching fingerprints do not prove either response is correct. A signed manifest can authenticate a snapshot root but does not by itself prove a query answer was computed from that snapshot.

The API argument is useful only when the expected fingerprint is independently trusted and the threat model includes stale/mismatched replicas. It must not be described as protection against an actively malicious replica.

## Next research gate

Before claiming malicious-replica verifiability, select a concrete protocol with a formal security model (e.g. a verifiable computation proof over the server's linear/XOR query, or a suitable verifiable-PIR construction), specify exactly what the proof reveals, bind it to a signed snapshot, and benchmark proof generation/verification. A Merkle inclusion proof cannot simply be added to this query because its index reveals the target.

## Validation

See the test suite for regression coverage of valid pinning, mismatches, and malformed pins. The complete suite should be run before packaging; passing tests here do not establish a zero-knowledge or malicious-server correctness guarantee.
