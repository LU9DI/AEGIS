# MALEBOLGE v0.10.0 validation record

Date: 2026-10-09 (UTC date; local research environment)

## Source tests

Command:

```bash
python -m pytest -q
```

Result:

```text
86 passed, 7 subtests passed
```

The same command was run twice: once from the working source tree and once from the root of `MALEBOLGE-research-lab-v0.10.0` after extracting the distributable ZIP. Both runs passed with the same result.

## Packaging

- Built wheel without network access or build isolation using locally installed setuptools:
  `python -m pip wheel . --no-deps --no-build-isolation -w /mnt/data/wheel-build-v0.10.0`
- Wheel: `rea_anon_lab-0.10.0-py3-none-any.whl`
- SHA-256: `24a83fff09f7848bf059e15358060a81aa864009184493dd3d356ce9c56728dc`
- Installed the wheel into a fresh virtual environment using `pip install --no-deps`.
- Confirmed `importlib.metadata.version("rea-anon-lab") == "0.10.0"` and `anonlab.__version__ == "0.10.0"`.
- Executed installed `rea-anon-directory-demo`; its checks for descriptor signature, key rotation, persistent state reload, rollback rejection, revocation, and route invalidation passed.
- Executed installed `rea-anon-telescope-bench --help` successfully.

## Authenticated-link test coverage

The 86-test suite includes:

- Signed-directory three-hop route builds with identity public keys carried into the circuit descriptors.
- Client authenticates the guard without exposing a client identity.
- Middle and exit relays authenticate the preceding relay's identity-key possession on their immediate inbound link.
- A guard rejects a response signed by the wrong target identity before sending CREATE.
- A relay rejects an initiating-relay signature altered in transit and does not claim the replay nonce.
- Replayed link-authentication nonces are rejected on a second TCP connection.
- Relay identity digest/public-key mismatch is rejected.

## Environment and limits

The test environment used Python 3.13.5, `cryptography` 46.0.4, and locally installed setuptools 82.0.1. All network tests are restricted to `127.0.0.1`.

These tests establish the listed local software invariants only. They do not demonstrate production security, transport confidentiality, resistance to a global observer, or anonymity against colluding relays. In particular, a receiving relay verifies the initiating relay's proof of key possession and digest/key binding, but does not yet validate the initiator's directory-authority certification or revocation status. The process-local replay guard can be exhausted and resets on restart. The custom MALEBOLGE key schedule and the link-authentication protocol require independent review before any distributed deployment.
