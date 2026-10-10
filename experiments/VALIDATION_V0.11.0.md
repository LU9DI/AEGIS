# MALEBOLGE v0.11.0 validation

- Full test suite: **92 tests passed** using `PYTHONPATH=src python -m unittest discover -s tests -v`.
- New peer-authorization integration cases: revoked relay rejected before link-auth response; relay outside local allowlist rejected; expired relay certificate rejected; wrong-authority certificate rejected; missing certificate rejected in strict mode.
- End-to-end signed-directory three-hop circuit continues to pass with each relay using its own persistent verifier and authority-signed revocation snapshot.
- Packaging and isolated install status is recorded after wheel build in this artifact release's completion notes.
- Scope remains loopback-only; passing tests validate implemented software checks and are not a security audit or proof of anonymous use on the public internet.

- Wheel built and installed successfully: `rea_anon_lab-0.11.0-py3-none-any.whl`; installed CLI `rea-anon-lab --help` returned successfully.
- Source ZIP extracted into a clean directory and complete test suite passed again.
- Wheel SHA-256: `685036b948d6030d9c67d1605153f386642dcb3648cb56e99bb860ed0eb2424b`.
