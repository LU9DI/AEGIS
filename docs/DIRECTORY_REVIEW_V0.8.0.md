# Signed directory review — v0.8.0

## Included checks

- Relay identity signature binds endpoint, relay identity, onion key, protocol, validity interval, sequence and serial.
- Authority signature certifies the complete relay-signed descriptor with domain separation.
- Verification rejects unknown/missing fields, non-canonical key IDs/hex fields, wrong trust anchors, tampered endpoints/keys, wrong identity digest, invalid port/host, expired/future descriptors and validity intervals over 24 hours.
- Revocation feed verification rejects tampering, malformed/unsorted IDs, expired snapshots, snapshot rollback, conflicting same-epoch content and removal of prior revocations.
- Client-side descriptor sequence state rejects lower-sequence rollback and different signed descriptor content using a previously seen sequence.
- JSON parser rejects duplicate keys and oversized descriptor input.
- Relay descriptors only allow literal IPv4 loopback endpoints in the laboratory.

## Non-goals / known gaps

- No trusted authority bootstrap or key-rotation bundle is shipped. Pin authority keys out-of-band.
- Anti-rollback state is not persisted; process restart resets descriptor sequence and revocation epoch state.
- The authority implementation is in-memory and does not maintain an authoritative issuance database to prevent the signer itself from certifying sequence conflicts. Verifiers reject conflicts after observing one.
- Revocation is cumulative and has no recovery path for mistaken revocation other than issuing a new relay identity. This avoids silent un-revocation but needs an operational policy before production.
- The descriptor has no transport address for public WAN use by design. Only loopback IPv4 is accepted.
- Live relay links are not authenticated by this module, and the descriptor directory has not been integrated as a mandatory gate for all existing circuit-construction paths. Callers must not bypass verification in any future public-network client.
- This has no independent cryptographic review, fuzzing campaign, multi-authority consensus, distribution mechanism, persistence, transparency log or end-to-end anonymity proof.
