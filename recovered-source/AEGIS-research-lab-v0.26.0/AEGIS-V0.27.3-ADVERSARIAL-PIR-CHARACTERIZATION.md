# AEGIS v0.27.3 — Adversarial PIR characterization

## Scope

This research increment adds a deterministic end-to-end test for a critical threat:
a replica that has a valid transport credential, reports the expected snapshot
fingerprint, but returns an incorrect PIR answer.

## Finding

The test modifies one replica's query-answer function to flip a bit while leaving
its genuine snapshot fingerprint unchanged. The client accepts the transfer, and
the reconstructed record differs from the expected record. This is expected with
the current protocol: HMAC authenticates the message origin/integrity in transit,
and fingerprint pinning checks the claimed snapshot identity, but neither proves
that the server correctly evaluated the query. A compromised server can create a
valid HMAC over a false answer because it holds the shared key.

## Security consequence

The current two-server XOR protocol protects the query only under its non-collusion
assumption. It does not provide malicious-server correctness. A single malicious
replica can corrupt the reconstructed record. A trusted snapshot hash does not fix
this because the protocol currently has no cryptographic binding between each
answer and a verifiable computation over that snapshot.

## Requirements before claiming verifiable PIR

1. Specify the database representation and the exact query/answer relation.
2. Select a verifiable-PIR protocol whose proof is independent of the secret index
   (or demonstrate formally that its transcript does not leak the index).
3. Bind the authenticated snapshot commitment, protocol version, dimensions, and
   query transcript into the proof's statement.
4. Define who generates and validates the commitment and how key rotation,
   freshness, rollback, and equivocation are handled.
5. Add adversarial tests for invalid proof, wrong answer, stale root, malformed proof,
   replay, and cross-snapshot substitution.
6. Benchmark proof generation, verification, bytes transferred, and end-to-end latency.

## Status

This increment is a characterization test and threat-model document, not a fix for
malicious-server correctness. It intentionally does not bolt on a Merkle inclusion
proof: such a proof reveals a record index and does not prove the XOR/PIR answer was
computed correctly. The RPC protocol and declared project version are unchanged.
