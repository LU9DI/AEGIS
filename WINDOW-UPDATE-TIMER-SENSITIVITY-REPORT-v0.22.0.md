# WINDOW_UPDATE sparse-credit flush timer sensitivity — v0.22.0

## Question

Does reducing or increasing the maximum wait before flushing pending, sub-threshold receive credit improve mixed bulk/interactive behavior when the receive-credit batch threshold is fixed at 64 KiB?

## Method

- Profile: `metro`, using local TCP shaping proxies on IPv4 loopback.
- Configurations: 0.5 ms, 2 ms (current control), and 5 ms.
- Repeats: 10 trials per configuration (30 runs total); condition order rotates each trial.
- Bulk transfer: 256 KiB; five 128-byte interactive requests at 5 ms gaps; late flow is staggered by 20 ms.
- Write chunk: 16 KiB; pipeline depth: 4; default write scheduler held constant.
- Threshold held constant: 65,536 bytes (64 KiB).
- Each trial uses a configured shaper seed common to the three timer values, although asynchronous TCP timing traces are not guaranteed to be identical.

The timer only bounds the wait when `read_chunk()` has pending credit below the byte threshold and is waiting for more data. It is **not** a timer applied to every `WINDOW_UPDATE`.

## Results

Percentages are the median of the per-trial paired percentage deltas versus the 2 ms control. Win/loss counts count paired trials favorable/unfavorable to the candidate according to the metric's direction. Positive latency percentages mean worse tail latency.

| Timer | Bulk goodput delta (wins/losses) | Completion-time delta (wins/losses) | Early interactive RTT p95 (wins/losses) | Late interactive RTT p95 (wins/losses) | `WINDOW_UPDATE` command count delta | Total >1 ms credit-pause time delta |
|---|---:|---:|---:|---:|---:|---:|
| 0.5 ms | -1.75% (3/7) | +1.78% (3/7) | +0.64% (3/7) | +1.54% (4/6) | +0.00% | -1.24% |
| 2 ms (control) | Baseline | Baseline | Baseline | Baseline | Baseline | Baseline |
| 5 ms | +23.94% (9/1) | -19.21% (9/1) | +0.18% (5/5) | +0.98% (5/5) | -13.33% | -17.31% |

Additional observations from the summary:

- **5 ms** yielded a +23.94% median paired bulk-goodput delta (9 wins, 1 loss) and −19.21% completion time (9 wins, 1 loss).
- At 5 ms, the median paired command-count delta was −13.33%; total time in flow-credit pauses over 1 ms had a −17.31% median paired delta (10 wins, 0 losses).
- The interactive p95 results did not improve consistently at 5 ms: early p95 was +0.18% (5 wins, 5 losses) and late p95 was +0.98% (5 wins, 5 losses). This is effectively mixed/neutral in this small sample, not proof of no effect.
- **0.5 ms** was also not a consistent win: the median paired goodput delta was −1.75% (3 wins, 7 losses), while early and late interactive p95 were +0.64% and +1.54% respectively.
- All 30 runs passed payload integrity, relay-observability, resource cleanup, instrumentation-bound, configured timer/batch, and late-flow-overlap checks.

## Decision

Keep the default at **2 ms**. Five milliseconds is a plausible throughput-oriented experimental setting, but the current evidence does not show a reliable reduction in interactive tail latency. Do not change the default based on this finite-flow sample alone. A follow-up should include longer-lived sparse streams, multiple payload scales, more than one network profile, and a predeclared tail-latency acceptance criterion.

## Validation

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: 154 tests passed.
- `PYTHONPATH=src pytest -q`: 156 tests passed, 23 subtests passed.
- The benchmark output reported all integrity/cleanup/configuration/bounded-buffer checks passed and all late flows overlapped the bulk transfer.
- The wheel was rebuilt from this source tree, installed into an isolated virtual environment, and the `rea-anon-window-update-timer-bench --help` entry point was executed successfully.

## Limitations

This is a single-host loopback experiment. Proxies shape a TCP byte stream rather than IP packets; packet loss, retransmission, WAN routing, real congestion, and global-adversary anonymity are not modeled. The configured seeds hold random profile inputs in common, not deterministic socket/event schedules. Relay metrics are bounded and exclude payloads but add overhead and remain timing metadata. This report is exploratory performance analysis, not a cryptographic audit or production-readiness claim.
