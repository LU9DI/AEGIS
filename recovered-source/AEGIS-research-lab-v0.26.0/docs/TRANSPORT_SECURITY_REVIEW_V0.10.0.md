# Transport-authentication security review — v0.10.0

## Findings addressed

1. **Target endpoint could accept a spoofed TCP listener:** added a nonce-bound Ed25519 transcript response verified against the target identity key from a verified descriptor.
2. **Client might send CREATE before authenticating target:** authenticated descriptors trigger link authentication before the ntor-derived CREATE exchange.
3. **Relay-to-relay hop did not authenticate the initiating key holder:** the mutual mode requires the initiator to sign the target-bound hello and the receiver verifies the digest/public-key relationship.
4. **Captured hello replay:** receivers maintain a bounded, process-local nonce guard and reject repeat `(peer identity, nonce)` tokens.
5. **Silent fallback from verified routes:** high-level route construction rejects descriptors without identity public keys; a relay cannot initiate authenticated extension when it lacks its own identity private key.

## Residual risks

- A receiver currently verifies that an initiating relay holds the private key for its claimed identity digest, but it does not verify the sender's directory-authority certification, revocation status, or authorization to relay. That policy is not yet implemented.
- Replay state is process-local and no-eviction. It resets on restart and can be exhausted; do not treat it as a public-network DoS solution.
- Identity authentication is not transport encryption; it reveals peer relay identities on inter-relay links and is vulnerable to traffic analysis of connection timing/volume.
- The custom MALEBOLGE handshake integration, domain separation, framing, persistence, and route lifecycle have not been independently audited.
- The circuit remains loopback-only and data-plane behavior is the echo test harness rather than a general stream protocol.
- Low-level APIs intentionally retain compatibility for unauthenticated fixtures with no identity public key; production application code must not expose those entry points.

## Verification

Automated tests include successful signed-directory route construction, server identity mismatch, initiating relay signature tampering, nonce replay rejection, descriptor digest mismatch, and the existing circuit, replay, persistence, and resource-boundary suite. See `experiments/VALIDATION_V0.10.0.md` for the exact results from the current build.

Passing these tests establishes only the listed software invariants. It does not certify production anonymity or cryptographic security.
