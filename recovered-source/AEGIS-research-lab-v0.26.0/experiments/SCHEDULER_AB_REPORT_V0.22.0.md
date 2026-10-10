# Round-robin scheduler A/B report — v0.22.0

## Setup

- Three relay circuit, destination and four user-space shapers run on one host over IPv4 loopback.
- Profile: `metro`; 5 ms modeled one-way delay, ±1 ms jitter, 200 Mb/s aggregate rate per shaper direction.
- Workload: 2, 4 or 8 streams, 256 KiB per stream, 64 KiB writes, pipeline depth 4.
- Three trials per mode/count, with condition order rotated between trials. Every run checked data integrity, relay observability, relay connection closure and all four proxies returning to zero active connections.
- Two modes differed only in client dispatch: baseline batch dispatcher versus opt-in round-robin scheduler.

## Median results

| Streams | Scheduler | Goodput median (Mb/s) | Jain completion index | p50 per-stream latency (ms) | p95 per-stream latency (ms) |
|---:|---|---:|---:|---:|---:|
| 2 | Baseline | 10.541 | 0.9893 | 325.2 | 355.4 |
| 2 | Round-robin | 11.012 | 0.9985 | 321.6 | 333.9 |
| 4 | Baseline | 12.394 | 0.9882 | 552.0 | 618.4 |
| 4 | Round-robin | 11.288 | 0.9918 | 597.5 | 675.0 |
| 8 | Baseline | 12.249 | 0.9851 | 1053.2 | 1284.2 |
| 8 | Round-robin | 12.073 | 0.9873 | 1140.6 | 1322.2 |

## Median deltas for round-robin vs baseline

| Streams | Goodput delta | Jain-index delta | p95 latency delta |
|---:|---:|---:|---:|
| 2 | +4.47% | +0.0092 | -6.03% |
| 4 | -8.93% | +0.0036 | +9.14% |
| 8 | -1.44% | +0.0022 | +2.96% |

## Interpretation

Round-robin improves the finite-transfer Jain index in all three counts, but only slightly at 4 and 8 streams. Throughput and tail latency trade off: the 2-stream case improves, whereas the 4-stream case is slower and has higher p95 latency; 8 streams also show small losses in throughput and p95. These results do **not** establish a robust overall improvement. The scheduler is therefore opt-in, and the previous dispatcher remains the default.

## Limitations

- These are finite transfers, not long-lived flows; Jain's index is an exploratory completion-rate proxy.
- All relay/proxy/destination processes are local. This is not a WAN measurement and user-space byte-stream shaping does not simulate packet loss or TCP retransmissions.
- The direct-TCP path is not an anonymity-equivalent baseline.
- The protocol and scheduler remain custom and unaudited.

Raw runs and rotated order are stored in `scheduler-ab-v0.22.0.json`.
