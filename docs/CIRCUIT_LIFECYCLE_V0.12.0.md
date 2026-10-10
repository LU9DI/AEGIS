# Circuit lifecycle hardening — MALEBOLGE v0.12.0

## Scope

This milestone hardens the local telescoping testbed's client-side lifecycle. It does not claim production security, global replay resistance, stream multiplexing, or anonymity against traffic correlation.

## Single-channel serialization

A `TelescopingClient` owns one TCP connection to its guard and one request/response channel. Until the wire protocol supports stream identifiers and independent response demultiplexing, requests must not interleave. An `asyncio.Lock` now serializes route construction, extension, echo operations, and explicit close. `connect_verified_route()` holds the lock across the entire build so a concurrent task cannot use a partially constructed route.

## Verified-route binding

The high-level client binds the `VerifiedCircuitRoute` object during route construction. It revalidates the route:

- before the guard handshake and before CREATE;
- before each extension;
- after each extension response;
- before each application request;
- after each application response and before returning the response to the caller.

If the pinned trust anchor changes, the revocation epoch advances, a relay descriptor is superseded, a route expires, or revocation state becomes stale, the circuit closes and the error propagates. The client does not return application response bytes from a route that failed the post-operation check.

This is an application-level freshness check. It cannot defend against an attacker who can modify the process, patch the verifier, or restore both the process and its trusted state.

## Lifetime controls

`TelescopingClient` accepts:

- `idle_timeout_seconds` (default 300 seconds)
- `max_lifetime_seconds` (default 3600 seconds)

Both values must be finite positive numbers. Expiry is **lazy**: it is checked when the next API operation occurs, not by a background timer. Requests already in flight are not automatically interrupted at the idle deadline; the absolute maximum lifetime is checked before and after circuit operations. Production transports would need explicit cancellation and timer supervision.

## Failure handling

A timeout, malformed response, sequence uncertainty, expired route, or exceeded maximum lifetime closes the client circuit and clears its in-memory route binding. The current testbed continues to use one echo command to a loopback allowlist; it does not yet implement browser-compatible TCP byte streams, half-close, reset, congestion control, or independent per-stream sequence spaces.

## Test coverage

The v0.12.0 suite covers:

- concurrent `request_echo()` calls over a single client are serialized and return payloads to the correct caller;
- a route whose verifier receives a newer revocation epoch is rejected before DATA reaches the exit;
- idle timeout and maximum circuit lifetime close stale circuits;
- zero, negative, infinite, and NaN lifecycle settings are rejected;
- prior descriptor authorization, replay, circuit-extension, payload-integrity and cleanup tests continue to pass.

## Security limitations

The circuit only binds signed route state available to the current process. There is no external monotonic witness for rollback protection, no global distributed replay cache, and no independent cryptographic audit. Endpoints remain IPv4 loopback-only. The lab must not be used for sensitive communications.
