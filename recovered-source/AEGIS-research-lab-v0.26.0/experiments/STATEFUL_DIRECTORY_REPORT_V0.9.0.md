# Stateful directory experiment report — v0.9.0

## What this experiment validates

The v0.9.0 tests exercise a persistent local state file for the signed relay directory. It persists descriptor sequence high-water marks and the full authority-signed revocation snapshot. State is keyed to the fingerprint of the pinned directory authority, written with a temporary file plus `fsync` and atomic replacement, and revalidated on restart.

The high-level route API requires persistent state and an unexpired revocation snapshot. It returns a short-lived `VerifiedCircuitRoute`, and `TelescopingClient.connect_verified_route()` validates that route before opening a socket and again before every hop extension. A route is invalidated after a new revocation epoch or a newer descriptor sequence is accepted.

## Verification results

- 82 unit and integration tests passed using `PYTHONPATH=src python -m unittest discover -s tests -v`.
- Persistent sequence high-water marks survived verifier restart and rejected an older descriptor.
- A revoked identity remained revoked after restart.
- Editing the persisted revocation list without the authority's signature was rejected.
- State files with malformed JSON, incorrect authority trust anchor, or overly broad POSIX permissions were rejected.
- Expired persisted revocation snapshots failed closed for route construction.
- A failed state write left revocation epoch and revoked-ID state unchanged.
- A route became unusable when a newer revocation epoch or descriptor sequence was applied.
- A manually fabricated route object and an expired route were rejected before opening a client socket.
- Existing three-hop loopback integration from signed descriptors still succeeded.

## What this does not prove

The JSON file is local application state, not a hardware-backed monotonic counter. A party who can restore a previously valid state file can restore earlier knowledge; preventing this requires an independent freshness anchor. The authority remains a single trust root, and the low-level test APIs intentionally remain callable. The testbed accepts only loopback endpoints, does not authenticate live relay links independently, and does not establish resistance to global traffic correlation. This work is not a security audit or a production-readiness claim.
