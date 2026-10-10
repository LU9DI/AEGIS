# AEGIS v0.26.0 — PIR TLS certificate lifecycle and rate-limit operations

## Scope

This note describes operations for the experimental PIR RPC TLS endpoint. It does not define production PKI, a distributed deployment, or verifiable PIR. Keep listeners on loopback unless an isolated test/deployment explicitly requires a remote address; a remote bind needs TLS plus `allow_remote=True`, and HMAC pre-shared keys are forbidden in that mode.

## Leaf certificate rotation

`AuthenticatedPirRpcServer.rotate_tls_certificate(certfile, keyfile)` is available only on a started TLS server. It loads the candidate certificate/key pair into a temporary server context first. If the certificate is unreadable or the private key does not match, the method raises and leaves the live certificate unchanged. It then replaces the certificate chain in the existing `SSLContext` and returns the SHA-256 fingerprint of the new leaf certificate's DER bytes.

The rotation applies to new TLS handshakes. Existing negotiated TLS connections are not renegotiated. The caller must ensure that:

- the certificate has a `subjectAltName` matching every configured client `server_hostname`;
- the certificate chains to a root already trusted by clients;
- the key is held in a secret store or a file with restrictive permissions (typically `0600`), never committed to source control or included in the ZIP/wheel;
- the deployment records the returned fingerprint without recording client IPs, nonces or query values.

For a normal leaf renewal under the same CA, validate and distribute the new cert/key pair to one replica at a time, test a fresh handshake and a PIR request, then continue to the next replica. Keep a rollback copy in the secret manager, not in the project archive.

## CA rotation

Do not rotate the CA and leaf certificate in one step unless client trust is already coordinated. Use a trust-overlap period: distribute a trust bundle containing old and new roots, verify clients have loaded it, then rotate leaf certificates to the new CA, and only remove the old root after all replicas and clients have migrated. This prototype does not automate trust-bundle delivery, OCSP/CRL checking, certificate transparency, or private-key rotation in an HSM.

## Aggregate token bucket

Each replica enforces a single aggregate token bucket (default 100 accepted requests/second and burst 128). Configuration is bounded to 0.1–10,000 requests/second and burst 1–10,000. The server exports only aggregate `requests_accepted`, `requests_rate_limited`, and `active_connections` counters. It intentionally stores no per-client IP, peer address or request identifier in the rate-limiter state.

This prevents excess application-level PIR computation once a request has been parsed and validated, but does not rate-limit TLS handshakes at the edge, prevent distributed denial-of-service, or isolate heavy clients from legitimate users. A public deployment still requires operator-managed edge controls, alerting, abuse policy, and load testing. Per-IP throttling is not implemented because it would collect/link client network identity and is often ineffective behind anonymity relays.

## Security limits and red-team result

TLS authenticates the server identity and protects the connection from network modification. It does not prove that the server computed the PIR response correctly. The test suite includes a red-team case where one TLS-authenticated replica returns a corrupted answer but claims the expected database snapshot fingerprint; the current client accepts the corrupted reconstruction. This gap is deliberate and documented rather than obscured. Closing it requires a separately designed verifiable-PIR or equivalent correctness mechanism, not merely a certificate or signed snapshot hash.

The two-server XOR protocol also remains private only when the replicas do not collude: each sees one individually random query, but both queries together reveal the selected index. TLS, rate limiting and certificate rotation do not change this property.
