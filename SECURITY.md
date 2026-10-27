# Security policy

AEGIS is intended for production use as a privacy and anonymity network, but the current repository remains under construction and testing. The source includes research prototypes, local relay testbeds, simulations, and validation artifacts. It is not yet production-ready or independently audited. A production objective is not evidence of production security.

## Safe operating boundary

Until protocol, implementation, deployment, and independent security-review gates have passed:

- Do not use AEGIS for sensitive or production communications.
- Do not treat simulator outputs, synthetic route metrics, loopback relay tests, RPC/TLS demos, or benchmark results as proof of anonymity or security on a live network.
- Do not treat payload encryption as protection against traffic correlation, timing/volume analysis, endpoint compromise, or metadata leakage.
- Do not use remote PIR results for sensitive decisions unless the required verifiable-correctness guarantees are implemented and independently validated. Remote PIR is refused by default because TLS authenticates a transport endpoint but does not prove correct PIR computation. Any unverified research mode must remain an explicit, documented opt-in and must not be described as safe.
- Do not assume two-server XOR PIR protects the requested index if replicas collude. The four-server consistency check is not a cryptographic proof of correct computation and does not prevent collusion or common-mode failure.
- Do not assume the local relay testbed implements a production anonymity network. Garlic-clove delivery/batching semantics, a reviewed live multi-operator protocol, and production-grade key/directory lifecycle are not complete.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [AEGIS-V0.27.3-ADVERSARIAL-PIR-CHARACTERIZATION.md](AEGIS-V0.27.3-ADVERSARIAL-PIR-CHARACTERIZATION.md) for the documented threat boundaries and open work.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through the repository's GitHub Security tab if private vulnerability reporting is enabled. Do not publish exploit details, credentials, private keys, identifying traffic captures, or sensitive data in a public issue. If private reporting is unavailable, contact the repository maintainer through GitHub to arrange a private disclosure channel.

A useful report includes the affected commit/version, component, threat assumptions, prerequisites, reproducible steps or a minimal proof of concept, expected versus actual behavior, and likely privacy/security impact. Redact secrets and avoid testing against systems or traffic you do not own or have permission to assess. Please allow time for triage and coordinated remediation before public disclosure.

## Review expectations

Security-sensitive changes—including cryptographic protocols, relay authentication, circuit construction, directory trust, key derivation, traffic shaping, cover traffic, PIR correctness, and remote RPC—require a documented design rationale and adversarial tests. Prefer established protocol designs and reviewed libraries over new primitives. CI and local tests are necessary engineering evidence but do not replace independent protocol review or multi-host deployment testing.

When a vulnerability is confirmed, add a regression test where practical, document affected versions and mitigations, and coordinate publication of an advisory after a fix or mitigation is available.
