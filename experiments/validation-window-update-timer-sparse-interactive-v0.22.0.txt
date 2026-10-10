# Validation — sparse-interactive WINDOW_UPDATE timer follow-up (v0.22.0)

Date: 2026-10-09

## Benchmark runs

- `metro`: 4 trials × 2 timers = 8 complete runs.
- `intercontinental`: 4 trials × 2 timers = 8 complete runs.
- Total: 16/16 completed runs passed the benchmark's payload-integrity, relay-observability, resource-cleanup, telemetry-bounds and configured-parameter checks.
- The late interactive stream began while the bulk transfer was active in all 16 runs.
- Conditions: timers 2 ms and 5 ms; receive-credit threshold 65,536 bytes; 128 KiB bulk; four 128-byte interactive requests spaced 250 ms apart; stagger 100 ms; 8 KiB write chunks; pipeline depth 2; default scheduler.
- Raw results: `window-update-timer-sparse-metro-v0.22.0.json`, `window-update-timer-sparse-intercontinental-v0.22.0.json`, combined `window-update-timer-sparse-matrix-v0.22.0.json`.

## Regression tests

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: 154 tests passed in 24.592 s; no resource warning was emitted.
- `PYTHONPATH=src pytest -q`: 156 tests and 23 subtests passed in 25.17 s.

## Decision

Keep the 2 ms default. In the sparse workload, 5 ms lowered median paired bulk goodput 7.80% in `metro` and 1.05% in `intercontinental`, while worsening late-flow RTT p95 by 4.71% and 3.55%, respectively. Four trials per condition remain exploratory; no inferential claim is made.

## Limitations

All experiments use one host and TCP byte-stream shaping proxies. They do not reproduce IP packet loss/retransmission or a real WAN. Four requests per flow provide an unstable p95 estimate. Shared configured seeds and rotating order reduce some confounds but do not make asynchronous timing deterministic.

## Package checks

- Wheel built successfully with the locally installed build backend (`pip wheel --no-deps --no-build-isolation`); SHA-256: `4221582b5960577267f6c21c17bb7f8fb6ece9a4f45d86fa2ca11a52123066e5`.
- Installed the wheel into a fresh virtual environment with the existing system `cryptography` installation (`43.0.0`) available; the `rea-anon-window-update-timer-bench --help` entry point and module import smoke checks passed. The benchmark depends on the optional `onion-lab` extra (`cryptography`); a bare wheel-only environment without that extra cannot import this benchmark.
