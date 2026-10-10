# AEGIS — verifiable PIR design artifact validation

## Scope

This package carries a design note for the next verifiable-PIR implementation phase. It does not change the Python package version and does not implement a proof system.

## Changes

- `docs/AEGIS_V0.27_VERIFIABLE_PIR_DESIGN.md`: threat model, required proof statement, candidate construction families, snapshot lifecycle, fail-closed behavior, red-team acceptance matrix, performance measurements, and release gate.
- `CHANGELOG.md`: records the design-only change and explicitly preserves the v0.26.0 security boundary.

## Regression validation

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: **207 tests passed** in 27.204 s.
- `PYTHONPATH=src pytest -q`: **209 passed, 76 subtests passed** in 29.17 s.

These are regression results for the existing v0.26.0 implementation plus documentation changes. They are not tests of a verifiable-PIR proof system, because none has been implemented.

## Security status

The v0.26.0 malicious-replica limitation remains open: a TLS-authenticated replica can return a false PIR response while claiming the expected snapshot fingerprint. The client may accept corrupted reconstruction. The design note defines the acceptance criteria for closing this gap, but the gap is not closed by this package.

No remote push, live remote-network test, independent-operator test, or cryptographic audit was performed. The existing project remains a research prototype and is not production-secure.
