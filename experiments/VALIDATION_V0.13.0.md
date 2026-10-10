# MALEBOLGE v0.13.0 validation record

## Automated tests

On Linux x86-64 with Python 3.13.5:

```text
python -m pytest -q
100 passed, 11 subtests passed

python -m pytest tests/test_telescoping.py -q
25 passed, 4 subtests passed
```

The focused cancellation regression validates that a stream canceled while the client's active-stream limit is reached does not desynchronize the child relay sequence; a subsequent request on the same circuit succeeds.

## Multiplex benchmark

Command:

```bash
PYTHONPATH=src python -m anonlab.multiplex_benchmark \
  --streams 16 --payload-bytes 4096 --seed 20261009 \
  --output experiments/stream-multiplex-v0.13.0.json
```

Verified: payload integrity, the benchmark's parsed route-observation check, one direct client-to-guard connection, zero active streams after completion and zero active connections after close. Numeric results and environment metadata are in the raw JSON and [`STREAM_MULTIPLEXING_REPORT_V0.13.0.md`](STREAM_MULTIPLEXING_REPORT_V0.13.0.md).

This result is not a WAN performance test or an anonymity proof. It shows that concurrent request/response exchange works, but the first workload did not produce a compelling speedup.
