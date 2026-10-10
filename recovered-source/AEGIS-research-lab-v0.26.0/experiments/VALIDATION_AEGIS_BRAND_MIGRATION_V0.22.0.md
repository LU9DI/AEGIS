# AEGIS brand migration — validation record (v0.22.0)

## Scope

This change updates project-facing identity from MALEBOLGE to **AEGIS — Anonymous Encrypted Garlic-routed Internet Shield**. It does not claim garlic routing is implemented, does not change protocol version, and does not promote experimental performance settings.

## Change summary

- Python distribution metadata renamed to `aegis-anon-lab`.
- Canonical simulation CLI is `aegis`; AEGIS-prefixed aliases were added for all 19 existing `rea-anon-*` console scripts. The 19 legacy scripts remain available.
- Internal import namespace remains `anonlab` to avoid an unnecessary breaking import change.
- Updated README, changelog, public-facing code descriptions, generated benchmark metadata, and this transition record.
- Historical experiment JSON and reports retain their historical MALEBOLGE labels to preserve provenance.
- Legacy cryptographic v1 domains, AAD prefixes, relay-identity hashing domain, directory protocol identifier `malebolge-lab-ntor-v1`, and KDF info context were deliberately preserved. Renaming those byte strings would change protocol identity/authentication/key derivation and requires a separately versioned migration.

## Verification

- `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -q`: **160 tests passed**, no `ResourceWarning` (24.507 s).
- `PYTHONPATH=src pytest -q`: **162 tests passed, 23 subtests passed** (25.00 s).
- Branding regression tests verify the canonical CLI name, AEGIS simulator metadata, 19 legacy-script mappings, matching AEGIS aliases, and preservation of protocol v1 domain identifiers.
- Wheel built using locally installed setuptools with `python -m pip wheel . --wheel-dir /mnt/data/aegis-wheel-v0.22.0 --no-deps --no-build-isolation` because the environment does not have the `build` module and package-network access is not assumed.
- Built wheel: `aegis_anon_lab-0.22.0-py3-none-any.whl`, SHA-256 `dc42748024ef6e3dc4857d6c76597783cbd0ca135e137a0cd53949a66505767e`.
- Wheel installed into a fresh virtual environment. `aegis --help`, `aegis-network-impairment-bench --help`, `aegis-window-update-timer-bench --help`, `rea-anon-lab --help`, and `rea-anon-window-update-timer-bench --help` all ran successfully.
- Installed CLI smoke test produced five simulator profile results. Metadata identified AEGIS and explicitly reported `is_live_network_test=false` and `is_security_proof=false`.

## Limitations and compatibility

This is a local source/package change only; no remote repository was pushed or modified by this packaging step. The protocol remains custom, experimental and unaudited. The current relay implementation does not yet implement garlic-clove bundling/delivery semantics. Loopback experiments do not prove performance on a real WAN, resistance to a global passive observer, or production anonymity.
