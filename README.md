# AEGIS / MALEBOLGE — recovered research archive

This repository is being populated incrementally from recovered project files. **The Git tree is not yet a complete mirror of the recovered source tree.** Do not treat the current tree as a complete source release.

## Current upload status

Published and verified:
- package metadata (`pyproject.toml`), ignore rules, validation notes and recovery reports;
- a subset of simulator, routing, onion-envelope, PIR and XOR secret-sharing modules with selected tests;
- architecture, threat model, roadmap, protocol, onion, PIR and sharing design notes;
- `AEGIS-consolidated-recovery-2026-10-09.zip`, which contains selected research ZIPs, a recoverable Git baseline bundle and status/checksum files;
- GitHub Actions workflow at `.github/workflows/recovery-validation.yml`, which verifies the archive checksum and nested ZIPs, extracts the v0.27.4 source snapshot, compiles the source/tests, and runs pytest.

**The consolidated ZIP is not the full-history recovery archive.** It contains the v0.27.4 research snapshot, which was verified to match the recovered 246-file source tree exactly. It also contains selected older/research snapshots, not every historical artifact.

Still missing as ordinary files from the Git tree:
- 27 source modules and 22 test files from the recovered snapshot;
- many experiment outputs, docs, changelog and reports;
- historical ZIPs/wheels and the expanded full-history recovery ZIP.

Because the Git tree is partial, some console entry points declared in `pyproject.toml` refer to modules that are not present as individual files in `main`. Extract the full v0.27.4 source snapshot from the consolidated ZIP if you need the complete recovered source tree, or wait until the remaining files are published into Git. The new CI workflow validates the source snapshot embedded in the archive; it does **not** claim the partial Git checkout itself is complete.

## Recovery archive details

The consolidated archive in this repository:
- File: `AEGIS-consolidated-recovery-2026-10-09.zip`
- Size: 6,177,944 bytes
- SHA-256: `ae59e83cf68caebdebeb7522dd36c0bc16f9bbe288bbff1ce99bd7880c659be3`

The expanded full-history recovery archive is a separate file:
- File: `AEGIS-FULL-HISTORY-RECOVERY-2026-10-09.zip`
- Size: 29,923,637 bytes
- SHA-256: `8b0f01c8b54e356234dab4920e228af98fe3f63b06ecbd0060906626ed7265c2`

The full-history archive contains 458 ZIP entries, including 246 current-source files and additional historical artifacts, wheels, reports, experimental outputs and checksum records. It has not been uploaded to this repository as a separate file/release asset.

See [the GitHub/recovery audit](recovery/AEGIS-GITHUB-AUDIT-2026-10-10.md) for the latest verification, test results, gaps and security findings.

## Security caveats

AEGIS is a research prototype, not a production-ready or independently audited anonymity system. Garlic-clove delivery/batching semantics are not implemented. The two-server XOR PIR prototype assumes non-colluding replicas; colluding replicas can recover the requested index. The four-server consistency check is not a cryptographic proof of correct PIR computation and cannot prevent collusion or common-mode failures. A TLS-authenticated replica can still return a false PIR answer while claiming the expected snapshot hash. The relay testbed and RPC/TLS demos do not establish security on a live multi-operator network.

Simulator outputs and route-selection examples are hypothetical or synthetic, not measurements of Tor or a live network. **Do not use this prototype for sensitive or production communications.**

## Recovery integrity

Historical ZIP snapshots are not a reconstructed original Git commit graph. The recovered Git bundle contains a recovery baseline, not all original commits. Missing artifacts and checksum discrepancies are documented in `recovery/`. Keep an independent copy of the recovery archives outside this repository and outside temporary workspaces.
