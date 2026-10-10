# AEGIS v0.23.0 — route, PIR and secret-sharing prototypes

## Executive decision

Three research primitives were added without changing the live/loopback relay transport:

1. A client-local route scorer using measured link RTT where available, geometry-derived lower bounds for missing links, load/bandwidth/failure penalties, a pinned confirmed guard, and hard ASN/family/subnet diversity constraints.
2. A two-server XOR PIR reference construction for replicated fixed-width rows.
3. A chunk-level 2-of-2 XOR secret-sharing primitive with local integrity manifest and reconstruction check.

The implementation does **not** add ZK proofs, FHE, native QUIC, a WebAssembly client, WebTransport integration, distributed PIR servers, or live multipath relay forwarding. Those are separate design and audit tasks. Technical details and restrictions are in `docs/AEGIS_V0.23.0_ARCHITECTURE_DECISIONS.md`.

## Smoke-run outputs (synthetic/local only)

### Route scoring

The example topology selected `guard-pinned-sp → middle-sp → exit-sp` with 4 supplied synthetic link measurements, a modeled end-to-end RTT of 10.5 ms, and a score of 12.125 ms. This is a deterministic synthetic input, not a live ping, measured network route, or anonymity result. The route plan output omits client/destination coordinates. It explicitly reports `uses_zero_knowledge_proofs: false` and `is_live_network_test: false`.

### Two-server XOR PIR

The demo retrieved fixed-width row 17 from a synthetic table of 64 rows. Each server received an 8-byte query vector and returned 32 bytes; each simulated server scanned 64 records. Exhaustive unit testing over all 4-bit query masks confirms that for this construction, each server's individual query distribution is uniform independent of the selected index for that toy domain. This does not test server collusion, a network transport, identity privacy, or side channels. The reference construction has O(N) query upload and per-server row scan.

### Chunk-level XOR sharing

A synthetic 65,537-byte payload was encoded into 17 chunks of 4,096 bytes; each path's share occupied 69,632 padded bytes. Reconstruction and SHA-256 integrity verification succeeded. No share was transmitted. Anyone who sees both shares (including a shared guard before paths diverge) can reconstruct the data; timing and size bucket remain visible.

## Validation

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: **185 tests passed** in 24.416 s.
- `PYTHONPATH=src pytest -q`: **187 tests passed, 44 subtests passed** in 24.97 s.
- `python -m pip wheel . --no-deps --no-build-isolation`: built `aegis_anon_lab-0.23.0-py3-none-any.whl` successfully.
- Installed wheel into a clean virtual environment and executed `aegis-route-select --input examples/route-topology-demo.json`, `aegis-pir-demo --records 64 --index 17`, `aegis-share-demo --payload-bytes 65537 --chunk-size 4096`, and the canonical `aegis` simulator smoke command.
- The same full test runners passed from both the source tree and a fresh extraction of the ZIP, verifying that the archive matches the tested source set.
- The three CLI outputs are stored at `experiments/route-selection-demo-v0.23.0.json`, `experiments/pir-reference-demo-v0.23.0.json`, and `experiments/secret-sharing-demo-v0.23.0.json`.
- Python package version is 0.23.0. Existing v1 protocol domain-separation strings remain unchanged; the prior TCP relay path remains the control.

## Environment boundary

The current build environment has no `rustc`, `cargo`, or `aioquic`, so no Rust/QUIC crate was compiled and no QUIC implementation is included. The current prototypes are not connected to the existing relay circuit and are not production-ready anonymity features.
