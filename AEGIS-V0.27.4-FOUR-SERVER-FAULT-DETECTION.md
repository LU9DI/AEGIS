# AEGIS v0.27.4 research note — independent four-server PIR reconstruction

## Purpose

Add an optional defense-in-depth API that performs two independently randomized two-server XOR-PIR retrievals using four distinct endpoints and compares the reconstructed records. It detects a class of single-replica answer corruption that a single two-server retrieval cannot detect on its own.

## API

`anonlab.pir_rpc.retrieve_four_server_pir_rpc_checked(...)`

- Requires exactly four distinct server IDs and host/port pairs.
- Rejects duplicate legacy HMAC pre-shared keys and mixed transport modes.
- Runs two separate calls to `retrieve_two_server_pir_rpc` concurrently; each call generates its own randomized query pair.
- Passes through the caller-pinned snapshot fingerprint, if supplied.
- Rejects different reported snapshot fingerprints or different reconstructed records.
- Returns `RedundantPirRpcTransfer` only when both reconstructions agree.

## Security limits

This is redundancy-based fault detection, **not verifiable PIR** and not a cryptographic proof of correct computation. It costs four replicas and roughly doubles the traffic versus one two-server retrieval. It can fail against coordinated corruption across both pairs, collusion, shared implementation defects, compromised client state, or a common-mode dataset error. Each pair must preserve the protocol's non-collusion assumption for its query privacy; four endpoints do not by themselves guarantee independence of operators or infrastructure.

The API does not claim production security. A signed snapshot manifest and pinned fingerprint authenticate the expected snapshot identity only when the trust anchor is provisioned securely; they do not prove response correctness.

## Tests

- Healthy four-server retrieval reconstructs the expected record.
- A deliberately corrupted response from one replica causes the independent reconstructions to disagree and raises `PirRpcProtocolError`.
- Existing RPC regression tests remain in place.

## Validation record

`python -m pytest -q`: 227 passed, 76 subtests passed.

`PYTHONPATH=src python -m unittest tests.test_pir_rpc -q`: 16 tests passed.

A full `unittest discover` run did not complete within the execution time limit in this environment; it is not counted as a passing full-suite result. The full pytest suite is the complete successful validation result for this package.

## Release status

Research package only. `pyproject.toml` remains at 0.26.0. No production deployment or official release is implied by the `v0.27.4` research label.
