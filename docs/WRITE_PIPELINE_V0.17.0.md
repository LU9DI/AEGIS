# MALEBOLGE v0.17.0 — bounded acknowledged WRITE pipelining

## Goal

The v0.16 transport acknowledged each `WRITE` before the client sent the next
one. v0.17 adds a bounded API that queues several `WRITE` commands in order,
then waits for each individually authenticated acknowledgement. This tests
whether reducing stop-and-wait behavior matters on the local testbed.

## API

`DuplexCircuitStream.write_pipelined(data, chunk_bytes=64*1024, max_in_flight=4)`
accepts 1 byte to 4 MiB of caller data, uses command chunks of 1 byte to 256 KiB,
and limits each client batch to 1–4 outstanding commands. Each call is limited to
512 WRITE commands to avoid pathological one-byte chunking. The default chunk is
64 KiB and the default pipeline depth is four.

The client reserves each hop's monotonically increasing command sequence under
the circuit send lock, registers all response correlation futures, serializes the
frames in sequence order, writes the entire bounded batch, and calls `drain()`
once. Each relay still validates incoming per-hop sequence numbers. Relay
handlers queue downstream frames in order but wait for each downstream write ACK
in a tracked task. The exit schedules `drain()` and the ACK separately after
synchronously enqueuing payload bytes to the destination `StreamWriter`.
Responses are correlated by sequence and per-hop stream ID, so ACK frames can
complete independently without confusing streams.

## Bounds and control ordering

- Maximum pipeline depth: 4 commands per stream.
- Maximum application write command: 256 KiB.
- Maximum payload passed to a single `write_pipelined` call: 4 MiB.
- Maximum WRITE commands in one `write_pipelined` call: 512.
- Relay limit: at most 4 in-flight write commands and 2 MiB accounted pending
  write bytes per stream, plus a 16 MiB aggregate pending-write budget per
  circuit connection.
- `HALF_CLOSE` and `CLOSE` cannot overtake pending writes. On the client, they
  share the stream's write lock with pipeline operations. Each relay also rejects
  control messages that arrive while writes for that stream remain pending.
- The pending-byte accounting uses payload bytes at the exit and encrypted
  packet bytes at intermediate relays. It is an admission limit, not an exact
  bound on total Python, AEAD, socket, or kernel memory.
- Relays fail the connection closed if a queued write cannot be acknowledged.

## Benchmark results

Command:

```bash
rea-anon-pipeline-bench --trials 5 --streams 8 \
  --payload-bytes 1048576 --chunk-bytes 65536 \
  --output experiments/pipeline-depth-1mib-5trials-v0.17.0.json
```

The testbed uses three relays plus an echo destination on IPv4 loopback. With
8 streams × 1 MiB per stream, 64 KiB chunks, five trials per depth and rotating
run order, median useful goodput was:

| Maximum in-flight WRITE commands | Median goodput | Median per-stream p50 |
|---:|---:|---:|
| 1 (stop-and-wait) | 234.45 Mb/s | 282.51 ms |
| 2 | 220.15 Mb/s | 300.75 ms |
| 4 | 237.31 Mb/s | 277.58 ms |

All 15 trials passed integrity, relay-observability, and resource-cleanup
checks. Depth 4 was only 1.2% above depth 1, while depth 2 was 6.1% below it;
per-trial variability was substantial. A shorter 256 KiB workload showed a
slightly different pattern. These measurements therefore **do not demonstrate
a robust performance win from pipelining yet**. They show that the pipeline is
functional and give us a baseline for profiling and more representative tests.

Raw records are in `experiments/pipeline-depth-1mib-5trials-v0.17.0.json` and
`experiments/pipeline-depth-v0.17.0.json`.

## Limitations

This is a custom, unaudited, loopback-only protocol—not Tor-compatible and not
safe for sensitive or production traffic. TCP-direct comparisons are not
anonymity-equivalent. No WAN loss, variable RTT, congestion, fairness, global
observer, traffic-correlation, or independent crypto-audit claims are made.
