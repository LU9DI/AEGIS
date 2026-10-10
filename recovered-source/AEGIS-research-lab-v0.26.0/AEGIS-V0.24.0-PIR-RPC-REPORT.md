# AEGIS v0.24.0 — authenticated loopback PIR RPC

## What changed

The two-server XOR PIR reference can now be exercised over two distinct TCP listeners using `aegis-pir-rpc-demo`. Requests and responses are authenticated with HMAC-SHA256, use separate domain strings for request/response messages, correlate through a random 256-bit nonce and reject timestamps outside a 60-second window. Each server maintains a bounded replay cache. Per-endpoint keys must be different, and the client checks replica dimensions plus a content snapshot fingerprint before reconstructing the row.

The wire request contains only `protocol`, `server_id`, `nonce`, `issued_at`, and a base64-encoded masked query. It has no selected-index field. The demo intentionally tests two separate listener ports, but both listeners run in the same process. This demonstrates framing, request/response authentication, replay rejection, and reconstruction—not independent operator or machine trust.

## Validation results

- Full `unittest`: **194 tests passed** using `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`.
- Full `pytest`: **196 passed, 76 subtests passed**.
- Targeted `tests/test_pir_rpc.py`: 9 passed.
- `aegis-pir-rpc-demo --records 64 --index 17 --record-bytes 32`: `retrieval_correct=true`, different replica ports, 4 authenticated messages, report explicitly marks encrypted transport / production security false.
- All tests are local; no remote network or anonymity claim is included.

## Security limitations

HMAC authenticates possession of a symmetric key but does not encrypt traffic. Any public client given a replica's shared key could forge messages, so this exact key arrangement is not suitable for a public service. The server bind is loopback-only to reduce accidental remote exposure. An observer who sees both PIR query masks can XOR them and recover the selected index. The nonce cache is in-memory and bounded; it is not a durable global anti-replay mechanism. The snapshot digest helps detect mismatched copies, but may fingerprint a low-entropy dataset. No TLS, independent host/operator validation, quotas, privacy-preserving logging, database refresh/signature protocol, or AEGIS circuit integration is implemented.

The next security gate is a reviewed authenticated-confidential transport appropriate for anonymous clients, a signed opaque database-version commitment, quotas, malicious-replica tests, and two operators on independently hosted systems. Do not expose this loopback harness to untrusted clients.
