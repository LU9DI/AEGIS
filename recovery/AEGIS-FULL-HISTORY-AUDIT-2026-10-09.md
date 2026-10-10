# AEGIS / MALEBOLGE — Full History Recovery Bundle

Audit date: 2026-10-09 (environment timestamps may display as 2026-10-10 UTC)

## Contents

- `current-source/`: source tree exported from local recovery commit `8808fed841252ac96472a3e4babd79a3e4a906e4`, 246 tracked files. Its `pyproject.toml` declares package version 0.26.0; the later v0.27.x archives are research snapshots, not declared official releases.
- `library-artifacts/`: project-lineage artifacts recovered from the ChatGPT Library and accessible conversation files, including the original `rea-anon-lab` name, historical source ZIPs, wheels, reports, JSON experiment outputs, validation records, checksum files, and earlier recovery artifacts. Identical duplicate materializations were removed; distinct versioned snapshots were retained.
- `git-history/AEGIS-local-recovery-history.bundle`: transportable Git bundle for the recovered source baseline.

## Historical coverage found

Source ZIP snapshots found across the accessible Library and conversation artifacts include the original `rea-anon-lab-v0.1.zip`, `rea-anon-lab-v0.3.0.zip`, MALEBOLGE v0.3.0, v0.4.0, v0.5.0, v0.7.0 through v0.21.0, several incremental v0.22.0 snapshots, AEGIS v0.22.0 through v0.26.0, and research snapshots v0.27.0 through v0.27.4. Historical wheels and standalone reports/results for many versions have also been added. The source ZIPs cover the earliest recovered snapshot at v0.1 and continue through v0.27.4, with gaps explicitly listed below.

## Explicit gaps / caveats

- No v0.2 source ZIP or v0.6 source ZIP was found in the accessible Library/conversation artifacts. A v0.1 ZIP does exist. “Not found” does not prove that a missing version never existed elsewhere.
- Checksum audit of 36 manifests (120 records): 110 records match, 8 refer to unavailable historical v0.22.0 wheel byte variants, and 2 standalone ancillary outputs are missing. The exact missing outputs are documented in `CHECKSUM-AUDIT.md`. Three v0.23.0 demo JSON outputs were recovered by exact hash from the source ZIP under their original expected names.
- The earlier conversation was deleted. Artifacts can preserve source and documented decisions, but cannot restore instructions, design discussion, or work that existed only in that conversation and was never written to a file.
- The recovered Git history has one baseline commit. Historical ZIPs are snapshots, not reconstructed commit-by-commit history; authorship, branches, and exact intervening diffs are unavailable unless recovered elsewhere.
- All 44 included nested ZIP archives passed `unzip -t`; the current source snapshot has 246 tracked files. Full pytest: 227 passed and 76 subtests passed in 28.50 seconds.
- The GitHub repository `LU9DI/AEGIS` was checked: no branches, files, or commits are currently present. This bundle has not been pushed to GitHub.
- Uploading the expanded bundle and revised audit back into the persistent ChatGPT Library was attempted, but the platform rejected uploads due to its daily upload limit. The expanded ZIP and revised reports are verified in the current session and linked in the accompanying response; the older Library copy remains unchanged until a future upload is allowed.
- Full pytest verification completed on the exported `current-source/` tree: **227 passed, 76 subtests passed in 28.50 seconds**. The successful run used `PYTHONPATH=src python -m pytest -vv --disable-warnings --maxfail=1`.
- AEGIS remains a research prototype. The project documentation itself states that garlic-clove semantics are not implemented and the protocol is unaudited. The four-server PIR consistency check is not a cryptographic proof of correct PIR computation and does not defeat collusion or common-mode failures.

## Recovery principle

Treat this as the broadest recoverable archive assembled from the currently accessible local project and ChatGPT Library artifacts—not as proof that every item from every deleted conversation has been recovered. Keep an independent copy outside ChatGPT's temporary workspace.
