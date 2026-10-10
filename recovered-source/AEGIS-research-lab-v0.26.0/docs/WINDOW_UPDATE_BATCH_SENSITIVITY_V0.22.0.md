# WINDOW_UPDATE batch sensitivity — MALEBOLGE v0.22.0

## Objective

Test whether changing the consumed-byte credit batching threshold improves mixed bulk/interactive traffic while keeping the default write scheduler and the 2 ms sub-threshold flush timer fixed. The control is the current 64 KiB threshold.

## Method

- Four thresholds: 16, 32, 64 and 128 KiB.
- Three trials per threshold (12 runs total), with rotated threshold order and the same configured shaper seed across candidates within each trial.
- Profile: `metro`; bulk payload: 256 KiB; five interactive requests per interactive flow; 128-byte request payload; 5 ms gap; late flow stagger at 20 ms; write chunk 16 KiB; pipeline depth 4.
- Default write scheduler held constant (`fair_write_scheduling=False`). Relay metrics are bounded and payload-free, but do add instrumentation overhead.
- All late flows started while the bulk transfer was active. All 12 runs passed integrity, relay observability, resource cleanup and event-buffer bounds checks.

## Results

Values are medians over three trials. “Paired delta” is the median of per-trial percentage changes against the 64 KiB control using the same configured seed. Negative latency deltas are better; negative goodput deltas are worse. The updates and pause counts are diagnostic metrics, not independent quality scores.

| Threshold | Bulk goodput | Paired delta | Bulk completion | Paired delta | Early RTT p95 | Paired delta | Late RTT p95 | Paired delta | `WINDOW_UPDATE` commands | Pauses >1 ms | Time in pauses >1 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 KiB | 2.96 Mbps | -45.06% | 708.17 ms | 82.02% | 127.68 ms | 18.26% | 134.72 ms | 13.28% | 21 | 13 | 646.92 ms |
| 32 KiB | 5.00 Mbps | -7.07% | 419.36 ms | 7.60% | 118.83 ms | 13.82% | 116.32 ms | -4.95% | 15 | 7 | 352.60 ms |
| 64 KiB | 5.35 Mbps | 0.00% | 391.94 ms | 0.00% | 104.41 ms | 0.00% | 121.98 ms | 0.00% | 14 | 5 | 284.71 ms |
| 128 KiB | 5.38 Mbps | 6.54% | 389.77 ms | -6.14% | 109.07 ms | 4.47% | 134.27 ms | 7.56% | 14 | 5 | 260.10 ms |

## Interpretation

- **16 KiB is a poor candidate in this workload.** Its median goodput was about 45% lower than the control based on paired trial deltas, completion time was about 82% higher, early interactive p95 was about 18% higher, and the exit relay observed more update commands and longer pauses waiting for credit. Returning credit after nearly every 16 KiB read added control traffic without improving these observed metrics.
- **32 KiB showed a mixed trade-off.** The late-flow RTT p95 improved by about 4.95% in the median paired delta, but bulk goodput fell about 7.07%, early RTT p95 worsened about 13.82%, and pause time increased about 11.67%. This is not a general win.
- **128 KiB did not produce a consistent interactive improvement.** Bulk goodput was close to or slightly above the control in this small sample, while early RTT p95 and late RTT p95 were worse in paired medians. The median number of updates was similar to the control.
- **The current 64 KiB setting remains the default.** The results do not justify changing the threshold based on this sample. They are local exploratory evidence, not proof of an optimal setting.

## Reproduction

```bash
PYTHONPATH=src python -m anonlab.window_update_benchmark \
  --profile metro \
  --trials 3 \
  --batch-sizes 16384 32768 65536 131072 \
  --bulk-bytes 262144 \
  --interactive-requests 5 \
  --request-bytes 128 \
  --request-gap-ms 5 \
  --stagger-after-ms 20 \
  --write-chunk-bytes 16384 \
  --pipeline-depth 4 \
  --seed 20261024 \
  --output experiments/window-update-batch-sensitivity-v0.22.0.json
```

## Validation

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: **151 tests passed**.
- `PYTHONPATH=src pytest -q`: **153 tests passed, 11 subtests passed**.
- The 12 benchmark runs passed integrity, relay-observability, resource-cleanup and bounded-event checks; late interactive flows overlapped bulk transfers in all runs.

## Limitations

- All relays, TCP shaping proxies and the echo destination run on one host over IPv4 loopback.
- The proxy shapes TCP byte-stream chunks and does not simulate IP packet loss or retransmission.
- The 2 ms delayed flush remains fixed, so this experiment isolates the byte threshold rather than the timer.
- Identical configured seeds do not guarantee identical shaper event sequences when timing changes.
- The metrics are finite-flow observations from three trials per condition; they do not establish statistical significance, a real-WAN prediction, anonymity, or independent cryptographic security.

Raw per-run data and paired summaries: `experiments/window-update-batch-sensitivity-v0.22.0.json`.
