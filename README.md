# AEGIS — Anonymous Encrypted Garlic-routed Internet Shield

**AEGIS** stands for **Anonymous Encrypted Garlic-routed Internet Shield**. AEGIS is an actively developed privacy and anonymity network intended for **production use**. The project is currently under construction and testing. This repository includes recovered source code, prototypes, simulations, and validation artifacts that support development toward that production goal. The production objective is real; production readiness has not yet been established.

The v0.27.4 recovered Python source, tests, design documents, examples, experiment results, and reports are now published as normal Git files. The repository also retains the consolidated recovery ZIP. Eight pre-existing files intentionally differ from the snapshot and were preserved rather than overwritten; their reconciliation is tracked in [Issue #1](https://github.com/LU9DI/AEGIS/issues/1). The original historical Git commit graph has not been reconstructed.

## Repository recovery status

Published and verified:
- package metadata (`pyproject.toml`), ignore rules, validation notes and recovery reports;
- all 42 Python modules and 26 Python test files from the recovered source snapshot, including the remote PIR fail-closed guard and its regression tests;
- architecture, threat model, roadmap, protocol, onion, PIR and sharing design notes, plus the recovered changelog, examples, experiment outputs, checksum manifests and validation reports;
- `AEGIS-consolidated-recovery-2026-10-09.zip`, which contains selected research ZIPs, a recoverable Git baseline bundle and status/checksum files;
- GitHub Actions workflow at `.github/workflows/recovery-validation.yml`, which verifies the archive checksum and nested ZIPs, extracts the v0.27.4 source snapshot, compiles the source/tests, and runs pytest.

**The consolidated ZIP is not the full-history recovery archive.** It contains the v0.27.4 research snapshot, which was verified to match the recovered 246-file source tree exactly. It also contains selected older/research snapshots, not every historical artifact.

Still unresolved:
- eight existing files have content differences from the recovered snapshot and require a deliberate diff review; they were not overwritten automatically;
- the separate full-history recovery archive (29 MB) has not been uploaded as an independent GitHub release asset;
- the historical original Git commit graph was not reconstructed.

The Python source/test checkout is complete enough to install and test. The recovery workflow validates both the archived snapshot and the checked-out Git source, including package installation, console entry points, compilation, and pytest.

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

## Tracked work and CI status

The remaining blockers are tracked explicitly:
- [Issue #1 — publish the full recovered source tree and validate package installation](https://github.com/LU9DI/AEGIS/issues/1).
- [Issue #2 — make PIR responses verifiable against malicious replicas](https://github.com/LU9DI/AEGIS/issues/2).

The CI workflow runs on every push to `main`, pull requests, and manual dispatch. It validates archive checksums, extracts the recovered snapshot, applies the explicit remote-PIR safety overlay, installs the package, checks dependencies and console scripts, compiles code, and runs the complete test suite against both the recovered snapshot and the checked-out source. Check the latest [GitHub Actions runs](https://github.com/LU9DI/AEGIS/actions) for the current result.

## Security caveats

AEGIS is being developed as a real anonymity-network product intended for production use, not merely as a research archive or hobby project. It is currently under construction and testing and is **not yet production-ready or independently audited**. Remote PIR retrieval is refused by default because TLS does not prove correct PIR computation; callers can explicitly opt into unverified research mode, which remains unsafe for sensitive data. The two-server XOR PIR prototype assumes non-colluding replicas; colluding replicas can recover the requested index. The four-server consistency check is not a cryptographic proof of correct computation and cannot prevent collusion or common-mode failures. Garlic-clove delivery/batching semantics are not implemented. The relay testbed and RPC/TLS demos do not establish security on a live multi-operator network. The cryptographic verifiable-PIR blocker remains tracked in [Issue #2](https://github.com/LU9DI/AEGIS/issues/2).

Simulator outputs and route-selection examples are hypothetical or synthetic, not measurements of Tor or a live network. **Until the required protocol, network, and independent security validation gates have passed, do not use the current implementation for sensitive or production communications.**

## Recovery integrity

Historical ZIP snapshots are not a reconstructed original Git commit graph. The recovered Git bundle contains a recovery baseline, not all original commits. Missing artifacts and checksum discrepancies are documented in `recovery/`. Keep an independent copy of the recovery archives outside this repository and outside temporary workspaces.
