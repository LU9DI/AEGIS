# PIR RPC transport: resource and shutdown boundaries

The RPC server uses asyncio's TLS listener when `ssl_context` is configured. The current `MAX_ACTIVE_RPC_CONNECTIONS` guard is enforced inside `_handle`, which asyncio invokes only after a TLS handshake succeeds. Therefore it bounds application handlers, **not concurrent TLS handshakes**. `ssl_handshake_timeout` limits how long an individual handshake can remain pending, but it is not a concurrency limit; `backlog` is also not a bound on all handshakes already accepted by the event loop.

## Security implications

- A peer that can reach a TLS listener may open many slow or incomplete handshakes and consume file descriptors, memory, and TLS CPU before the application-level active-connection counter is incremented.
- The handler task registry used by `close()` likewise contains only connections that have completed TLS negotiation and entered `_handle`. Do not interpret an empty registry or `active_connections == 0` as proof that no TLS handshake is pending.
- The handshake timeout limits the lifetime of each pending handshake but does not establish a strict upper bound on simultaneous handshakes under sustained connection churn.

## Required mitigation before exposed deployment

Deploy behind a front proxy/load balancer that enforces a documented concurrent-handshake and connection-rate limit, or implement and test an accept/TLS lifecycle that places a strict cap on handshakes before the asyncio application callback. Validate behavior under slow-handshake floods on the target Python/OpenSSL version and operating system. Do not claim that `MAX_ACTIVE_RPC_CONNECTIONS` protects the TLS handshake phase.

This is a transport resource-control limitation, separate from durable replay admission. It remains an explicit deployment blocker for directly exposed TLS listeners until a tested mitigation is in place.
