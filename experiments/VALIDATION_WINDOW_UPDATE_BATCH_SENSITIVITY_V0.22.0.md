# Validation record — WINDOW_UPDATE batch sensitivity follow-up

- Package version: `0.22.0` (version intentionally unchanged)
- Source command: `PYTHONPATH=src python -m anonlab.window_update_benchmark --profile metro --trials 3 --batch-sizes 16384 32768 65536 131072 --bulk-bytes 262144 --interactive-requests 5 --request-bytes 128 --request-gap-ms 5 --stagger-after-ms 20 --write-chunk-bytes 16384 --pipeline-depth 4 --seed 20261024 --output experiments/window-update-batch-sensitivity-v0.22.0.json`
- Benchmark result: 12/12 runs completed; all integrity, relay-observability, resource-cleanup and telemetry-bound checks passed; all late interactive flows began while bulk transfer was active.
- Unit tests: `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q` — 151 passed.
- Pytest: `PYTHONPATH=src pytest -q` — 153 passed, 11 subtests passed.
- Smoke command: `PYTHONPATH=src python -m anonlab.window_update_benchmark --help`.
- Notes: exploratory local result only. Do not infer WAN performance or production congestion-control behavior. The default 64 KiB threshold remains unchanged.
