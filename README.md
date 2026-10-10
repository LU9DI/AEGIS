# AEGIS / MALEBOLGE — Research archive

This repository is being populated incrementally from recovered project files. **It is not yet a complete mirror of the source tree or recovery archive.** Do not treat the current GitHub tree as a complete release.

## Current upload status

Uploaded and verified in this repository:
- Package metadata: `pyproject.toml` (declares `aegis-anon-lab==0.26.0`).
- `.gitignore` and v0.26.0 validation record.
- Research simulator subset: `src/anonlab/__init__.py`, `model.py`, `profiles.py`, `simulator.py`, `cli.py`.
- Local two-server XOR PIR prototype: `src/anonlab/pir.py` and its regression tests `tests/test_pir.py`.
- Local XOR secret-sharing prototype: `src/anonlab/secret_sharing.py` and its regression tests `tests/test_secret_sharing.py`.
- Architecture notes and full-history recovery audit under `docs/` and `recovery/`.

**Not yet uploaded:** the remaining implementation modules, most tests, the historical source snapshots/wheels/JSON experiment outputs, the full recovery ZIP, the Git bundle, and the complete checksum inventory. The package's declared entry points therefore refer to files that are not all present in this partial GitHub tree yet.

## Recovery archive details

The recovery audit describes 246 files in the latest recovered source snapshot and the historical artifacts found. The expanded archive's SHA-256 is recorded in `recovery/AEGIS-FULL-HISTORY-RECOVERY-2026-10-09.SHA256`; the archive itself is still held in the working session and has not been uploaded as a GitHub release asset.

## Security caveats

AEGIS is a research prototype, not a production-ready or independently audited anonymity system. The two-server XOR PIR prototype assumes replicated databases and non-colluding servers. Four-server PIR consistency checks are not a cryptographic proof of correct PIR computation and do not prevent collusion or common-mode failures. Simulator outputs are hypothetical models, not measurements of Tor or a live network.

## Recovery integrity

Historical ZIP snapshots are not a reconstructed original Git commit graph. The recovered Git bundle contains a recovery baseline, not all original commits. Missing artifacts and checksum discrepancies are documented in the full-history audit. Keep an independent copy of the recovery archive outside this temporary working environment.
