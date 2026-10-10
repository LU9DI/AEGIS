# AEGIS v0.24.0 validation record

Date: 2026-10-09

## Source tests

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: **194 passed** in 24.377 seconds; no `ResourceWarning` escaped.
- `PYTHONPATH=src pytest -q`: **196 passed, 76 subtests passed** in 25.70 seconds.
- Targeted `tests/test_pir_rpc.py`: **9 passed** in 0.171 seconds.
- `python -m compileall -q src tests`: passed.

## PIR RPC smoke test

Command: `PYTHONPATH=src python -m anonlab.pir_rpc_demo --records 64 --index 17 --record-bytes 32`

Result: correct record reconstruction; two distinct loopback ports; four HMAC-authenticated messages (two requests/two replies); no target index in the RPC request schema; output explicitly declares no encryption, no live remote network test, no security proof, and no production readiness.

## Important caveats

The two server listeners run in one process. HMAC provides message authentication/integrity for key holders, not confidentiality; distributing symmetric keys to public clients lets those clients forge messages. The remote network bind is refused by code. A network observer seeing both query masks recovers the index, and colluding replicas always recover it. No claim of deployment security, anonymity, or independent-operator assurance is made.
