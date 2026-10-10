# MALEBOLGE v0.12.0 validation report

## Automated checks

- Source tree: `python -m pytest -q` — **97 passed, 11 subtests passed**.
- `python -m compileall -q src tests` — passed.
- Source release ZIP extracted to a clean directory and tested again: **97 passed, 11 subtests passed**.
- Wheel built with the installed setuptools backend using `pip wheel --no-deps --no-build-isolation`.
- Wheel installed into a fresh virtual environment with system cryptography available; installed module and distribution both report version `0.12.0`.
- Installed `rea-anon-lab --help` and `rea-anon-directory-demo` commands both executed successfully.

## New behavior covered

- Concurrent `request_echo()` calls on one circuit are serialized over the single request/response channel.
- A newer signed revocation epoch invalidates a live verified route before an application DATA command reaches the exit.
- Idle expiry and maximum circuit lifetime close the client before a subsequent DATA command is sent.
- Zero, negative, infinite and NaN lifecycle limits are rejected.
- Existing tests for directory signatures, revocation, peer authorization, circuit extension, nonce replay rejection, payload integrity and resource cleanup continue to pass.

## Interpretation and limitations

These are functional checks in a loopback-only lab. They do not demonstrate public-network performance, traffic-analysis resistance, global replay resistance or production anonymity. The client uses lazy idle expiration (checked at the next operation), and a single circuit serializes all requests because the current wire protocol does not provide stream identifiers or response demultiplexing. Persistent trust state still cannot independently detect restoration of an older valid state file without an external freshness witness. No independent cryptographic audit has been performed.
