# AEGIS v0.26.0 — PIR RPC certificate lifecycle and abuse-control report

## Delivered

- Added live leaf-certificate rotation through `AuthenticatedPirRpcServer.rotate_tls_certificate(certfile, keyfile)`. The certificate/key bytes are copied once into a private temporary directory (0600 files), checked with a candidate TLS context, then loaded into the live listener context. The call returns the SHA-256 fingerprint of the new leaf certificate. A mismatched or unreadable pair fails before changing the current listener certificate.
- Added a per-replica aggregate token bucket, with bounded configuration (0.1–10,000 requests/s; burst 1–10,000), default 100 requests/s and burst 128. Exposed only aggregate accepted, rate-limited and active-connection counts. No per-client IP, address, stream identifier or request ID is stored in the limiter.
- Added TLS demo flags `--max-requests-per-second` and `--request-burst` and included aggregate counters in its JSON output.
- Added certificate rotation, rollback-on-bad-key-pair, rate-limit exhaustion, configuration bounds, and HMAC-server guard tests.
- Added a red-team case that deliberately alters one TLS replica's computed response while retaining the expected snapshot fingerprint. The client accepts the corrupted reconstruction. This is recorded as an unresolved correctness gap; TLS protects the channel and authenticates the endpoint but does not prove the server computed its answer correctly.

## Validation

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: 207 tests passed in 25.3 seconds, no `ResourceWarning`.
- `PYTHONPATH=src pytest -q`: 209 passed, 76 subtests passed in 25.75 seconds.
- Focused PIR RPC tests: 22 passed, including rotation, rate-limiting and existing TLS validation tests.
- Built and installed `aegis-anon-lab 0.26.0` into a clean virtual environment. `aegis` and `aegis-pir-rpc-tls-demo --help` ran successfully.
- Executed the installed TLS demo with ephemeral CA and two leaf certificates: result retrieval passed; distinct local listener ports, correct TLS hostname validation, and aggregate counters (`1 accepted`, `0 rate-limited`, `0 active`) were recorded for each replica.
- The source ZIP is created without Python caches, build folders, egg-info, nested duplicate v0.22 source tree, or ephemeral CA/private-key material.

## Security interpretation and limitations

The token bucket is aggregate per endpoint and intentionally does not track a client IP. It protects the query-processing path after a request has been parsed and validated; it does not rate-limit TLS handshakes at an upstream edge, stop distributed denial-of-service, or isolate abusive users. Use independent network-edge controls and monitoring in any remotely reachable experiment.

The TLS demo continues to run both replicas in one process on one host. The two-server XOR PIR protocol protects the index only against either server considered separately; if both collude, they can recover it from the two masks. More importantly, a malicious TLS replica can return a false answer with the expected snapshot hash. A correct fix needs verifiable PIR or another designed correctness mechanism; certificate rotation, signatures over snapshot metadata, and TLS alone do not solve it.

CA rotation requires trust overlap: publish a trust bundle containing old and new roots, verify adoption by clients, rotate leaf certificates, and only then remove the old root. This prototype does not automate CA distribution, revocation, OCSP/CRL, certificate transparency, HSM-backed keys, or independent operator orchestration.

This remains a research prototype, not a production anonymity service. No push to a remote repository was performed.
