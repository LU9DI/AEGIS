# AEGIS v0.23.0 validation record

Date: 2026-10-09

## Test suites

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q` — **185 passed**, 24.416 s, no resource warnings emitted.
- `PYTHONPATH=src pytest -q` — **187 passed, 44 subtests passed**, 24.97 s.

The unittest and pytest runners discover the same codebase through different runner conventions; their counts should not be added together as if they represented unique test cases.

## Packaging

- Distribution: `aegis-anon-lab==0.23.0`.
- Wheel: `aegis_anon_lab-0.23.0-py3-none-any.whl`.
- Built with `python -m pip wheel . --no-deps --no-build-isolation` using the locally installed setuptools backend.
- Installed into a newly created virtual environment with `pip install --no-deps`.
- Executed the three new console scripts and the existing `aegis` simulator from the installed wheel.
- The same two full test runners also passed after extracting the final ZIP into a fresh directory: 185 unittest tests, plus 187 pytest tests and 44 subtests. The wheel smoke checks were for actual command startup/outputs; they are not a network integration test.

## New functionality checked

1. `aegis-route-select --input examples/route-topology-demo.json` generated a route plan without endpoint coordinates, marked it as not a live network test, and reported that no ZK proof was used.
2. `aegis-pir-demo --records 64 --index 17` reconstructed the synthetic 32-byte row. For the construction, each server receives an 8-byte query bit-vector and scans all 64 rows; no network request is made.
3. `aegis-share-demo --payload-bytes 65537 --chunk-size 4096` created 17 padded chunks, reconstructed the synthetic payload, and verified the local SHA-256 manifest. No share is transmitted.

Raw smoke outputs are included in `experiments/route-selection-demo-v0.23.0.json`, `experiments/pir-reference-demo-v0.23.0.json`, and `experiments/secret-sharing-demo-v0.23.0.json`.

## Scope/limitations

- Geometry is a latency heuristic, not a ping guarantee; only the synthetic topology is demonstrated here.
- PIR assumes identical non-colluding replicas. Collusion reveals the requested index; PIR alone does not hide source identity or timing.
- XOR shares do not protect against a relay/common guard/global observer seeing both shares. The module has no live transport or traffic-analysis defense.
- No ZK credential system, FHE, native Rust/QUIC transport, browser Wasm client, or WebTransport integration is implemented.
- The environment had no `rustc`, `cargo`, or `aioquic`; no native QUIC build/test was attempted.
- The existing TCP circuit remains the control; no protocol crypto domains were renamed and no live network was contacted by these prototypes.
