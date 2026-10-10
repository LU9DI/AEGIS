# AEGIS snapshot reconciliation — 2026-10-10

**Repository:** https://github.com/LU9DI/AEGIS  
**Reviewed baseline:** recovered v0.27.4 source snapshot (246 files)  
**Current branch:** `main`  
**Purpose:** record why eight pre-existing files were preserved rather than overwritten during source recovery.

## Decision summary

The recovered archive is an important forensic baseline, not an instruction to replace newer or security-hardened files byte-for-byte. The eight paths below were compared at the role/content level and the current Git versions are retained as canonical. This means the Git tree is **not byte-identical** to the historical snapshot by design; the archive remains available for reproducibility.

| Path | Decision | Reason |
|---|---|---|
| `docs/ARCHITECTURE.md` | Keep current Git version | It records the current research architecture and the phase gates; preserve the mainline narrative rather than replace it solely to match archive bytes. |
| `docs/MALEBOLGE_CHARTER.md` | Keep current Git version | The charter states the explicit research-only status, limitations, and gates before distributed use. |
| `docs/NTOR_HANDSHAKE_EXPERIMENT.md` | Keep current Git version | It preserves the custom-KDF, directory-trust, replay/DoS, and no-production-use caveats for the isolated handshake experiment. |
| `docs/TELESCOPING_EXTENSION_DESIGN.md` | Keep current Git version | It retains the design/POC boundary, hop knowledge limits, relay-authentication gaps, and acceptance gates. |
| `docs/THREAT_MODEL.md` | Keep current Git version | It explicitly distinguishes browser tracking, local observers, malicious relays, collusion, and global observers, and labels current evidence as prototype-level. |
| `src/anonlab/pir_rpc_demo.py` | Keep current Git version | It explicitly labels the demo as loopback research, unencrypted in legacy HMAC mode, not a live remote test, and not a security proof. |
| `src/anonlab/pir_two_server.py` | Keep current Git version | It retains bounded input validation and explicit non-collusion assumptions; changing it just to match the archive would risk losing current safeguards. |
| `tests/test_pir_two_server.py` | Keep current Git version | The current suite covers retrieval correctness, target-independent per-server masks, collusion disclosure, fixed-size messages, invalid inputs, and resource bounds. |

## Verification

- The recovered snapshot archive remains preserved and checksum-identified; no archive files were overwritten.
- PR #5 published the missing source/test/research artifacts as normal Git files.
- PR #6 added a stricter PIR fail-closed boundary and regression tests; see https://github.com/LU9DI/AEGIS/pull/6.
- The PR #6 validation passed: 233 tests and 76 subtests in the checked-out Git source, and 230 tests plus 76 subtests in the recovered snapshot.
- Post-merge CI on `main` passed for the PIR hardening commit: https://github.com/LU9DI/AEGIS/actions/runs/38067902796.
- The consolidated recovery ZIP is published in the repository. The separate 29 MB full-history recovery ZIP is a distinct artifact; this report does not claim it was uploaded independently.

## Remaining security boundary

This reconciliation closes the **source publication/reconciliation** work only. It does not close the cryptographic PIR issue. Remote PIR retrieval is disabled for all non-loopback endpoints until a privacy-preserving proof of correct computation is integrated and independently reviewed. Two-server XOR-PIR still leaks the queried index if both replicas collude. AEGIS remains a research prototype, not production-ready anonymity software.
