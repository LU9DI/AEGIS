# AEGIS v0.25.0 validation record

## Test suites

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: 201 tests passed; no `ResourceWarning` raised.
- `PYTHONPATH=src pytest -q`: 203 passed, 76 subtests passed.
- Focused PIR RPC/TLS and branding regression tests passed after the TLS integration and CLI changes.

## TLS integration

- Constructed two distinct local server certificate identities (`replica-a.test`, `replica-b.test`) signed by a test CA.
- Confirmed CA trust and hostname verification, TLS 1.2+ requirement and retrieval of the requested fixed-width record.
- Confirmed that TLS-mode `PirRpcEndpoint` instances have no HMAC shared key and the TLS application envelope contains no `mac` field.
- Confirmed rejection of an untrusted CA and a hostname mismatch.
- Confirmed remote bind guardrails: TLS + explicit `allow_remote=True` + no client-shared HMAC key is required by the API.
- Confirmed incomplete/stalled frames are closed at the configured timeout.

## Packaging and installed CLI

- Built `aegis_anon_lab-0.25.0-py3-none-any.whl` with local build dependencies and no network fetch.
- Installed the wheel in an isolated virtual environment without optional extras.
- `aegis-pir-rpc-tls-demo --help` and the legacy `aegis-pir-rpc-demo --help` succeeded.
- The installed TLS demo retrieved its row successfully with distinct TLS certificate identities. The emitted JSON is stored in `experiments/pir-rpc-tls-demo-v0.25.0.json`.

## Important scope boundary

The test listeners run in one local process on loopback. A construction-only test validates remote-bind policy; no live service was bound to a public interface or tested over the Internet. TLS protects the transport stream, but it does not hide client IP/timing metadata and does not prevent two PIR replicas from colluding. This validation is not a cryptographic audit or production-readiness claim.
