# MALEBOLGE v0.22.0 — experimental fair write scheduler

## Purpose

The v0.21.0 completion-rate matrix suggested more competition at higher stream counts. v0.22.0 adds an **opt-in** client-side round-robin scheduler to test whether dispatching a WRITE from each ready stream before returning to the same stream improves service distribution.

## Behavior

- Default mode remains the previous batch dispatcher: `TelescopingClient(fair_write_scheduling=False)`.
- Experimental mode is enabled with `TelescopingClient(fair_write_scheduling=True)` or `--fair-write-scheduling` on the impairment benchmark.
- Each logical stream has a FIFO queue. The scheduler picks one pending WRITE from each ready stream in round-robin order, then may continue another round until it has selected at most 32 commands to send in one writer-drain batch.
- Pending work is bounded at 512 commands and 8 MiB across queued and dispatching requests. Admission above either limit fails before sending frames and does not by itself poison the circuit.
- The bounded diagnostic trace records ephemeral logical stream IDs only; no payloads, destinations, or plaintext are captured.
- Per-hop command sequence allocation and AEAD framing occur only when a scheduled job is dispatched under the circuit send lock, so wire sequence order follows the actual write order.
- An exception after frame construction fails closed because some bytes may already be buffered in the socket and continuing could desynchronize the circuit.

## A/B result

Run `rea-anon-scheduler-bench --profile metro --stream-counts 2,4,8 --trials 3 --payload-bytes 262144 --write-chunk-bytes 65536 --pipeline-depth 4`. The checked-in report includes run-order rotation, raw per-run measurements and cleanup assertions.

The 3-trial result showed small positive Jain-index deltas, but no consistent throughput or tail-latency advantage. Therefore, round-robin remains opt-in and must not be described as a proved fairness fix.

## Limits

This is a client-side lab scheduler; it is not a production congestion controller or an end-to-end per-circuit fairness proof. Measurements use IPv4 loopback plus user-space shaping and do not simulate IP packet loss. A reviewer should specifically inspect cancellation during dispatch, command sequence ordering, memory accounting and the interaction with HALF_CLOSE/CLOSE.
