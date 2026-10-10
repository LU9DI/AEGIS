# Stream multiplexing security review — v0.13.0

## Implemented safeguards

- Nonzero 32-bit hop-local stream identifiers; stream ID zero remains reserved for circuit control.
- 64-bit monotonic command sequence per relay hop.
- Response lookup keyed by both command sequence and stream ID.
- Single client reader task with pending-future dispatch, preventing concurrent reads from stealing responses.
- Client and relay limits on the number of active streams.
- Cancellation propagates through the existing circuit; a relay queues DATA downstream before it can process a later CANCEL, preserving child sequence order.
- Canceled late responses are marked as ignorable for the relevant pending key; the circuit is not kept usable after protocol-level mismatches.
- Test coverage includes concurrent streams with out-of-order completion, cancellation, stream admission limits and post-cancel reuse of the same circuit.

## Findings / open risks

1. **Not a general stream protocol.** Each “stream” is one bounded request and one bounded response. There are no chunked DATA frames, half-closes, reset/FIN semantics, backpressure windows, fair scheduler or retransmission policy.
2. **Correlation metadata remains visible locally.** The direct neighbor sees sequence and hop-local stream ID metadata. Per-hop IDs differ, but timing and volume remain observable and correlatable.
3. **No production traffic analysis defense.** The current checks inspect parsed relay observations; they do not simulate a global passive attacker or prove anonymity-set properties.
4. **Cancellation is best-effort.** A response may race with cancellation; completed responses win. Link failure during cancellation invalidates the circuit.
5. **Lab-only transport.** Relays and destination are restricted to IPv4 loopback, and exit destinations must be allowlisted. Do not expose these listeners to untrusted networks.
6. **Cryptography unaudited.** The MALEBOLGE-specific KDF, envelope composition, transcript and cancellation behavior still require independent review and fixed cross-implementation test vectors.
7. **Benchmark is not a performance win.** A local 16 × 4 KiB run had similar aggregate goodput to serial execution and substantially worse per-stream p50 because of dispatch/queueing overhead. Optimization must follow fair, repeatable measurements rather than marketing claims.

## Verification

Validation at this milestone: `python -m pytest -q` → 100 passed, 11 subtests passed. Focused `tests/test_telescoping.py` → 25 passed, 4 subtests passed. ZIP-extracted suite must be rerun as part of release packaging.
