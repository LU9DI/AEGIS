# AEGIS v0.23.0 — chunk-level XOR secret-sharing prototype

## Status

Implemented as a local primitive in `src/anonlab/secret_sharing.py`, exposed as `aegis-share-demo`. It **does not** transport data over different relays. It replaces the proposed “one bit per path” idea with fixed-width chunk-level 2-of-2 XOR sharing, which is simpler to test and has lower per-bit framing overhead.

## Operation

For each padded chunk `M`, sample a cryptographically random chunk `R`; produce `share_A = R` and `share_B = M XOR R`. A single share is uniformly random and carries no information about the chunk bytes by itself. The client keeps the exact length and SHA-256 integrity manifest locally; all transmitted-size metadata would need to be encrypted/authenticated by a future transport. Reconstruction requires both shares and validates the final digest before returning plaintext.

## Hard limits

- Seeing both shares is enough to reconstruct the plaintext. **Any relay that sees both shares—including a guard shared before routes diverge—can reconstruct the plaintext.** A global observer, colluding relay sets, endpoint compromise, or route reuse can defeat the intended separation. Distinct downstream relays alone are insufficient if the client sends both shares through the same entry guard.
- Chunk count, timing, traffic bursts, and padded-size bucket remain visible in this prototype. It has no cover traffic, packet mixing or traffic-analysis resistance.
- This module does not encrypt or authenticate each path's transport, bind shares to a circuit, handle retransmissions, or protect against denial of service. A production design needs authenticated framing, sequence binding, replay rules and key rotation.
- Splitting every bit across separate connections would impose enormous overhead, destroy locality, magnify loss/reassembly costs and still would not protect against an observer who sees both channels.
- There is no “100% normal Internet speed” guarantee: the receiver needs both shares, so the slowest/missing path affects completion, while sending two shares at least doubles payload traffic before per-hop overhead.

## Run

```bash
PYTHONPATH=src python -m anonlab.secret_sharing --payload-bytes 65537 --chunk-size 4096
```

Output reports aggregate sizes and integrity only. It does not print the payload or either share.
