# MALEBOLGE directory state and verified route boundary — v0.9.0

## Scope

This is a local implementation for IPv4 loopback endpoints. It is not a public directory, production trust store, or a guarantee of anonymity.

## Persistent trust state

Construct a verifier with a path on a local filesystem controlled by the current user:

```python
from anonlab.directory import DirectoryVerifier

verifier = DirectoryVerifier(
    pinned_authority_public_key,
    state_path="/path/to/private-state/directory-state.json",
    require_persistent_state=True,
)
```

The stored state is bound to the SHA-256 fingerprint of the pinned authority key. It includes the highest accepted descriptor sequence per relay, the complete most recent authority-signed revocation snapshot, its epoch and expiration, and the revoked identity set. On restart, the verifier checks the state schema, exact fields, data bounds, authority fingerprint, signed snapshot signature and consistency between the snapshot, digest, epoch, expiry and revoked IDs.

Writes use a temporary file in the same directory, private mode `0600` on POSIX, file `fsync`, atomic replacement and parent-directory `fsync`. A failed write does not advance in-memory revocation state. Symbolic-link state paths and overly permissive POSIX state files are rejected. The state file is intended for a directory private to the application user.

The persistent state does **not** provide hardware-backed monotonicity. An attacker who can restore an older, previously valid state file can roll back observed descriptor/revocation knowledge. Preventing that requires a stronger anchor such as platform-provided monotonic storage, independent witnesses, a transparency log, or gossip/consensus. The file also cannot protect against an attacker who controls the running process or the user's account.

## Freshness and route lifecycle

A signed revocation snapshot must be applied before route materialization, and the snapshot must not have expired. Descriptor sequence high-water marks are persisted before a newly observed sequence is accepted. A new revocation epoch, any relay revocation, a newer descriptor sequence, or expiration invalidates an already-issued route object.

Preferred high-level flow:

```python
route = verifier.verify_circuit_route(signed_descriptors)
await client.connect_verified_route(route)
```

The high-level client re-checks route usability before connecting and before each extension. If a check fails partway through, the client closes the circuit. The low-level `connect_guard` and `extend` APIs remain available for protocol-unit tests and explicit local experiments; they are not intended as a policy boundary for untrusted application code. Production application code should expose only the verified-route path.

## Limits and residual risks

- State must live in a protected, backed-up local directory. Restoring an older valid copy can roll back state.
- The directory authority remains centralized and its public key must be pinned out of band.
- Authority-key rotation and recovery, multiple authorities, transparency/gossip, and independent audits are not implemented.
- Relays accept only literal IPv4 loopback endpoints in this lab.
- Relay-to-relay transport authentication is not yet integrated as a separate layer.
- Low-level test APIs can bypass route verification, and the cryptographic adaptation is custom and unaudited.
- None of this proves resistance to timing correlation or makes the prototype safe for sensitive traffic.
