# MALEBOLGE v0.19.0 — coalesced read-window credit updates

## Change

`DuplexCircuitStream.read_chunk()` now accumulates application-consumed bytes in `_pending_window_credit`. The client sends an authenticated `WINDOW_UPDATE` when the configured threshold is reached; the default is 64 KiB. If the application has exhausted the currently buffered data while credits remain below the threshold, the client waits at most 2 ms for another data/EOF event before flushing the partial credit. This timeout is intended to prevent sparse streams from stalling while allowing fast streams to combine updates.

A window update body is a 32-bit byte count and can grant 1..256 KiB. The exit relay still enforces `read_credit + amount <= MAX_STREAM_WINDOW_BYTES`; the client threshold is not permission to exceed the receive-window maximum. The default threshold is 64 KiB; tests and the duplex benchmark can select lower thresholds for paired experiments.

Unused pending credit is discarded at EOF or stream close because the destination can no longer send additional bytes. On a failed update, the enclosing stream/circuit operation fails; the amount is reserved locally before the awaited command so it cannot be counted twice.

## Benchmark methodology

The benchmark uses three relays, an echo destination and all TCP sockets on IPv4 loopback within one host. The eight streams are run concurrently, the same seeds are used per trial index, and the three credit thresholds are interleaved in randomized order. Each configuration has five trials. The benchmark records useful goodput, per-stream latency, update-command count, data integrity, relay-observability and cleanup results.

### 8 streams × 256 KiB per stream

| Credit batch threshold | Median goodput | Range | Median p50 per stream | Median p95 per stream | Median update commands |
|---:|---:|---:|---:|---:|---:|
| 1 byte (flush each consumed chunk) | 330.34 Mb/s | 314.99–358.12 Mb/s | 46.78 ms | 47.11 ms | 104 |
| 32 KiB | 412.80 Mb/s | 386.33–431.27 Mb/s | 36.94 ms | 37.52 ms | 56 |
| 64 KiB (default) | 493.27 Mb/s | 472.35–505.02 Mb/s | 30.03 ms | 30.76 ms | 32 |

For this workload, 64 KiB batching was 49.3% above immediate credit updates and 19.5% above 32 KiB batching. Median update count fell 69.2% vs immediate updates. All integrity, relay-observability and cleanup checks passed for all 15 runs.

### 8 streams × 64 KiB per stream

| Credit batch threshold | Median goodput | Range | Median p50 per stream | Median update commands |
|---:|---:|---:|---:|---:|
| 1 byte | 320.70 Mb/s | 288.77–338.29 Mb/s | 10.54 ms | 8 |
| 32 KiB | 310.25 Mb/s | 277.43–347.92 Mb/s | 10.74 ms | 8 |
| 64 KiB | 329.78 Mb/s | 305.76–344.07 Mb/s | 9.97 ms | 8 |

The smaller workload did not reduce the number of updates; streams can observe EOF before a pending batch would be useful, and EOF safely discards unneeded credit. No robust throughput gain is claimed for this smaller case.

## Interpretation and limits

The larger workload supports the hypothesis that fewer control round trips can improve this implementation's local throughput. The result does not show that the same percentages transfer to the Internet: all relays and the echo endpoint share one process/host, and there is no WAN delay, packet loss or independent relay operator. The timer adds up to 2 ms before a below-threshold credit update is sent when a stream is waiting for data; interactive and sparse traffic need separate measurements.

The exit relay still sees the cleartext application stream and target destination. Adjacent relays can observe link timing, sizes, directions and hop-local stream IDs. This is a custom, unaudited research protocol; the change makes no Tor compatibility, global-observer anonymity, or production security claim.

## Reproduction

```bash
rea-anon-duplex-bench --streams 8 --payload-bytes 262144 --write-chunk-bytes 262144 --pipeline-depth 1 --window-update-batch-bytes 1 --output experiments/window-update-batching-v0.19.0-immediate.json
rea-anon-duplex-bench --streams 8 --payload-bytes 262144 --write-chunk-bytes 262144 --pipeline-depth 1 --window-update-batch-bytes 32768 --output experiments/window-update-batching-v0.19.0-32k.json
rea-anon-duplex-bench --streams 8 --payload-bytes 262144 --write-chunk-bytes 262144 --pipeline-depth 1 --window-update-batch-bytes 65536 --output experiments/window-update-batching-v0.19.0-64k.json
```

The raw randomized five-trial comparison is stored at `experiments/window-update-batching-v0.19.0.json`; the smaller workload is at `experiments/window-update-batching-small-v0.19.0.json`.
