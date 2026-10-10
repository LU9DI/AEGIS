# Write-stage diagnostics — MALEBOLGE v0.22.0

Date: 2026-10-09

## Objective

The mixed-workload A/B matrix did not show a stable latency advantage for the optional round-robin scheduler. This run adds bounded, payload-free instrumentation to distinguish client-side queueing and frame preparation from time spent waiting for the echoed stream response.

Instrumentation is disabled by default in `TelescopingClient`; the research benchmark enables it explicitly. Captured events hold timings, command counts, and byte counts only—not payload bytes, destination addresses, or relay identities. The event trace is bounded to 4,096 records per client.

## Completed run

- Four configurations; two trials per scheduler per configuration; 16 total scheduler runs.
- All runs passed data integrity, relay observability, and resource-cleanup checks.
- All delayed interactive streams started while bulk transfer was still active.
- Full test suites passed after instrumentation: `unittest` reported 147 tests passed with `ResourceWarning` treated as an error; `pytest` reported 149 passed plus 11 subtests passed.

## Stage timing summary

All values below are medians over instrumented operations. The samples within a run are correlated, and there were only two paired runs per configuration; use the numbers as diagnostic indications, not confidence estimates.

| Scenario | Baseline response-wait (ms) | Round-robin response-wait (ms) | RR queue-wait median (ms) | RR frame preparation (ms) | RR socket drain (ms) |
|---|---:|---:|---:|---:|---:|
| loopback / pipeline 1 / 256 KiB | 0.9695 | 0.9308 | 0.0449 | 0.0419 | 0.0008 |
| metro / pipeline 1 / 256 KiB | 43.9295 | 42.4504 | 0.0325 | 0.0552 | 0.0013 |
| metro / pipeline 4 / 256 KiB | 48.0739 | 49.3964 | 0.0269 | 0.0700 | 0.0014 |
| metro / pipeline 4 / 1024 KiB | 55.5647 | 53.8185 | 0.0302 | 0.0655 | 0.0013 |

## What the measurements suggest

On the shaped `metro` cases, the median round-robin queue wait is approximately 0.027–0.033 ms per dispatch round, frame preparation is approximately 0.055–0.070 ms, and local socket `drain()` is approximately 0.001–0.0014 ms. The end-to-end wait for the echoed stream response is approximately 42–55 ms. Thus the observed response latency is orders of magnitude larger than the measured client queue wait. This makes queue tuning an unlikely primary fix for the current latency results.

`response_wait_ms` is the time waiting for the application-level stream response to return through the circuit and shaped proxies. It is **not** a raw TCP ACK timer, and it includes destination/relay processing and the configured path delay. The trace distinguishes broad stages; it does not yet split time spent inside each relay.

Round-robin still does not show a consistent performance win in the prior three-trial aggregate matrix. These stage measurements are consistent with keeping it opt-in rather than changing defaults.

## Next technical priority

Instrument per-relay forwarding and control-command counts (without recording payloads) to separate configured delay, relay forwarding time, flow-control pauses, and round-trip amplification. If most response wait is attributable to the shaper and protocol round trips, focus on pipeline/control protocol behavior rather than changing the write queue scheduler.

## Reproduction

```sh
PYTHONPATH=src python -W error::ResourceWarning -m anonlab.mixed_workload_matrix \
  --trials 2 --seed 20261028 --interactive-requests 3 \
  --request-bytes 128 --request-gap-ms 2 --stagger-after-ms 20 \
  --output experiments/write-stage-diagnostics-v0.22.0.json
```

## Limitations

- All relays, proxies and destination run on one host via IPv4 loopback.
- The shaping proxy operates on TCP byte streams; it is not a packet-loss, retransmission, routing-change or real-WAN emulator.
- Timings are instrumented and therefore incur some overhead; they should not be compared directly with earlier uninstrumented throughput runs.
- Only two trials per configuration were completed. The test does not establish statistically significant scheduler superiority, steady-state fairness, anonymity, resistance to global observation or production security.
- MALEBOLGE remains an experimental research lab and has not received an independent cryptographic audit.
