# Validation record — MALEBOLGE v0.21.0

- Version metadata: `0.21.0`.
- Full test command: `python -m pytest -q`.
- Result: **137 passed, 11 subtests passed**.
- Fairness matrix command: `PYTHONPATH=src python -m anonlab.fairness_benchmark --profile metro --stream-counts 1,2,4,8 --trials 3 --payload-bytes 32768 --seed 20261021 --output experiments/fairness-matrix-metro-v0.21.0.json`.
- Fairness matrix: 12 runs; all payload integrity, relay-observability, relay cleanup, and zero-proxy-connection checks passed.
- Wheel: built with `pip wheel --no-deps --no-build-isolation`, installed into a fresh virtual environment, and the installed `rea-anon-fairness-bench` command completed a two-scenario smoke run successfully.
- ZIP: a clean source archive is validated by rerunning the complete test suite after extraction.
- Limitations: results use IPv4 loopback with a user-space TCP byte-stream shaper. This is not a WAN test, does not simulate packet loss, and does not prove anonymity or steady-state fairness.
