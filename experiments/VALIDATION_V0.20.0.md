# Validation — MALEBOLGE v0.20.0

- Python source compilation: passed.
- `pytest -q`: **130 passed, 11 subtests passed**.
- Tests cover profile validation, IPv4 loopback restriction, shaped echo round-trip, half-close preservation, nonzero delay, shared aggregate bandwidth cap, bounded queue depth, proxy connection admission limits, full circuit integrity/observability/cleanup, sparse stream liveness and invalid benchmark parameters.
- Network-condition matrix: 12 runs (2 trials for each of five profiles and 2 sparse intercontinental trials); every run passed integrity, observability, relay cleanup, proxy cleanup and queue-bound checks.
- Measured environment: Python 3.13.5 on Linux x86-64; all relay, proxy, and echo processes ran on one host over IPv4 loopback.
- The proxy shapes TCP byte-stream read chunks; it does not model IP packet loss or retransmission. All measurements are exploratory and do not prove anonymity.
- Wheel `rea_anon_lab-0.20.0-py3-none-any.whl` built successfully, installed in a fresh virtual environment using the installed system cryptography dependency, and passed the installed `rea-anon-network-impairment-bench --help` and `--profile lan --streams 1 --payload-bytes 1024` smoke run. The smoke run confirmed version 0.20.0, integrity, relay cleanup, proxy cleanup, and zero rejected connections.
