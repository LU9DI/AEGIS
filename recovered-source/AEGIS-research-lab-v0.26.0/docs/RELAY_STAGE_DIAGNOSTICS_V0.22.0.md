# Relay-stage diagnostics (v0.22.0)

## Purpose

The mixed-workload benchmark can now enable optional, bounded timings on each relay. The instrumentation is off by default on `RelayNode` and is enabled only by the research benchmark. Each relay keeps at most 8,192 metric events; older events are dropped and counted.

## Recorded stages

- `command_dispatch`: time spent handling a decoded command in the relay loop, plus the operation category (`extend`, `forward`, `open_stream`, `write`, `window_update`, and related control commands).
- `downstream_response_wait`: wait for the downstream relay's correlated response; this is not a TCP ACK measurement.
- `relay_reply_send` and `relay_event_send`: local response/event framing, lock acquisition, socket write, and `drain()` time.
- `destination_read_wait`: time awaiting bytes from the local echo destination.
- `destination_write_drain`: time awaiting the exit relay's destination writer to drain after a `WRITE`.
- `flow_credit_wait`: time waiting for available stream read credit before requesting more destination bytes.

Snapshots report sample count, median, p95, and summed elapsed time. Command counts are grouped by operation. A flow-control summary separately counts waits of at least 1 ms and their aggregate duration; this threshold is a diagnostic convention, not a protocol limit. Event records contain only stage names, operation categories, and durations; they do not retain payload bytes, stream IDs, relay IDs, destination addresses, or other application contents. Timing and operation categories can still disclose traffic behavior and should be treated as diagnostic metadata.

## Reproduce

```bash
PYTHONPATH=src python -m anonlab.mixed_workload_benchmark \
  --profile metro \
  --trials 3 \
  --bulk-bytes 262144 \
  --interactive-requests 8 \
  --stagger-after-ms 20 \
  --output experiments/mixed-workload-relay-diagnostics.json
```

The JSON includes a `relay_stage_diagnostics` list indexed by circuit hop. The comparison alternates scheduler execution order and uses matching seeds per trial, but a small sample is exploratory only. Instrumentation adds overhead; use it to locate candidate bottlenecks, not as an uninstrumented performance benchmark.

## Interpretation cautions

`downstream_response_wait` includes the downstream path and remote processing as observed by the current relay. `destination_read_wait` includes waiting for the application destination to provide data, so a large value can simply mean the echo endpoint is waiting for the client to write. `flow_credit_wait` is a flow-control pause only when it lasts materially longer than the immediate condition check; the raw aggregate includes short checks too. These timings do not prove relay saturation, WAN behavior, traffic-analysis resistance, or anonymity.
