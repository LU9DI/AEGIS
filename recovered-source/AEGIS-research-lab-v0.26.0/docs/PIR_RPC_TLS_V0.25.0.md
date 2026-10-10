# AEGIS v0.25.0 — TLS transport for the two-server PIR reference RPC

## What changed

`aegis-pir-rpc-tls-demo` runs two distinct local TCP listeners under TLS and retrieves a fixed-width record from two XOR-PIR replicas. Each replica uses its own certificate/private key. The client validates the issuing CA and the configured server hostname. TLS 1.2 or newer is required. In TLS mode no HMAC pre-shared key is distributed to the client; request and response framing are protected by the TLS record layer. The request nonce/timestamp replay guard, bounded nonce cache, snapshot comparison and fail-closed parsing remain active.

The original `aegis-pir-rpc-demo` remains a legacy loopback HMAC demonstration for wire-compatibility tests. Its messages are **not encrypted** and its shared keys must not be distributed to untrusted clients.

## TLS demonstration

Use a private test or deployment CA and distinct server certificates whose Subject Alternative Names match the expected names. For a local test, the names could be `replica-a.test` and `replica-b.test`; map both names to loopback in the endpoint configuration or pass them as TLS `server_hostname` while connecting to `127.0.0.1`.

```bash
aegis-pir-rpc-tls-demo \
  --ca-cert ./test-ca.pem \
  --cert-a ./replica-a.pem --key-a ./replica-a-key.pem \
  --cert-b ./replica-b.pem --key-b ./replica-b-key.pem \
  --server-name-a replica-a.test --server-name-b replica-b.test \
  --records 64 --index 17 --record-bytes 32
```

The command intentionally starts both listeners in one process and binds only to loopback. It is a TLS/certificate-validation integration demonstration, not an independent-host or production deployment test.

## API guardrails for remote binds

`AuthenticatedPirRpcServer` accepts a remote numeric bind address only when all three conditions hold:

1. a TLS server context is provided and configured with a certificate/key;
2. `allow_remote=True` is explicitly set;
3. no client-shared HMAC key is configured.

`PirRpcEndpoint` accepts a non-loopback destination only with a client TLS context using `CERT_REQUIRED`, hostname verification enabled, and TLS 1.2 or newer. The caller supplies `server_hostname` to verify a DNS SAN while connecting to a numeric host address. TLS client certificates are intentionally not required; the model allows an anonymous client to retrieve PIR shares. Server identity is authenticated to the client, not client identity to the server.

TLS handshakes and shutdowns, frame reads and writes have a 5-second timeout by default; the server limits its listen backlog and active RPC handlers to 128. These are basic resource bounds, not a substitute for deployment rate limits, per-IP controls, abuse detection, admission control or operational monitoring.

## Security boundaries

- TLS provides channel confidentiality/integrity and client-side server-certificate/hostname verification. It does not conceal the client's IP address, packet timing, message sizes or the fact that a PIR request occurred.
- Both replicas still learn the same database version and can collude: XORing their two query masks reveals the requested index.
- The TLS demo starts both replicas in one process/host. Certificate separation does not prove operational independence or non-collusion.
- The snapshot SHA-256 fingerprint is a consistency check. On a low-entropy public database it may allow database fingerprinting; it is not a signed version commitment.
- The server accepts unauthenticated TLS clients by design. There are no blind credentials, quotas, per-client rate limits, signed dataset update protocol, secure audit trail or production key rotation/revocation workflow.
- No live public network, AEGIS onion circuit, QUIC transport, ZK proof, FHE or browser WebAssembly integration is implemented by this change.
- The legacy HMAC transport is still loopback-only and is not switched to TLS automatically. Deployments must explicitly configure TLS and certificates.

## Validation

Tests exercise a trusted TLS chain with two distinct certificate identities, successful PIR reconstruction without client-shared HMAC secrets, rejection of an untrusted CA, rejection of hostname mismatch, TLS-context enforcement and remote-bind guardrails. These tests prove local behavior for the tested implementation, not a cryptographic audit or deployment security.
