# MALEBOLGE v0.5.0 — one-hop handshake benchmark

**Date:** 2026-10-09  
**Environment:** Python 3.13.5; Linux 6.18.44 x86-64; loopback `127.0.0.1`  
**Purpose:** validate the isolated ntor-derived handshake path and quantify local setup overhead. This is not a network anonymity test.

## Method

- 100 in-process handshakes timed from client ephemeral generation through relay response and client authenticator validation.
- 100 TCP handshakes on loopback, using one new TCP connection per handshake.
- One relay identity digest and one static X25519 onion key were used; each client and relay handshake generated fresh ephemeral key material.
- A process-local replay guard remained enabled for the loopback server.
- Each handshake transmits an 84-byte client message and a 64-byte server response: 148 bytes of handshake payload, excluding TCP/IP and framing overhead.
- All returned key schedules were accepted by the client; the unit suite separately checks client/relay key agreement and negative cases.

## Results

| Metric | Result |
|---|---:|
| In-process crypto p50 | 0.218 ms |
| In-process crypto p95 | 0.286 ms |
| Loopback TCP handshake p50 | 0.421 ms |
| Loopback TCP handshake p95 | 0.607 ms |
| Loopback handshake throughput | 2,276 handshakes/s |
| Handshake payload (client + relay) | 148 bytes |

Raw measurements are recorded in [`ntor-loopback-v0.5.0.json`](ntor-loopback-v0.5.0.json).

## Interpretation

The one-hop handshake completes locally with small control messages. This is useful baseline data for circuit setup, but does not tell us the cost of establishing a three-hop circuit over a WAN. Geographic RTT, packet loss, queueing, relays under load, descriptor validation, and a telescoping circuit-extension protocol are not included. The per-hop handshake has not been integrated with the current v2 circuit because contacting each relay independently from the client would reveal the route.

The code follows the published Tor ntor v1 authentication transcript but uses a MALEBOLGE-specific HKDF info label and 32-byte directional AEAD key partition; it is **not Tor-wire-compatible**. The relay descriptor and its identity-to-onion-key binding are injected by the test harness rather than validated by a directory implementation. This adaptation has not received independent cryptographic review and must not be used for real or sensitive traffic.

## Verification

Command:

```bash
PYTHONPATH=src python -m anonlab.ntor_benchmark --rounds 100 --output experiments/ntor-loopback-v0.5.0.json
PYTHONPATH=src python -m unittest discover -s tests -v
```

The complete test suite passed 29 tests in the latest run. A unit test uses a two-round smoke benchmark; the measurements above are from the 100-round run.

## Next gate

Design and review telescoping extension before integrating these per-hop keys into the v2 relay chain. The design must avoid revealing downstream relay identifiers to the entry relay, validate descriptor/key binding, define key lifetime and rotation, handle partial failure, and model DoS/resource exhaustion. Then measure full-circuit setup over multiple independently administered hosts. Do not infer anonymity from handshake correctness.
