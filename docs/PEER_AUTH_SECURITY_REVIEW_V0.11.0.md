# Peer authorization security review — v0.11.0

## Issue closed in the strict configured path

Prior to v0.11, a peer could claim an identity digest and prove possession of that Ed25519 key without demonstrating that the identity was certified by the pinned directory authority or absent from the current revocation feed. A local relay now verifies the full certified descriptor before sending a link-auth response.

## Checks added

- Current signed revocation feed is mandatory for peer authorization.
- Descriptor relay and authority signatures are verified.
- Expired descriptors, revoked identities, wrong-authority certificates, descriptor rollback, malformed certificates, and peer identity/public-key mismatches are rejected.
- The signed hello includes the exact certificate bytes and is bound to the target relay ID and a fresh 32-byte nonce.
- Optional relay-local allowlists can further restrict accepted peers.
- The receiving relay's nonce replay guard is updated only after certificate and local policy checks succeed.
- Relay configuration refuses a verifier without a persistent state path and checks its own certificate against its identity and onion key.

## Tests

New end-to-end tests exercise a revoked peer, an expired certificate, a certificate signed by a different authority, and a currently valid but disallowed peer. The signed-directory three-hop flow now configures independent persistent verification state for each relay, rather than reusing the client's verifier as the relay's trust boundary.

## Residual risks

- This is a Python research implementation with no independent cryptographic audit.
- Link authentication does not encrypt the TCP hop and relay-to-relay identities remain visible on the transport.
- The replay guard remains process-local, has a finite no-eviction capacity, and resets on restart; resource-exhaustion handling still needs a durable/rate-limited design.
- A signed descriptor proves authority certification under the pinned key, but the directory authority remains a single trust root. There is no transparency log, quorum, gossip, or external monotonic state.
- Low-level fixture APIs retain a key-possession-only fallback if a `RelayNode` is not configured with a `DirectoryVerifier`. This branch is intended only for local tests.
- `authorized_peer_ids=None` means any non-revoked, current relay certified by the pinned authority may initiate a link. Deployments requiring topological/role restrictions must configure an allowlist.
- Circuit construction still uses experimental custom protocol framing and an ntor-derived handshake adaptation; the project is not Tor-compatible.
- Traffic timing/volume correlation, browser fingerprinting, DNS behavior beyond the lab harness, WAN routing and active adversaries are not addressed here.

## Decision

Accept the change as a research milestone only. Do not represent v0.11 as a production anonymous network. Before expanding beyond loopback, require a protocol design review, independent cryptographic assessment, replay-guard/resource-exhaustion work, and distributed testbed measurements.
