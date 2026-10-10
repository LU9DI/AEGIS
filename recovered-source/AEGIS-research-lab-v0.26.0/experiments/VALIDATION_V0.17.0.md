# MALEBOLGE v0.17.0 validation record

## Automated tests and packaging

- Source test suite: **109 passed, 11 subtests passed** (`python -m pytest -q`).
- Python modules compile and import under Python 3.13.5.
- Built `rea_anon_lab-0.17.0-py3-none-any.whl` with `pip wheel --no-deps --no-build-isolation`.
- Verified the wheel contains `anonlab/pipeline_benchmark.py` and version metadata `0.17.0`.
- Installed the wheel into a fresh virtual environment using system cryptography dependency, away from the source tree.
- The installed `rea-anon-pipeline-bench` command completed a three-depth smoke experiment. Metadata reported version 0.17.0; integrity, relay-observability and cleanup checks all passed.
- `rea-anon-pipeline-bench --help` and `rea-anon-duplex-bench --help` list their expected pipeline options.
- Final ZIP was extracted to a clean directory and the extracted source test suite passed: **109 passed, 11 subtests passed** (20.26 seconds).

## Main performance experiment

- Linux x86-64, Python 3.13.5, one host, IPv4 loopback.
- 3-hop circuit and local echo destination; 8 streams × 1 MiB each; 64 KiB chunks.
- Five trials per pipeline depth with rotating order.
- Depth 1: median 234.45 Mb/s, p50 282.51 ms, range 204.60–242.40 Mb/s.
- Depth 2: median 220.15 Mb/s, p50 300.75 ms, range 208.63–235.08 Mb/s.
- Depth 4: median 237.31 Mb/s, p50 277.58 ms, range 176.23–240.10 Mb/s.
- All 15 trials passed integrity, parsed relay-observability and cleanup checks. Depth 4 was only 1.2% above depth 1; depth 2 was 6.1% below it. No robust performance gain is established.

## Smaller performance experiment

- 3 trials per depth; 8 streams × 256 KiB each; 64 KiB chunks.
- Median goodput: 222.56 Mb/s at depth 1; 225.19 Mb/s at depth 2; 192.91 Mb/s at depth 4.
- All integrity, relay-observability and cleanup checks passed in all 9 trials. Depth 4 was 13.3% below depth 1 in this workload.

## Safety and interpretation

All network experiments use IPv4 loopback. They do not validate WAN delay/loss, traffic correlation, anonymity, production security, fairness, or comparison to Tor. TCP-direct measurements are throughput references only, not privacy-equivalent baselines. The custom protocol remains unaudited and must not be exposed to the public Internet or used for sensitive traffic.
- Final source after adding the 512-command per-call cap: `109 passed, 11 subtests passed`.
- Final wheel was rebuilt after that cap, inspected to confirm the cap exists in `anonlab/telescoping.py`, and its `Version: 0.17.0` metadata was verified.
- Final wheel was installed into a fresh virtual environment; its installed `rea-anon-pipeline-bench` CLI smoke test passed at depths 1/2/4 with all integrity, observability and cleanup checks true.
