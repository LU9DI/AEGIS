# AEGIS v0.24.0 — authenticated two-endpoint PIR RPC prototype

## Status

`aegis-pir-rpc-demo` starts two separately bound TCP listeners on loopback and retrieves a fixed-width record using the existing two-server XOR PIR construction. Each endpoint uses a different 256-bit pre-shared HMAC key. Requests and responses are framed JSON, authenticated with HMAC-SHA256 using separate request/response domain strings, correlated with a 256-bit nonce, timestamp-checked, and replay-checked by a bounded nonce cache. Each response carries record count/width and a SHA-256 snapshot fingerprint; the client rejects mismatching replica snapshots. The fingerprint can allow dictionary confirmation for low-entropy databases, so this field is a research convenience, not a universal production design.

The selected row index is not a request field. The only query sent to a replica is a masked N-bit vector. A replica that sees only its own query learns no information about the target index under the reference protocol's uniform-mask model. Two colluding replicas can XOR the query vectors and recover the one-hot target mask.

## Run

```bash
PYTHONPATH=src python -m anonlab.pir_rpc_demo --records 64 --index 17 --record-bytes 32
# or after installing the wheel:
aegis-pir-rpc-demo --records 64 --index 17 --record-bytes 32
```

The output must report `retrieval_correct: true`, distinct replica ports, four authenticated messages (two requests and two responses), and `is_production_secure: false`.

## Authentication and limits

- HMAC-SHA256 authenticates a message as originating from an entity possessing that endpoint's pre-shared key and detects tampering. Request and response tags use different domain strings.
- A random 256-bit nonce and a 60-second timestamp window reduce replay risk. Each server has a bounded in-memory nonce cache (up to 65,536 entries); cache eviction during high-rate traffic means this is not a complete production anti-replay design.
- Both endpoint keys must be distinct and at least 32 bytes. The client refuses duplicate endpoint identity or the same host/port.
- Binds are restricted to numeric loopback addresses. This is deliberate: HMAC does **not** encrypt traffic, and if an observer can see both PIR queries it can XOR them to recover the requested index. The demo's shared key is also unsuitable for embedding in an untrusted public client, because that client could forge HMAC messages.
- The demonstration hosts both listener tasks inside one process, even though they use separate ports, keys, and server instances. That demonstrates the RPC boundary and protocol handling, not operator or machine independence.
- The snapshot SHA-256 allows mismatched copies to be detected, but can act as a fingerprint for low-entropy databases. Production should prefer a signed, opaque database-version commitment with a carefully analyzed privacy model.
- No TLS, remote transport, onion-circuit integration, hidden client IP, privacy-preserving logs, rate limiting, database refresh protocol, signed public server identity, or anonymous credential system is implemented.
- This is still O(N) server work and O(N) query bandwidth. PIR does not make arbitrary websites instant and does not hide request timing, access-link identity or response size.

## Tests

`tests/test_pir_rpc.py` checks record retrieval over two listeners, request fields excluding an index, collusion recovery, MAC tampering, replay rejection, response corruption, distinct endpoint/key enforcement, loopback-only binding and mismatching database shapes. Existing exhaustive tests retain the single-server query-distribution check.

## Next security gate

Before remote deployment, replace the loopback-only HMAC demo with a reviewed protocol using authenticated confidential transport and a trust model that does not distribute server signing secrets to arbitrary clients; provision independent replica operators and database-version commitments; test hostile/malicious replicas, timing leakage, request quotas, persistence/replay behavior, and a client access path that does not reveal the same identity to both replicas. Do not claim production PIR or anonymity from this prototype.
