# Loopback network-condition testbed — v0.20.0

## Purpose

The new `rea-anon-network-impairment-bench` command measures the experimental three-relay circuit under repeatable, user-space link shaping. It is intended to expose sensitivity to propagation delay, jitter, bandwidth contention, and sparse application writes before running experiments on separate machines.

It is **not** a real WAN emulator and does not prove anonymity, traffic-analysis resistance, or Tor-equivalent security.

## Impairment model

`LinkImpairmentProfile` defines:

- `latency_ms`: one-way propagation delay applied to forwarded TCP-read chunks.
- `jitter_ms`: a deterministic-seed, uniform plus/minus perturbation to each chunk's target arrival time. Delivery order is preserved, because this is a TCP byte stream.
- `bandwidth_mbps`: optional aggregate serialization cap shared by all TCP connections traversing one proxy, separately in each direction.
- `chunk_bytes`: maximum read request made by the proxy; these reads are **not** IP packets and actual `StreamReader.read()` return lengths may vary.
- `queue_chunks`: bounded queue size per connection and direction.
- `max_connections`: proxy admission bound, default 64.

The proxy binds and connects only to literal IPv4 loopback addresses. An admission above `max_connections` is closed and counted as rejected. Queue metrics report the maximum observed queue depth and should not be interpreted as total process memory; transport and Python object overhead is additional. At default limits, queued payload alone is bounded at roughly 32 MiB per proxy (64 connections × 16 queue chunks × 16 KiB × two directions), before StreamReader/StreamWriter buffers and Python object overhead.

## Built-in illustrative profiles

| Profile | One-way delay | Jitter (±) | Aggregate bandwidth per proxy direction |
|---|---:|---:|---:|
| `loopback` | 0 ms | 0 ms | Uncapped |
| `lan` | 0.5 ms | 0.1 ms | 1,000 Mb/s |
| `metro` | 5 ms | 1 ms | 200 Mb/s |
| `intercontinental` | 25 ms | 5 ms | 50 Mb/s |
| `constrained` | 40 ms | 8 ms | 10 Mb/s |

These are synthetic test profiles, not claims about any specific real network.

## Topology and comparison

For circuit measurements, the shaped links are:

1. client → guard;
2. guard → middle relay;
3. middle relay → exit relay;
4. exit relay → destination.

The direct control is one shaped proxy link between the client and the same echo service. This is intentionally a path-length reference, **not** a like-for-like anonymity/performance comparison: the circuit traverses more shaped links and executes additional protocol operations.

The TCP proxy leaves TCP reliability intact. It does not drop IP packets, model retransmissions, congestion-control algorithms, route changes, NAT, wireless interference, or packet reordering. The jitter scheduler preserves byte order.

## v0.20.0 exploratory matrix

Each profile has two repeated runs with two streams × 8 KiB per stream. The sparse case uses the intercontinental profile, two streams × 4 KiB, 512-byte application writes and 1 ms between writes. This is a smoke/research matrix, not enough repetitions for statistical claims.

| Profile | Circuit goodput median | Direct goodput median | Circuit p50 stream latency median | Circuit p95 stream latency median |
|---|---:|---:|---:|---:|
| `loopback` | 35.181 Mb/s | 126.088 Mb/s | 2.766 ms | 3.051 ms |
| `lan` | 4.079 Mb/s | 37.277 Mb/s | 19.691 ms | 22.623 ms |
| `metro` | 0.938 Mb/s | 10.071 Mb/s | 82.068 ms | 93.870 ms |
| `intercontinental` | 0.207 Mb/s | 2.283 Mb/s | 377.340 ms | 429.641 ms |
| `constrained` | 0.098 Mb/s | 1.172 Mb/s | 916.517 ms | 993.602 ms |
| `intercontinental_sparse` | 0.038 Mb/s | 1.012 Mb/s | 1,472.512 ms | 1,516.115 ms |

All tested runs passed integrity, relay-observability, queue-bound, and cleanup checks. The large latency in the high-delay/sparse profile demonstrates that small acknowledged application writes amplify round trips across this experimental circuit. It does not predict exact performance on the Internet, because delay is applied to user-space stream chunks, not IP packets.

Raw per-trial records are in `experiments/network-condition-matrix-v0.20.0.json`; summary data are in `experiments/network-condition-summary-v0.20.0.json`.

## Reproduce

```bash
python -m pip install -e '.[onion-lab]'
rea-anon-network-impairment-bench --profile metro --streams 2 --payload-bytes 8192 --output experiments/metro.json
rea-anon-network-impairment-bench --profile intercontinental --streams 2 --payload-bytes 4096 --sparse-gap-ms 1 --sparse-chunk-bytes 512 --output experiments/intercontinental-sparse.json
```

## Security scope

This proxy and protocol are for isolated localhost research only. Do not bind to a public interface. The proxy models delay/jitter/rate, not packet loss. The circuit implementation remains custom and unaudited; the exit sees the destination and application plaintext, and adjacent relays can observe timing, sizes, and link-local identifiers.
