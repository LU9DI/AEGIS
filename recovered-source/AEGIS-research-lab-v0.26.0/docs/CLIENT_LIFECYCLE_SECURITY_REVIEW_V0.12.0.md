# Client lifecycle security review — v0.12.0

## Changes reviewed

- `TelescopingClient` serializes the one request/response socket with an asyncio lock.
- Verified route construction holds the lock through the full multi-hop build.
- A route created by `DirectoryVerifier` is bound to the client, then checked before and after route extensions and application echo requests.
- Idle timeout and absolute maximum lifetime are checked fail-closed at API boundaries; hard lifetime is checked again after asynchronous operations.
- Route invalidation and lifetime expiration clear client state and close the guard connection.

## Positive invariants tested

- Concurrent callers on one circuit cannot interleave writes/reads and receive each other's responses.
- An updated revocation epoch invalidates a live route before an application DATA command can reach the exit.
- Expired idle and maximum-lifetime circuits are closed before new data is sent.
- Invalid timeout configuration is rejected.
- Existing loopback identity, descriptor, peer authorization, sequence, replay, and resource cleanup tests continue passing.

## Residual risks

1. **Not production secure.** No independent review of the custom transcript, KDF, envelope, or circuit protocol has been completed.
2. **Lazy idle expiry.** A circuit that is idle remains connected until another API operation observes expiry or the remote closes it. A future service should implement supervised timers and cancellation.
3. **No stream multiplexing.** The lock serializes requests rather than supporting concurrent independent streams. One slow operation blocks all work on that circuit.
4. **Limited rollback protection.** The persisted directory state cannot detect an attacker restoring an earlier valid state file without an external monotonic witness or transparency/gossip system.
5. **No traffic-analysis guarantee.** The route shape and timing/volume patterns can still be correlated. The guard knows the client network endpoint; the exit knows the destination and application payload.
6. **Loopback-only.** Host validation limits endpoints to IPv4 loopback. Nothing in this milestone authorizes a public listener.

## Release gate

This version is a research milestone only. Do not expose it to the Internet or rely on it for private communications. The next gate is a stream-oriented state machine with independent stream IDs, explicit flow control and supervised cancellation, followed by multi-host testing and independent protocol review.
