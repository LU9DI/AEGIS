---
name: privacy-protocol-review
description: Review anonymous-network and privacy-preserving protocol changes for leakage and threat-model regressions.
---
# Privacy protocol review

- State the adversary model, protected metadata, trust assumptions, and intended security property before modifying protocol behavior.
- Distinguish measured properties from assumptions and theoretical claims; do not claim anonymity from encryption alone.
- Review traffic, timing, size, routing, error, and operational metadata leaks, not only payload confidentiality.
- Use vetted cryptographic primitives and reviewed constructions; do not introduce bespoke crypto or downgrade checks.
- Treat keys, manifests, snapshots, peer identities, and RPC inputs as untrusted until authenticated and validated.
- Keep secrets and real identities out of logs, fixtures, and benchmark output.
- Test downgrade, replay, malformed input, peer faults, partial failure, and privacy regression scenarios.
- Document residual risks and conditions under which a claim does not hold.
