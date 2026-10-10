# AEGIS PIR research: signed manifests and persistent rollback checkpoints

## Increment added

- Ed25519-signed, domain-separated snapshot metadata with a fixed schema.
- Strict field validation and signature verification.
- Optional manifest freshness and future-timestamp checks.
- An in-memory sequence checkpoint that rejects rollback and same-sequence equivocation.
- `save_checkpoint` writes checkpoint JSON to a same-directory temporary file, flushes and fsyncs it, atomically replaces the target, and fsyncs the parent directory on POSIX.
- `load_checkpoint` validates exact fields, schema, sequence and digest encoding and rejects malformed/oversized state.
- Persistence tests cover round trip, invalid schemas, malformed JSON and inconsistent state.

## Security boundaries

This authenticates snapshot metadata and a Merkle root, not the correctness of a PIR response. Merkle inclusion proofs reveal a record index and must not be attached to a private query. The signer public key must be pinned through trusted provisioning. Freshness depends on a trustworthy clock or a separately defined epoch policy.

Persistent checkpoint storage is an improvement over process-only state, but is not a complete production anti-rollback system. The directory must be trusted and writable only by the service identity. The current implementation assumes a single writer: it does not implement cross-process locking, compare-and-swap, replicated consensus, or protection from an attacker who can rewrite the checkpoint and its parent directory. Backups and recovery procedures must not silently restore an older checkpoint. For stronger local attacker resistance, anchor the monotonic sequence in a separate trust domain (for example, hardware-backed monotonic state or a quorum-backed transparency log).

The module is experimental and is not wired into the PIR RPC path. No claim is made that malicious replicas are prevented from returning incorrect PIR answers. `pyproject.toml` remains at 0.26.0; this artifact is a research package, not an official release.
