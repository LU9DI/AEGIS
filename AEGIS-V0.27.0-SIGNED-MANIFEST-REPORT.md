# AEGIS PIR research increment — signed snapshot manifests

## Delivered

- Added `anonlab.pir_manifest`: Ed25519-signed snapshot metadata binding schema version, snapshot ID, monotonically increasing sequence, creation time, record count, and the SHA-256 Merkle root.
- Applied domain separation and deterministic canonical JSON encoding before signing/verifying.
- Added strict validation, optional freshness enforcement, future timestamp tolerance, and `SnapshotCheckpoint` logic to reject sequence rollback or a different manifest at an already accepted sequence.
- Added tests for signature success/failure, payload tampering, invalid sequence, stale/future manifests, rollback, equivocation, and checkpoint state not advancing after failed verification.
- Documented deployment assumptions and explicit security boundaries in `docs/AEGIS_V0.27_SIGNED_SNAPSHOT_MANIFESTS.md`.

## Validation

- `PYTHONPATH=src python -m pytest -q`: **219 passed, 76 subtests passed**.
- `PYTHONPATH=src python -m unittest discover -s tests -q`: **207 tests passed**.
- The pytest suite includes the new pytest-style manifest tests; the unittest count reflects unittest-discoverable test cases only.

## Security boundaries / not yet solved

This increment authenticates snapshot metadata and gives a client an in-memory primitive for detecting stale sequence numbers. It does **not** prove that a PIR server computed a response correctly. Merkle inclusion proofs disclose an index and must not be attached to the private query path. The signer public key must be pinned via trusted provisioning. `SnapshotCheckpoint` is in-memory only: production anti-rollback requires durable, atomic storage and an explicit backup/recovery policy. Time-based freshness also assumes a trustworthy clock. The manifest code is not integrated into the RPC protocol, and the package version in `pyproject.toml` remains 0.26.0; this ZIP is a research artifact, not an official release.
