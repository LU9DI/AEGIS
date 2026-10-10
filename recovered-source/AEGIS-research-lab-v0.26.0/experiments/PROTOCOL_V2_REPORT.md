# MALEBOLGE protocol v2 / v0.4.0 local validation report

Date: 2026-10-09 (UTC environment date)

## Scope

Protocol v2 adds authenticated circuit IDs and sequence numbers on top of the loopback-only ChaCha20-Poly1305 envelope. This report validates the implementation and benchmarks on one local host. It does not measure anonymity or WAN performance.

## Automated validation

- `PYTHONPATH=src python -m compileall -q src tests`: passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v`: 17 tests passed.
- The replay integration test sent a valid first frame to a local relay, then resent the same captured frame on a new connection. The relay accepted the first circuit and closed the replayed connection.
- Persistent 3-hop encrypted-circuit benchmark: all payload SHA-256 hashes matched.

## Matched-host measurements

Both paths used three relay subprocesses on `127.0.0.1`, an 8,000,000-byte payload in each direction, five bulk trials, 30 latency probes, and the same Linux/Python host. Because the benchmark programs use different I/O strategies, this is an engineering comparison rather than a controlled end-to-end security/performance claim.

| Metric | TCP relays without encryption | Onion protocol v2 |
|---|---:|---:|
| Median payload goodput | 3,677.377 Mb/s | 701.647 Mb/s |
| p50 request/response latency | 0.129 ms | 0.316 ms |
| p95 request/response latency | 0.255 ms | 0.454 ms |
| Response integrity | SHA-256 verified | SHA-256 verified |

Observed encrypted goodput is about 19.1% of the plaintext TCP relay baseline in this run. Both reported latency values use 30 probes and both bulk paths use five trials. The benchmarks still differ in their internal write/read behavior, so results are a local engineering indicator—not a clean estimate of pure cryptographic cost. All results are loopback-only; they should not be extrapolated to WAN or compared directly to a live Tor network.

Raw results:

- [`plain-tcp-3-hop-8mb-v2-matched.json`](plain-tcp-3-hop-8mb-v2-matched.json)
- [`onion-3-hop-8mb-v2-matched.json`](onion-3-hop-8mb-v2-matched.json)

Earlier three-trial results are retained in `plain-tcp-3-hop-8mb-v2.json` and `onion-3-hop-8mb-v2.json` for history.

## Security interpretation

Newly tested: AEAD tampering detection, response circuit-ID binding, response sequence validation, request metadata parsing, duplicate circuit-ID rejection, registry-capacity fail-closed behavior, actual relay rejection of a replayed first frame on a new TCP connection, and sequential persistent request/response operation.

Not solved: authenticated ephemeral key agreement, forward secrecy, secure key rotation, a distributed replay-defense protocol, anonymous peer discovery, general streams/multiplexing, cover traffic/mixing, congestion control, or correlation resistance. The relay-local replay registry keeps all observed IDs for the process lifetime, caps at 100,000 entries by default, and fails closed when full. It is only a lab safeguard; public deployment would require a better reviewed design.
