# Mixed-workload benchmark — MALEBOLGE v0.22.0 worktree

Date: 2026-10-09

## Purpose

The equal-sized-flow benchmark did not answer whether a client write scheduler protects short interactive work while a bulk stream is active. This benchmark runs three streams on one authenticated three-hop circuit:

1. A finite bulk echo transfer.
2. An interactive flow that sends short request/response messages.
3. A second interactive flow that opens after a delay while the bulk transfer is expected to remain active.

Metrics include bulk time-to-first-byte, aggregate finite-flow goodput and completion time; first interactive response RTT; interactive request RTT p50/p95 and completion time; byte-integrity; exit-relay observability; and resource teardown. Interactive RTT is measured from immediately before a request write through receipt of the corresponding echo bytes, excluding circuit setup and stream-open time.

## Reproduce

From the project root:

```sh
PYTHONPATH=src python -m anonlab.mixed_workload_benchmark \
  --profile metro --trials 5 --bulk-bytes 262144 \
  --interactive-requests 5 --request-bytes 128 \
  --request-gap-ms 5 --stagger-after-ms 20 \
  --write-chunk-bytes 16384 --pipeline-depth 4 \
  --seed 20261023 --output experiments/mixed-workload-ab-v0.22.0.json
```

The comparison runs baseline and optional round-robin modes per trial, uses the same deterministic shaping seed for both modes within a trial, and alternates condition order. The raw per-run values matter more than the summary medians at this sample size.

## Current experiment

Configuration: `metro` user-space shaper; 5 trials per mode; 256 KiB bulk stream; 5 interactive requests of 128 bytes per interactive flow; 5 ms request gap; late stream starts 20 ms after bulk begins; 16 KiB write chunks; pipeline depth 4.

Raw data: `experiments/mixed-workload-ab-paired-v0.22.0.json` (also distributed separately as `MALEBOLGE-v0.22.0-mixed-workload-ab-paired.json`).

| Metric (median) | Baseline | Round-robin | RR delta |
|---|---:|---:|---:|
| Bulk goodput (Mbps) | 6.245 | 5.442 | -12.85% |
| Bulk time-to-first-byte (ms) | 55.752 | 55.278 | -0.85% |
| Bulk completion (ms) | 335.802 | 385.333 | +14.75% |
| Early interactive request RTT p50 (ms) | 98.666 | 99.906 | +1.26% |
| Early interactive request RTT p95 (ms) | 109.689 | 107.808 | -1.72% |
| Late interactive request RTT p50 (ms) | 85.677 | 84.993 | -0.80% |
| Late interactive request RTT p95 (ms) | 123.043 | 126.160 | +2.53% |

Integrity, relay-observability and resource-cleanup checks passed in all 10 runs. Every late flow began while the bulk stream was still active.

## Interpretation and decision

This five-trial sample does not show a robust interactive-latency benefit from round-robin scheduling. Some median interactive measures improve slightly while others regress; bulk goodput drops 12.85% and median bulk completion takes 14.75% longer in this run. Do **not** change the default scheduler. Keep round-robin opt-in and gather more trials or varied payload sizes before drawing stronger conclusions.

## Limits

All components execute on one host using IPv4 loopback. The proxy shapes TCP byte-stream chunks; it does not model IP loss, TCP retransmission dynamics, routing changes, or a real WAN. The flows are finite, and this is neither a steady-state fairness proof nor a production congestion-control/security evaluation. MALEBOLGE remains experimental and has not been independently cryptographically audited.
