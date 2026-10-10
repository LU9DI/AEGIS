# MALEBOLGE local testbed security review — v0.7.0

**Scope:** code review of the local telescoping harness and its tests. This is not a cryptographic audit, formal verification, or approval to deploy.

## Security properties exercised by tests

- The listener and descriptor APIs require literal IPv4 loopback endpoints.
- The exit requires an exact `(host, port)` allowlist entry before opening an echo destination.
- Outer frame lengths are checked before the framed body is read.
- Every active relay handler is admitted under a per-relay cap (default 64; configuration constrained to 1..1024) and decrements the counter in a `finally` path.
- Per-hop command sequence must match the expected sequence; the circuit has a finite 4,096-command budget and the client fails closed before attempting a command after exhaustion.
- The client validates the circuit-bound response sequence and closes on response parse, authentication, timeout or integrity errors.
- Integration checks run multiple independent clients at once, verify that the parsed command fields at entry/middle do not contain the echo destination port, and verify that admitted handler counters return to zero after closing clients.

## Limitations and residual risks

1. **No production protocol:** the KDF and framing are MALEBOLGE-specific experiments. The handshake borrows an ntor transcript but is not wire-compatible with Tor and has not received an independent cryptographic review.
2. **No signed descriptor directory:** identity digests and onion public keys are pinned by the test harness. There is no signature lifecycle, expiry, rotation, revocation or consensus.
3. **No internet-facing relay links:** the testbed refuses non-loopback endpoints by design. The per-relay connection cap is process-local and is not a substitute for per-source rate limiting, OS-level accept-queue policy or distributed abuse controls.
4. **Replay guard state:** handshake replay history is process-local and bounded; it resets on restart and fails closed when full. This trades availability for avoiding unsafe eviction in a research harness.
5. **Metadata leakage:** frame lengths, direction, timing, circuit setup/teardown and volume are visible. No padding, mixing, cover traffic or correlation-attack campaign is implemented.
6. **Application transport is not general:** the data plane is a framed loopback echo request/response. It lacks streams, multiplexing, proper flow control, congestion control and browser integration.
7. **No distributed failures tested:** relays share one process and failure domain in local benchmarks. Colluding relays, malicious descriptors, link resets, global observers and WAN latency are out of scope.
8. **Diagnostic observability:** relay observations are an in-memory test ledger. They should not be repurposed as production logging, and output must remain free of payload/key material.

## Blocking gates before any public or sensitive use

- Independent review of the handshake transcript, KDF, AEAD nonce/state design and message framing.
- Authenticated relay descriptors with signed keys, expiry, rotation and revocation.
- Circuit construction/failure recovery specified as a state machine and tested with injected crashes, timeouts, partial frames and concurrent faults.
- Bounded buffering, stream flow control, congestion control and load/abuse policies.
- Multi-host testbed plus a published attacker model and correlation-analysis results.
- Independent penetration testing and a responsible release process.

The current harness is intentionally loopback-only. Do not expose its ports or use it for sensitive traffic.
