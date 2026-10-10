# AEGIS / MALEBOLGE — Checksum Audit

Audit scope: checksum manifests and artifacts included in this recovery bundle.

- Manifests examined: **36**
- Individual checksum records: **120**
- Hashes matched by exact file content: **110**
- Missing standalone artifacts: **2**
- Expected hashes not matched: **8**

## Interpretation

- All included historical source ZIPs passed ZIP integrity testing (no archive corruption reported). The current source snapshot passed its full pytest suite: 227 tests and 76 subtests passed.
- Three v0.23.0 demo JSON files were originally named differently in the checksum manifest than inside the source ZIP. They were recovered by content hash from the v0.23.0 ZIP and saved under the exact expected names; their SHA-256 values match.
- The 8 unmatched records are historical v0.22.0 wheel hashes: multiple separate experimental wheel builds reused the same basename (`rea_anon_lab-0.22.0-py3-none-any.whl`), but those exact byte variants are not present among accessible artifacts. One wheel file exists, but it does not match those expected hashes. This is a preservation gap, not evidence that the source ZIPs are corrupted.
- Two standalone ancillary outputs are not present by their expected content hashes: `malebolge-window-update-timer-wheel-cli-help.txt` and `AEGIS-simulator-smoke-final.json`. Their source code and associated reports/source snapshots are preserved, but the exact historical output files were not recovered.

## Unmatched entries

- `MALEBOLGE-v0.22.0-window-update-timer-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `d52e35fef3aded9c27d55218b87fa7ba86d8cd2c35b79a505fdd46684f70e757`
- `MALEBOLGE-v0.22.0-window-update-timer-SHA256SUMS.txt` — `malebolge-window-update-timer-wheel-cli-help.txt` — expected SHA-256 `d143d559f00fadf5a1e1ff5d7fc987a8ace116f3907acdc29367b13f639b776d`
- `MALEBOLGE-v0.22.0-window-update-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `91fb02d8fb2efc82cfc423a865a8e74ba969dc102dfaef86b65c2e27e2e87eeb`
- `MALEBOLGE-v0.22.0-window-update-timer-cross-profile-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `97c43d7387a6c2532627eb92d3fed634100bfbfe41e8bd9d4efb764e5695e1a5`
- `MALEBOLGE-v0.22.0-write-diagnostics-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `4b36b8b36b72276c7bcf4692571a3910ba45dbc01986e720bdc8eff2c4ccd90e`
- `MALEBOLGE-v0.22.0-mixed-workload-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `38a967fd2477bcb6671d8c92853c440d6ba943df95ca9827e2dba88d9e6e976e`
- `MALEBOLGE-v0.22.0-relay-stage-diagnostics-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `c1b97155746ecfe3c425b1ce77e097d1b02eb76b45c6f4f28a78c32083e77ba5`
- `AEGIS-v0.22.0-brand-migration-SHA256SUMS.txt` — `AEGIS-simulator-smoke-final.json` — expected SHA-256 `2287fc2a97b9a53f1c30143e9dd8a4041b8199bc474287962793194fa92e1e81`
- `MALEBOLGE-v0.22.0-SHA256SUMS.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `2da66050565b6b3a9bca5d7e62c91389d9b0b3aae0c2e39aafc945506c48a94d`
- `MALEBOLGE-v0.22.0-window-update-timer-cross-profile-SHA256SUMS_2.txt` — `rea_anon_lab-0.22.0-py3-none-any.whl` — expected SHA-256 `97c43d7387a6c2532627eb92d3fed634100bfbfe41e8bd9d4efb764e5695e1a5`

This report records the exact accessible-artifact audit. It does not claim every historical build artifact has been recovered.
