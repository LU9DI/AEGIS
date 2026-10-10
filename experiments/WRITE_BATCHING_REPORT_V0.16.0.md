# MALEBOLGE v0.16.0 — three-way write-batching benchmark

## Method

- Three-hop loopback circuit and loopback echo destination.
- Eight concurrent streams; 256 KiB payload per stream; three trials per batch size.
- Compared 16 KiB, 64 KiB and 256 KiB client write commands.
- Trial order rotates across batch sizes; each trial uses a deterministic payload seed.
- Captured integrity, relay-observability and cleanup checks for each run.

## Results

| Write batch | ACKs per 256 KiB stream | Median goodput | Min goodput | Max goodput | Median stream p50 | Median stream p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 16 KiB | 16 | 178.66 Mb/s | 160.92 Mb/s | 184.66 Mb/s | 90.86 ms | 91.50 ms |
| 64 KiB | 4 | 230.15 Mb/s | 219.67 Mb/s | 231.82 Mb/s | 69.52 ms | 69.75 ms |
| 256 KiB | 1 | 246.17 Mb/s | 240.87 Mb/s | 246.83 Mb/s | 63.75 ms | 64.90 ms |

The 256 KiB variant improved median goodput by 37.8% versus 16 KiB and 7.0% versus 64 KiB for this run. All trial integrity, relay-observability and cleanup checks passed.

## Interpretation and limitations

The data supports that fewer acknowledged commands can improve throughput in this workload. It does not prove WAN performance, network-scale fairness, resistance to traffic correlation, Tor parity, or production security. All nodes ran on one host using IPv4 loopback. Direct TCP is not an anonymity-equivalent baseline. Larger writes also increase transient memory per in-flight command; this release keeps one write acknowledgement outstanding per individual stream.

Raw results: [`write-batch-v0.16.0.json`](write-batch-v0.16.0.json).
