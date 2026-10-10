# AEGIS v0.27 — verifiable PIR implementation status

## Implemented in this research increment

`anonlab.pir_commitment` adds a domain-separated SHA-256 Merkle commitment for an ordered, immutable record snapshot, inclusion proof generation, and a verifier. The tests cover varying tree sizes, altered records and roots, malformed paths, empty snapshots, and order/position binding.

## Security boundary — important

This is **not** a verifiable-PIR protocol and is **not wired into the PIR RPC client**. A Merkle inclusion proof reveals the record index. Sending it with a private PIR request would defeat query privacy. The module only authenticates individual records against a trusted root; it does not prove that a server computed the PIR response correctly, nor that a claimed root is authoritative or fresh.

The original v0.26.0 behavior and package version remain unchanged. Do not advertise the project as having solved malicious-replica correctness.

## Required next research step

Evaluate a zero-knowledge proof system or a suitable verifiable linear-query protocol that proves the PIR response is consistent with a committed snapshot and the hidden query, without revealing the query index. Specify trusted root distribution, snapshot freshness/rollback resistance, setup assumptions, soundness, privacy leakage, proof sizes, and prover/verifier cost before integrating it into RPC.
