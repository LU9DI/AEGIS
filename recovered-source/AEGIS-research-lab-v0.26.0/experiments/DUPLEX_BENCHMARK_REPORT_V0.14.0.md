# Full-duplex stream benchmark — MALEBOLGE v0.14.0

## Method

Three trials were run on the same Linux x86-64 host with Python 3.13.5. Each trial opened one three-relay circuit and measured eight continuous TCP streams, each carrying 65,536 useful bytes through the encrypted MALEBOLGE circuit, then repeated the same eight payloads over direct TCP to the exact same loopback echo destination. All streams half-closed the client-to-destination direction, read until EOF, and compared the received bytes with the sent payload. Trial seeds: `20261009`, `20261010`, `20261011`.

This is a microbenchmark and direct TCP is not an anonymity-equivalent comparison. The run uses one host and loopback sockets; it has no WAN delay, loss, NAT, congestion, or adversarial relay behavior.

## Results

| Metric | Median of 3 trials | Min | Max |
|---|---:|---:|---:|
| Duplex circuit useful-payload goodput | 130.56 Mb/s | 116.61 Mb/s | 136.96 Mb/s |
| Duplex stream latency p50 | 28.14 ms | — | — |
| Duplex stream latency p95 | 29.22 ms | — | — |
| Direct TCP useful-payload goodput | 2,324.10 Mb/s | — | — |
| Direct stream latency p50 | 1.52 ms | — | — |

All three trials passed payload integrity and relay-observability checks. Every trial ended with zero active client streams and `[0, 0, 0]` active relay connections. The median duplex throughput is about **5.6%** of direct TCP in this test, a substantial performance gap. The implementation validates the mechanics of continuous bidirectional streaming and bounded read credit, not a performance breakthrough.

## Interpretation and next bottlenecks

1. Each write waits for a per-chunk acknowledgement.
2. Every consumed read chunk waits for a credit-update acknowledgement.
3. All commands share one per-circuit send lock and a single response dispatcher, so independent streams can interfere with each other.
4. Relay crypto/framing and Python scheduling add overhead not present in direct TCP.

The next optimization should batch writes and window grants without allowing unbounded in-flight data, then test per-stream fairness and head-of-line blocking. We should not optimize by removing authentication, sequence checks, or the credit bound.

## Limitations

The protocol is custom and unaudited, not Tor-compatible, and not safe for sensitive traffic. The exit sees the destination and clear application bytes; adjacent relays see traffic timing, sizes, and link-local IDs. No conclusion about anonymity, resistance to global traffic correlation, or performance over the public Internet can be inferred.
