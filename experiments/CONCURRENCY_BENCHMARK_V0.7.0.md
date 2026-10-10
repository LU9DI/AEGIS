# MALEBOLGE concurrent circuit benchmark — v0.7.0

**Status: local microbenchmark only. Not a WAN benchmark, anonymity test, or security audit.**

## Method

The benchmark opens independent three-relay circuits concurrently. Every client socket connects directly only to the guard; the guard and middle relay extend downstream. Each circuit sends one framed echo payload through the exit. The same deterministic payload set is then echoed using concurrent direct loopback TCP requests. The benchmark checks byte-for-byte integrity, the parsed-command destination visibility boundary, one client-to-guard connection per circuit, and zero active relay handlers after clients close.

- Environment: Linux x86-64, Python 3.13.5.
- Relay and echo sockets: IPv4 loopback, same process and host.
- Default relay active-connection admission limit: 64.
- Circuit length: three relays.
- `goodput` is total useful response payload bits divided by wall-clock time for all concurrent responses. It is not wire throughput and does not include padding/cover traffic.

## Results

| Metric | 8 clients, 65,536 bytes/client | 32 clients, 16,384 bytes/client | 64 clients, 4,096 bytes/client |
|---|---:|---:|
| Concurrent circuit build wall time | 12.289 ms | 131.424 ms | 174.329 ms |
| Circuit-build latency p50 | 11.704 ms | 129.246 ms | 168.063 ms |
| Circuit echo RTT p50 | 20.027 ms | 24.605 ms | 40.360 ms |
| Circuit echo RTT p95 | 20.402 ms | 24.835 ms | 40.802 ms |
| Aggregate circuit response goodput | 199.36 Mb/s | 159.48 Mb/s | 49.18 Mb/s |
| Direct echo RTT p50 / p95 | 1.058 / 1.174 ms | 3.235 / 3.444 ms | 7.969 / 8.725 ms |
| Aggregate direct response goodput | 3,213.89 Mb/s | 1,064.07 Mb/s | 209.61 Mb/s |
| Integrity verified | Yes | Yes |
| Route-knowledge parsed-command check | Passed | Passed |
| Active handlers after teardown | 0 / 0 / 0 | 0 / 0 / 0 |

The columns use different client counts and payload sizes and should not be interpreted as a controlled scaling curve. The 64-client case reached the configured active-connection cap without loss of test integrity. The results show only that the local implementation handles concurrent circuits and cleans up admitted handler state for these runs; the lower aggregate than direct TCP includes Python task scheduling, three separate relay handlers, multiple AEAD operations and framing.

## Raw data and reproduction

- [`concurrency-benchmark-v0.7.0.json`](concurrency-benchmark-v0.7.0.json)
- [`concurrency-benchmark-32clients-v0.7.0.json`](concurrency-benchmark-32clients-v0.7.0.json)
- [`concurrency-benchmark-64clients-v0.7.0.json`](concurrency-benchmark-64clients-v0.7.0.json)

```bash
PYTHONPATH=src python -m anonlab.concurrency_benchmark --clients 8 --bytes 65536 --seed 20261009 --output experiments/concurrency-benchmark-v0.7.0.json
PYTHONPATH=src python -m anonlab.concurrency_benchmark --clients 32 --bytes 16384 --seed 20261009 --output experiments/concurrency-benchmark-32clients-v0.7.0.json
PYTHONPATH=src python -m anonlab.concurrency_benchmark --clients 64 --bytes 4096 --seed 20261009 --output experiments/concurrency-benchmark-64clients-v0.7.0.json
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Security limitations

Relay and echo sockets remain loopback-only. Descriptors are caller-pinned rather than signed/rotatable. The MALEBOLGE-specific key derivation is unaudited. Connection counts and command budgets are coarse lab safeguards, not a complete denial-of-service design. Timing and packet-size correlation, collusion, Internet routing, censorship and application stream behavior are not tested. Do not expose this harness publicly or use it for sensitive traffic.
