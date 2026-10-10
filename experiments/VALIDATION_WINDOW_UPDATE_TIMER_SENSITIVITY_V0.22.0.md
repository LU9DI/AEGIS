# Validation — WINDOW_UPDATE timer sensitivity follow-up v0.22.0

Date: 2026-10-09

- Full `unittest` suite with `ResourceWarning` promoted to errors: 154 passed in 23.729 s.
- Full `pytest` suite: 156 passed, 23 subtests passed in 25.12 s.
- Timer sensitivity matrix: 30 runs (10 each at 0.5, 2, and 5 ms); all payload integrity, relay observability, resource cleanup, bounded-event-buffer, configured timer/threshold, and late-flow-overlap checks passed.
- Default remains 2 ms. Five milliseconds showed a throughput/completion benefit in this particular loopback profile but no consistent tail-latency benefit.
- Wheel `rea_anon_lab-0.22.0-py3-none-any.whl` built successfully, installed into an isolated virtual environment, and the `rea-anon-window-update-timer-bench --help` entry point ran successfully.
- Package version remains 0.22.0; no release/version promotion is implied.

Commands:

```bash
PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m anonlab.window_update_timer_benchmark --profile metro --trials 10 --timer-values-ms 0.5 2 5 --batch-bytes 65536 --bulk-bytes 262144 --interactive-requests 5 --request-gap-ms 5 --stagger-after-ms 20 --pipeline-depth 4 --seed 20261027 --output experiments/window-update-timer-sensitivity-v0.22.0.json
```

The recorded result was produced before packaging from the same benchmark implementation and configuration. Re-running can produce different timing because TCP proxy and asyncio event timing are not deterministic.
