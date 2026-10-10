# MALEBOLGE v0.9.0 validation record

Validation was run on the Linux research environment with Python 3.13.

- `python -m compileall -q src tests`: passed.
- `PYTHONPATH=src python -m unittest discover -s tests -v`: **82 tests passed**.
- `PYTHONPATH=src python -m anonlab.directory_demo`: passed; state reload, descriptor rollback rejection, revocation, and route invalidation all reported true.
- Wheel built with `python -m pip wheel . --no-deps --no-build-isolation`.
- Wheel installed into a fresh virtual environment and the installed package reported version `0.9.0`.
- Installed `rea-anon-directory-demo` entry point passed the same assertions.

All network demonstrations remain IPv4-loopback-only. These checks are software regression evidence, not a cryptographic audit or proof of anonymity.
