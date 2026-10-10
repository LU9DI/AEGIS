# MALEBOLGE v0.17.0 pipeline benchmark report

## Large workload

- Python 3.13.5, Linux x86-64
- 3-hop IPv4 loopback circuit, echo destination on same host
- 8 streams × 1 MiB, 64 KiB WRITE chunks
- 5 trials for each maximum in-flight depth, order rotated by trial
- All integrity, relay-observability, and cleanup checks passed

| Pipeline depth | Median goodput | Min–max goodput | Median stream p50 | Median stream p95 |
|---:|---:|---:|---:|---:|
| 1 | 234.45 Mb/s | 204.60–242.40 Mb/s | 282.51 ms | 282.78 ms |
| 2 | 220.15 Mb/s | 208.63–235.08 Mb/s | 300.75 ms | 300.79 ms |
| 4 | 237.31 Mb/s | 176.23–240.10 Mb/s | 277.58 ms | 278.29 ms |

Depth 2 was 6.1% slower than depth 1; depth 4 was 1.2% faster. The depth-4
range was also wider. No robust speedup is established.

## Smaller workload

The 3-trial 8 × 256 KiB workload measured medians of 222.56 Mb/s (depth 1),
225.19 Mb/s (depth 2), and 192.91 Mb/s (depth 4), so depth 4 was slower in that
workload. Results are available in `pipeline-depth-v0.17.0.json`.

## Interpretation

The pipeline feature is functionally validated, but the experiment does not
show a repeatable performance advantage yet. Current bottlenecks may include
per-hop Python parsing/AEAD work, serial incoming-frame dispatch, socket drain
behavior, and response handling. The next task should be profiling, not raising
the in-flight limit.

Neither workload predicts WAN speed or supports a comparison to Tor's anonymity
properties. The direct-TCP results are a throughput reference only and do not
provide equivalent privacy.
