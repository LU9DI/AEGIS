# AEGIS v0.25.0 — TLS transport for two-server PIR

## Summary

This release adds an optional TLS-backed transport path for the two-server XOR PIR RPC prototype. It addresses the most important transport weakness of v0.24.0: the legacy demo gave each client the same HMAC pre-shared key the server used, so those keys were not suitable for untrusted public clients and messages were not confidential.

In TLS mode, each endpoint has a server certificate and private key. A client context must require CA validation and hostname verification, and TLS 1.2+ is mandatory. Application-level HMAC keys are not sent to or configured in the client; TLS record integrity/confidentiality protects the framed RPC messages. A random nonce, timestamp window, replay cache, message correlation, record-size checks and the replica snapshot comparison remain in place.

The v0.24.0 `aegis-pir-rpc-demo` remains available as a loopback-only HMAC compatibility exercise. The new `aegis-pir-rpc-tls-demo` exercises the TLS mode with two distinct certificate identities and an explicit trusted CA.

## Additional resource bounds

- Default frame read/write timeout: 5 seconds, configurable per server within 0.05–60 seconds for tests and controlled deployments.
- TLS handshake/shutdown timeout follows that same setting.
- Listen backlog and active application handlers are bounded to 128.
- Non-TLS/HMAC mode binds only to loopback. Remote server bind requires TLS, explicit `allow_remote=True`, and no client-shared HMAC secret.
- A remote endpoint must use TLS, a numeric destination address and server hostname validation. The TLS client context must use `CERT_REQUIRED` and `check_hostname=True`.

These bounds reduce basic resource-exhaustion exposure; they are not a full production rate-limit or admission-control system.

## Validation

- Full `unittest`: 201 passed with `ResourceWarning` elevated to an error.
- Full `pytest`: 203 passed, 76 subtests passed.
- TLS-specific tests include successful retrieval with no client-shared HMAC key, CA rejection, hostname mismatch rejection, TLS context validation, remote-bind guardrails, and refusal of stalled frames.
- The wheel was installed in a clean virtual environment without project extras. The installed `aegis-pir-rpc-tls-demo --help`, legacy demo `--help`, and TLS demo execution succeeded.
- Smoke result: `experiments/pir-rpc-tls-demo-v0.25.0.json`; a 32-record demonstration retrieved record 17 correctly, and the output explicitly states that both listeners ran in one process and that the run is neither a live remote-network test nor a security proof.

## Security limitations

TLS authenticates each server to a client and provides confidentiality/integrity for that stream. This design intentionally does not require a TLS client certificate, to avoid building a stable client identity into this prototype. As a consequence, the server does not identify the client at the TLS layer. TLS does not hide the client's IP address, traffic timing, message sizes or the fact of a request.

The two replicas still learn database version/shape and can collude: XORing their masked queries reveals the requested index. The current demo runs both listeners in a single process and host; it does not establish operator independence. Dataset fingerprints are consistency checks, not signed commitments. Rate limiting, a signed dataset-version/update protocol, blind credentials, durable replay tracking, certificate revocation/rotation operations, anonymous AEGIS circuit integration, and an independent cryptographic audit are not implemented.

No Rust/QUIC transport, ZK proof system, FHE engine, browser WebAssembly client or production anonymity claim is added by this change. The release advances the PIR RPC transport only.
