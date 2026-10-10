# Security review — v0.22.0 fair write scheduler

## Guardrails added

- Aggregate scheduler work is capped at 512 commands and 8 MiB, counting queued and currently-dispatched payloads.
- Each stream's queue preserves FIFO command order; a round-robin turn changes only the interleaving between streams.
- Sequence numbers, hop-local stream IDs and response correlation futures are allocated while holding the existing circuit send lock.
- Pending commands are failed on circuit close; the queue is cleared, and the diagnostic trace is bounded to 8,192 ephemeral stream IDs.
- If an exception occurs after some frames may have been queued to the socket, the circuit is closed rather than reused with uncertain sequence state.
- An admission-budget rejection occurs before dispatch and is propagated without closing a healthy circuit.

## Residual risks

- This remains custom protocol logic and has not undergone independent security review.
- The scheduler does not implement production congestion control, priority policy, per-user fairness, or protection against a malicious client filling its own queue within the defined caps.
- A cancellation at the wrong point may force circuit closure; availability is preferred over reusing a circuit with uncertain write/ACK state.
- The fairness metric is derived from finite transfers; it does not establish long-lived fairness.
- Loopback tests do not model packet loss, kernel/network behavior over WAN, or active adversarial relay operators.

## Verification

The v0.22.0 suite adds integration tests for four-stream round-robin interleaving, payload integrity, post-completion queue counters, and queue-budget rejection without circuit teardown. The A/B benchmark enforces integrity, relay-observability and full cleanup for every run.
