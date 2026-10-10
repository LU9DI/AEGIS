# AEGIS v0.26.0 validation record

## Test results

- Focused `unittest` for PIR RPC/TLS: 22 tests passed.
- Full `unittest`: 207 tests passed in 25.3 s using `-W error::ResourceWarning`; no resource warnings were emitted.
- Full `pytest`: 209 tests and 76 subtests passed in 25.75 s.
- Regression coverage includes live certificate rotation, failed-rotation preservation of the served certificate, global rate-limiter exhaustion without client identity state, bounded config, legacy-HMAC rotation rejection, and a red-team limitation test for malicious-but-authenticated PIR answers.

## Installed wheel smoke test

- Distribution: `aegis-anon-lab==0.26.0`.
- Built with installed setuptools and no build isolation or downloads.
- Installed in `/mnt/data/aegis-v0.26.0-wheel-venv` (development validation only, not part of release ZIP).
- `aegis --help` and `aegis-pir-rpc-tls-demo --help` passed.
- The installed TLS demo retrieved record 17 from the local two-listener test. Report flags are `is_live_remote_network_test=false`, `is_production_secure=false`, `is_security_proof=false`.
- Both endpoint aggregate counters reported one accepted request, zero rate-limited requests and zero active connections after completion.

## Security limitations

- Certificate rotation is live for subsequent handshakes in the current `SSLContext`; the caller must still manage certificate validity, SAN, trust roots and key storage.
- The rate limit is aggregate per replica, not per identity. It does not protect TLS handshakes at an edge or prevent a distributed attack.
- The red-team test demonstrates that TLS-authenticated replicas can return a corrupted PIR answer while claiming the matching snapshot fingerprint. Correctness-verifiable PIR has not been implemented.
- Both demo replicas share one process/host; no independent-operator deployment or live remote-network test was performed.
