# AEGIS / MALEBOLGE — Recovery status

Date: 2026-10-09 (working session timestamps may be displayed in UTC on GitHub).

## Current GitHub publication status

The repository `LU9DI/AEGIS` is no longer empty. A recovery baseline and a subset of files have been published on `main`. This is **not** a complete mirror of the recovered source or archives.

Published subset includes:
- package metadata and ignore rules;
- research simulator modules;
- local two-server XOR PIR and XOR secret-sharing prototype modules with selected tests;
- architecture notes, validation report, recovery audit, checksum audit, and archive inventory.

Still missing from GitHub:
- the remaining source modules and most of the tests;
- complete experiments, docs, changelog, and reports from the recovered tree;
- all historical ZIPs, wheels, bundle and the full-history recovery ZIP as binary assets;
- complete per-file checksum inventory.

## Local recovery facts

- Recovered source baseline declares package version 0.26.0.
- Latest recovered source archive v0.27.4 was reported to match a 246-file source tree exactly.
- Full-history recovery ZIP: `AEGIS-FULL-HISTORY-RECOVERY-2026-10-09.zip`; SHA-256: `8b0f01c8b54e356234dab4920e228af98fe3f63b06ecbd0060906626ed7265c2`.
- ZIP integrity was checked locally; the archive contains 458 entries.
- Checksum audit: 36 manifests, 120 records, 110 exact matches, 8 unavailable historical v0.22.0 wheel byte variants, 2 missing ancillary outputs.
- Full pytest result reported for the recovered tree: 227 tests and 76 subtests passed in 28.50 seconds.

## Recovery caveats

Historical ZIPs preserve snapshots, not the original Git commit graph. Work that existed only in a deleted conversation and was never written to a file cannot be recreated from these archives. Keep an independent copy of the ZIP outside the temporary session environment.

## Security caveats

AEGIS remains a research prototype, not an audited production anonymity system. The four-server PIR consistency check detects some disagreement, but is not a cryptographic proof of correct PIR computation and cannot prevent collusion or common-mode faults.
