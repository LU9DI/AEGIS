# Contributing

AEGIS is intended to become a production-grade privacy and anonymity network. The current repository contains recovered source, experimental implementations, local relay testbeds, simulations, and validation artifacts; production readiness has not been established. Contributions must preserve that distinction.

## Security and privacy invariants

- Preserve fail-closed behavior for remote PIR and other operations whose correctness or trust requirements have not been satisfied. Do not silently opt users into unverified research modes.
- Do not claim anonymity, traffic-analysis resistance, malicious-replica resistance, or live-network security based solely on encryption, route scores, simulator output, loopback tests, or a passing unit test.
- Treat colluding relays, colluding PIR replicas, malicious directory inputs, replay, Sybil concentration, traffic correlation, metadata leakage, and resource exhaustion as explicit threat cases where relevant.
- Never implement cryptographic primitives from scratch. Use established cryptographic libraries and documented, independently reviewed protocols. Do not invent custom cryptographic constructions as a shortcut.
- Do not weaken authentication, certificate validation, replay checks, input bounds, or fail-closed guards to make a demo or benchmark pass.
- Do not add blockchain, tokens, remote code execution, or mandatory hosted services without a documented design review and explicit approval.
- Do not include real user traffic, credentials, private keys, sensitive datasets, or identifying network captures in fixtures, tests, logs, or reports.

## Tests and validation

- Add tests for normal behavior, malformed/hostile inputs, missing or stale telemetry, authentication failures, replay, malicious or colluding peers, resource exhaustion, and crash/failure recovery as applicable.
- Include negative tests that prove unsafe configurations are rejected by default and that any research-only opt-in is explicit and clearly documented.
- Keep tests deterministic and bounded. Label synthetic data and simulated network conditions as such.
- Run the relevant pytest suite, compilation checks, package-install/entry-point checks, and CI workflow for changes. Report exact commands and outcomes; do not claim tests ran if they did not.
- CI validates the specific code paths and artifacts it executes. It is not an independent protocol audit or proof of anonymity or production readiness.

## Architecture and documentation

- Update `README.md`, `SECURITY.md`, `docs/THREAT_MODEL.md`, `docs/ARCHITECTURE.md`, and relevant protocol/implementation-status documents when a change alters capabilities, assumptions, trust boundaries, or limitations.
- Document protocol goals, attacker capabilities, key lifecycle, relay trust, directory authorization, anti-replay behavior, metadata leakage, and failure behavior before implementing a material protocol change.
- Keep research prototypes and production paths clearly separated. Do not describe loopback TCP chains, relay testbeds, RPC/TLS demos, synthetic route metrics, or simulated cover traffic as a live multi-operator anonymity network.
- Do not close a production gate without implementation evidence, adversarial tests, independent review where required, and deployment-level validation.

## Recovery artifacts

The recovered archive and current Git source have documented differences. Do not overwrite or reconcile those differences automatically. Make deliberate, reviewable changes and preserve checksums and provenance when touching recovery artifacts.
