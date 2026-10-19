# MALEBOLGE signed relay directory — v0.8.0

## Scope

This is a local primitive, not yet a production directory service. It intentionally rejects DNS names, IPv6, and any endpoint that is not a literal IPv4 loopback address. It uses the `cryptography` package from the optional `onion-lab` extra.

## Two signatures, two purposes

A relay descriptor contains a relay identity public key (Ed25519), an onion key (X25519), loopback endpoint, protocol identifier, validity interval, monotonic sequence, and random serial.

1. The relay identity key signs the canonical descriptor body under `MALEBOLGE/relay-descriptor/v1\0`. This binds the announced endpoint and onion key to the relay identity key.
2. The directory authority validates the relay signature and certifies the relay-signed descriptor under a separate `MALEBOLGE/authority-descriptor/v1\0` domain. A client verifies this signature against an authority public key pinned through a separate trusted channel.

The relay ID is the first 20 bytes of SHA-256 over a domain-separated 32-byte Ed25519 public key. It is an identifier, not a signature and not a replacement for checking the signatures.

## Validity and rotation

Descriptor lifetimes are capped at 24 hours. Every relay identity has a positive monotonic descriptor sequence. A client verifier remembers the highest observed sequence and the digest seen for that sequence; lower sequences and conflicting descriptors at the same sequence are rejected. Relay onion-key rotation should keep the identity key stable and increment the sequence. In this lab, that anti-rollback state is process-local, so it resets on restart. A production client would need durable, crash-safe state and an explicit recovery strategy.

## Revocation feed

A revocation snapshot is signed by the authority, expires within six hours, carries a monotonically increasing epoch, and includes a sorted set of revoked relay IDs. The verifier rejects expired or not-yet-valid snapshots, bad signatures, epoch rollback, conflicting snapshots with the same epoch and attempts to remove a previously revoked identity. This makes the lab's revocation policy cumulative: an identity cannot be un-revoked. A new identity would be required after a key compromise.

## Running the demo

```bash
python -m pip install -e '.[onion-lab]'
PYTHONPATH=src python -m anonlab.directory_demo
# If installed, the same demonstration is available as:
rea-anon-directory-demo
PYTHONPATH=src python -m unittest discover -s tests -p 'test_directory.py' -v
```

The demo generates a temporary directory authority and relay identity in-process, issues a descriptor, verifies it, rotates the onion key under a higher sequence, rejects rollback, and rejects the relay after revocation. It is intentionally not a service and writes no persistent trust material.

## Security limitations and gates

- The authority public key must be pinned out-of-band; the demo's generated key is not a deployed trust anchor.
- Directory and revocation rollback state is in-memory. Restart loses the client's freshness knowledge.
- A single authority is a central trust and availability dependency. No threshold signatures, consensus, transparency log, gossip, or cross-signing is implemented.
- The descriptor's self-signature proves possession of the relay identity key, while authority certification authorizes it. Neither by itself authenticates a live network connection; authenticated relay transport remains a separate gate.
- Directory signatures do not establish anonymity. The circuit protocol, traffic correlation, exit behavior, congestion control, and adversarial node placement need separate analysis.
- This implementation is custom lab code, not a reviewed standard. Do not use it for sensitive traffic or claim production security.
