# MALEBOLGE v0.15.0 — paired write-batching benchmark

## Method

The benchmark compared **16 KiB** and **64 KiB** client-to-destination write batches on the same three-relay IPv4-loopback circuit implementation. Both scenarios used 8 concurrent streams, 65,536 useful bytes per stream, and 5 trials per batch size. Execution order alternated per trial, and both variants used the same per-trial seed/payload. The test measures a custom Python research transport on one host; it is not a Tor comparison and does not test anonymity.

## Results

| Metric | 16 KiB batches | 64 KiB batches | Change (64 KiB vs 16 KiB) |
|---|---:|---:|---:|
| Median useful throughput | 152.46 Mb/s | 193.71 Mb/s | +27.1% |
| Lowest trial throughput | 137.48 Mb/s | 159.45 Mb/s | — |
| Highest trial throughput | 155.40 Mb/s | 203.00 Mb/s | — |
| Median p50 stream latency | 24.74 ms | 17.80 ms | — |
| Median p95 stream latency | 25.12 ms | 18.43 ms | — |
| Write acknowledgements per 64 KiB | 4 | 1 | 75% fewer |

All payload-integrity checks: **True**. All relay-observability checks: **True**. All stream/connection cleanup checks: **True**.

## Interpretation

The 64 KiB batch median was 1.271× the 16 KiB batch median (+27.1%) in this five-trial, same-host comparison. This is a useful local result: it supports that reducing acknowledged write commands can improve throughput for this workload. It is **not** evidence of equivalent gains on WAN links, of fairness between streams, or of anonymity. Direct TCP results are included in each trial for context, but direct TCP is not an anonymity-equivalent baseline and varied with trial timing.

The write payload cap is now 64 KiB; response events remain at 16 KiB and the initial per-stream read-credit window remains 64 KiB. Larger commands require more transient memory per in-flight command, so this limit remains explicit. No new cryptographic properties are claimed.

## Reproduction

From the source checkout (with the optional `cryptography` dependency installed):

```bash
PYTHONPATH=src python -m anonlab.write_batch_benchmark \
  --trials 5 --streams 8 --payload-bytes 65536 \
  --seed 20261009 --output experiments/write-batch-v0.15.0.json
```

Raw results: [`write-batch-v0.15.0.json`](write-batch-v0.15.0.json).
