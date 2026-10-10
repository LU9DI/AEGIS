# AEGIS / MALEBOLGE — recovered research archive

This repository is being populated incrementally from recovered project files. **It is not yet a complete mirror of the recovered source tree or recovery archives.** Do not treat the current GitHub tree as a complete release.

## Current upload status

Published and verified so far:
- package metadata (`pyproject.toml`), `.gitignore`, and v0.26.0 validation notes;
- simulator subset: `src/anonlab/__init__.py`, `model.py`, `profiles.py`, `simulator.py`, and `cli.py`;
- PIR implementations: `src/anonlab/pir.py` and `pir_two_server.py`, with selected tests;
- local XOR secret-sharing prototype `src/anonlab/secret_sharing.py` and tests;
- offline route-selection engine and synthetic demo;
- loopback-only TCP relay and experimental binary onion envelope module;
- architecture, threat model, roadmap, MALEBOLGE charter, protocol v2, onion, PIR and XOR-sharing design notes;
- full-history recovery audit, checksum audit, archive inventory and recovery status.

**Still not uploaded:** many remaining implementation modules (including the telescoping circuit, directory and authenticated PIR RPC/TLS code), most tests, many experiment outputs and reports, full changelog, historical source ZIPs/wheels, the local Git bundle, and the full-history recovery ZIP as binary assets. The package entry points therefore refer to files that are not all present in this partial GitHub tree yet.

## Recovery archive details

The recovered full-history archive is named `AEGIS-FULL-HISTORY-RECOVERY-2026-10-09.zip`, with SHA-256 `8b0f01c8b54e356234dab4920e228af98fe3f63b06ecbd0060906626ed7265c2`. The archive itself remains in the working session and has **not** been uploaded as a GitHub release asset.

The recovery audit describes a latest recovered source snapshot of 246 tracked files. The publish-stage export currently contains 233 files excluding caches and bytecode, so the snapshot and stage counts should not be conflated.

## Security caveats

AEGIS is a research prototype, not a production-ready or independently audited anonymity system. The two-server XOR PIR prototypes assume replicated databases and non-colluding servers. The four-server PIR consistency check described in the experimental snapshots is not a cryptographic proof of correct PIR computation and does not prevent collusion or common-mode failures. Simulator outputs and route-selection examples are hypothetical or synthetic, not measurements of Tor or a live network.

## Recovery integrity

Historical ZIP snapshots are not a reconstructed original Git commit graph. The recovered Git bundle contains a recovery baseline, not all original commits. Missing artifacts and checksum discrepancies are documented under `recovery/`. Keep an independent copy of the recovery archive outside this temporary working environment.
