# AEGIS PIR research increment — persistent anti-rollback checkpoint

## Delivered

- Added atomic checkpoint persistence helpers to `anonlab.pir_manifest`.
- Writes are staged in the target directory, restricted to owner read/write where supported, flushed and fsynced before atomic replacement; POSIX directory entries are fsynced afterward.
- Loader validates schema, exact field set, sequence and digest shape and rejects malformed/oversized files.
- Added tests for round-trip persistence, unknown schema, malformed JSON and inconsistent in-memory state.

## Validation

- `PYTHONPATH=src python -m pytest -q`: **222 passed, 76 subtests passed**.
- `PYTHONPATH=src python -m unittest discover -s tests -q`: **207 tests passed**.

## Limitations

The checkpoint API assumes one writer and a trusted parent directory. It does not provide inter-process locking, secure hardware monotonic counters, quorum-backed state, or resistance to a local attacker able to rewrite the file. Production anti-rollback must anchor state outside the same mutable trust boundary and define backup/recovery policy. The manifest/checkpoint code remains unintegrated with RPC and does not prove PIR answer correctness. The package version remains 0.26.0.
