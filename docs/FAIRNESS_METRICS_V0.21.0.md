# Stream fairness measurements — v0.21.0

## Purpose

The v0.21.0 fairness experiment measures whether equal-sized finite streams complete at similar rates when they share a three-relay MALEBOLGE test circuit. It records per-stream completion duration and the Jain index over per-stream completion-goodput estimates.

This is a **diagnostic proxy**, not a proof of steady-state fairness, max-min fairness, production congestion control, or fairness for heterogeneous and long-lived flows. Completion times include circuit application work, relay scheduling, buffering, flow-control windows, startup, and teardown.

## Method

- Topology: client → shaped guard → shaped middle → shaped exit → shaped echo destination.
- All relays and shapers run on IPv4 loopback on one host.
- Profile: `metro` (5 ms one-way configured delay per proxy, ±1 ms deterministic-seed jitter, 200 Mb/s aggregate per direction per proxy).
- Payload: 32 KiB per stream, identical size per stream.
- Stream counts: 1, 2, 4, and 8.
- Trials: 3 per stream count; order rotates per trial to reduce simple order bias.
- Seed: 20261021 base seed; each run derives a distinct deterministic seed.
- Every run checks payload integrity, expected relay observations, relay cleanup and zero active proxy connections.

The direct TCP control is included for diagnostic context only. It uses a different path length and provides no equivalent anonymity guarantee.

## Results

Median results across three repetitions for each stream count:

| Streams | Circuit goodput median (Mb/s) | Circuit Jain completion-rate index | Circuit latency p50 median (ms) | Circuit latency p95 median (ms) | Direct Jain completion-rate index |
|---:|---:|---:|---:|---:|---:|
| 1 | 2.378 | 1.000 | 76.725 | 76.725 | 1.000 |
| 2 | 3.722 | 0.981 | 84.515 | 95.231 | 0.999 |
| 4 | 3.812 | 0.881 | 110.981 | 229.142 | 0.986 |
| 8 | 4.907 | 0.857 | 161.971 | 242.811 | 0.973 |

All 12 runs passed the integrity, relay-observability and cleanup checks. Raw results and per-stream records are in `experiments/fairness-matrix-metro-v0.21.0.json`.

## Interpretation

Aggregate useful goodput increased with more streams but not proportionally. The completion-rate Jain index declined at 4 and 8 streams, indicating different completion rates across streams under this particular finite workload. This points to an area for further investigation: command scheduling and shared circuit coordination, not just link capacity.

Do not interpret this as proof that the protocol is intrinsically unfair. The index is affected by finite payload timing and startup/teardown, and the experiment has only three repetitions per condition. A follow-up should collect more repetitions, compare per-stream timeseries, and profile queue wait/command lock wait before modifying the scheduler.

## Limitations

- User-space proxies shape TCP byte-stream reads, not IP packets.
- No packet loss, retransmission behavior, routing changes, NAT, wireless interference or real WAN is modeled.
- A shared loopback host does not model independent operators or machine contention in a distributed deployment.
- The custom protocol remains experimental and unaudited.
- The Jain index is calculated from per-stream finite-transfer completion-goodput estimates; it is not a steady-state fairness guarantee.
