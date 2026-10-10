# Stream multiplexing report — MALEBOLGE v0.13.0

## Setup

- Python: 3.13.5
- Platform: Linux x86-64
- Three relays and an echo destination all on `127.0.0.1`
- One persistent three-hop circuit
- 16 simultaneous one-shot streams, 4,096 payload bytes each
- Seed: `20261009`
- Comparison baseline: the same client and circuit using serial `request_echo()` calls

Raw data: [`stream-multiplex-v0.13.0.json`](stream-multiplex-v0.13.0.json).

## Results

| Metric | Multiplexed | Serial baseline |
|---|---:|---:|
| Useful payload bytes per round | 65,536 | 65,536 |
| p50 per-stream/request latency | 8.751 ms | 0.566 ms |
| p95 per-stream/request latency | 8.922 ms | 0.720 ms |
| Total round time | 9.273 ms | 9.566 ms |
| Aggregate useful goodput | 56.539 Mb/s | 54.808 Mb/s |

Circuit construction measured 2.701 ms. The run passed payload-integrity and route-observation checks. It used one direct client-to-guard connection; after close, all three relay active-connection counters were zero, and no active streams remained before close.

## Interpretation

On this host, multiplexing improved aggregate goodput by only about 3.2% for this small workload while increasing per-stream p50 substantially. The benchmark is a smoke experiment with no statistical confidence interval; it should not be extrapolated to WAN conditions. The high per-stream latency includes queueing and scheduling behavior in the current client and relays. It shows that the feature functions, not that MALEBOLGE is already faster than a serial circuit, Tor, or a direct connection.

## Next measurement step

Repeat multiple trials over a matrix of stream counts (1, 4, 16, 32, 64), payload sizes (1 KiB, 16 KiB, 256 KiB), and per-stream service delays. Report median and tail latency distributions, CPU time, memory and bytes of framing/metadata. Compare only matched workloads, then profile the response dispatcher and per-relay send locks. Keep all hosts loopback-only until the protocol is reviewed.
