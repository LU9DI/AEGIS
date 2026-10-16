# AEGIS / MALEBOLGE — recovered research archive

**AEGIS** stands for **Anonymous Encrypted Garlic-routed Internet Shield**. This repository contains recovered research code and is not a production anonymity network.

The v0.27.4 recovered Python source, tests, design documents, examples, experiment results, and reports are now published as normal Git files. The repository also retains the consolidated recovery ZIP. Eight pre-existing files intentionally differ from the snapshot and were preserved rather than overwritten; their reconciliation is tracked in [Issue #1](https://github.com/LU9DI/AEGIS/issues/1). The original historical Git commit graph has not been reconstructed.

## Run AEGIS locally (quick start)

This section is the shortest path from a fresh checkout to an executable local run. It separates the **simulator** from the **real loopback testbeds**: neither is a public anonymity service, and neither should receive sensitive traffic.

> **Warning:** AEGIS is an unaudited research prototype. Do not route personal, sensitive or production traffic through it, and do not expose its relays to the Internet.
>
> **Version note:** the recovered snapshot, reports and design notes are labelled **v0.27.4**, but the package metadata (`pyproject.toml`, `anonlab.__version__`) and `CHANGELOG.md` still report **0.26.0**. `pip show aegis-anon-lab` will therefore print 0.26.0. This mismatch is known and not yet reconciled.

### 1. Requirements

- Python 3.11 or newer.
- Git, and a terminal opened at the repository root.
- Internet access only to install Python packages.

### 2. Install

**Windows (PowerShell):**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[onion-lab]"
python -m pip install pytest
```

If PowerShell blocks activation, run the commands below using `.\.venv\Scripts\python.exe` instead of activating the environment.

**Linux / macOS:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[onion-lab]"
python -m pip install pytest
```

The optional `onion-lab` extra installs the `cryptography` dependency used by experimental encrypted-onion and handshake demos. The core simulator and raw TCP relay benchmark do not require that extra, but installing it enables more of the research tools.

### 3. Run the simulator

This is a deterministic model, not a network connection. It writes a JSON report you can inspect or feed into your own analysis.

```bash
aegis --duration 30 --request-rate 1.4 --seed 20261009 --output results/simulation.json
```

The output explicitly marks `is_live_network_test: false` and `is_security_proof: false`. To see the available options, run `aegis --help`.

### 4. Run a real local TCP relay-chain benchmark

This starts an echo destination and multiple relay processes on `127.0.0.1`, transfers payloads through them, checks data integrity and emits a provenance-rich JSON artifact. It does **not** send traffic over the Internet.

```bash
python scripts/run_transport_baseline.py --hops 3 --bytes 4000000 --trials 5 --latency-samples 100 --timeout 300
```

The runner creates a timestamped file under `experiments/baselines/` by default and refuses to overwrite an existing artifact. To run a smaller smoke test:

```bash
python scripts/run_transport_baseline.py --hops 1 --bytes 65536 --trials 2 --latency-samples 10 --timeout 60
```

To run the same full configuration on GitHub Actions, open **Actions → Transport baseline regression → Run workflow**, select the branch you want to test, and set `full_baseline` to `true`. Download the generated artifact from that run to inspect the JSON evidence. A successful workflow validates this local benchmark; it does not validate anonymity or production security.

**How to read the benchmark numbers.** The goodput and round-trip times measure raw TCP byte forwarding through Python relay processes on one machine (loopback). There is no physical network, and this is the raw TCP relay benchmark, not the experimental encrypted-onion prototype, so it says nothing about anonymity. The numbers are **not** Internet performance, are **not** comparable to Tor or to a direct connection, and a single run is not a stable baseline: transfers within one run can differ by tens of percent, so repeat the run and compare the spread. Compare only runs made on the same machine or runner. Use them to detect regressions in the relay code, not to make performance or privacy claims.

### 5. Run the experimental encrypted-onion benchmark

After installing `.[onion-lab]`, run the current loopback-only onion prototype:

```bash
aegis-onion-bench --help
```

Use the options displayed by that command to choose hop count, payload, trials and output. The prototype uses per-run pre-shared keys and experimental framing; it is **not** a production protocol, has no authenticated key exchange or forward secrecy, and is not safe for sensitive communications.

### 5.1. Experimental ntor-to-AEAD key plumbing (not a deployed handshake)

The lab now has an experimental ntor-style key agreement and the onion relay API can use distinct 32-byte request and response AEAD keys. A regression test derives both keys through the handshake functions and exercises encrypted request/response traffic through a loopback relay.

For a manually configured relay process, `--key-file` supplies the request-direction key. You may additionally pass `--response-key-file` for the separate relay-to-client key. Omitting it preserves legacy same-key lab behavior. These files are test inputs, **not** a secure key-distribution mechanism.

Important remaining gap: the relay CLI does not yet perform ntor with each connecting client, provision per-circuit keys automatically, or remove pre-shared key setup end to end. The ntor transcript/KDF is AEGIS-specific and is not wire-compatible with Tor; it has not received independent cryptographic review. This is integration progress, not a production security claim.

### 5.2. Run the synthetic privacy evaluation harness

Run a reproducible simulation of constrained path selection and a simple website-fingerprinting attacker:

```bash
aegis-privacy-eval --seed 20261014 --output experiments/privacy-eval.json
# Optional fail-able experiment gates:
aegis-privacy-eval --seed 20261014 --max-padding-overhead 0.50 --max-fingerprinting-accuracy 0.60
# Multi-seed stability report (comma-separated, at least two seeds):
aegis-privacy-eval --seed 20261014 --stability-seeds 20261015,20261016,20261017,20261020 --output experiments/privacy-eval.json
```

The harness uses synthetic latency-detour/ASN candidates and synthetic traffic traces. It reports randomized eligible-path selection, a nearest-centroid classifier's holdout accuracy, a chance baseline, and byte overhead for a toy size-bucketing/cover model on the client-to-entry link. It also runs a 20-point sweep across four packet-size buckets and five cover rates, reporting accuracy and byte overhead for each setting so one arbitrary configuration is not mistaken for a successful defense. It refuses to overwrite an existing output file. Optional thresholds are explicit experimental gates: the command exits with status 2 when a configured threshold fails and includes the observed values in its JSON output. Thresholds must be calibrated against a real dataset before being treated as meaningful targets.

Artifact schema 2 (current) adds, on top of schema 1:

- one shared stratified train/test split used by the plain, padded and sweep measurements, recorded with train/test digests and validated at runtime (overlap or out-of-range indices abort the run), so measurements cannot silently train on test data;
- a confusion matrix and per-class precision/recall/f1 for every measured configuration (the legacy `per_class_accuracy` field is preserved);
- `--stability-seeds`, which re-runs the evaluation under extra seeds and reports min/max/mean/pstdev spreads. This is sampling-seed spread only — not a confidence interval and not evidence about real traffic;
- a stricter default AS policy for path selection: candidate paths are rejected whenever any autonomous system appears at more than one path position (entry AS reappearing as a middle relay, entry = exit, repeated middle relay AS, …). Rejections are counted in `as_conflict_rejections` and cross-checked by `selected_paths_with_as_conflict` so a relaxed policy would be visible in the artifact;
- a `not_measured` block naming properties this harness does not measure (real packet captures, latency, throughput), so synthetic model parameters cannot be mistaken for measurements.

**Interpretation limit:** this is a harness smoke test, not a realistic Internet/AS topology model, not Deep Fingerprinting, not a Tor comparison, and not evidence that padding improves anonymity. Synthetic accuracies near 1.0 — and the mid-range dips at one sweep corner — are properties of the toy features and the nearest-centroid classifier, not measurements of a defense. Its value is a reproducible place to plug in trace datasets, calibrated route data, stronger attackers and explicit budget/accuracy targets.

**External trace ingestion (validation only):** the new `anonlab.trace_dataset.load_normalized_jsonl(path)` loader validates normalized JSONL packet traces, rejects duplicate/unknown fields and malformed values, enforces input limits, and records the exact file SHA-256. The format and example are documented in [Normalized external trace dataset format](docs/experiments/NORMALIZED-TRACE-DATASET.md). This loader is not yet wired into the evaluator and does not run an attack on real traces. A group-aware split, documented dataset provenance/licensing, and a stronger attacker are still required before real-trace results can be reported. Do not commit sensitive packet captures or identifying metadata.

### 6. Run the test suite

```bash
python -m pytest -q
```

For only the baseline runner regression tests:

```bash
python -m pytest -q tests/test_transport_baseline_runner.py
```

### What “running AEGIS” means today

- **Runnable now:** the research simulator, local TCP relay benchmark, experimental loopback onion/handshake tools, and automated tests.
- **Not available as a safe public service:** a production-ready multi-operator anonymity network, a browser proxy, a deployable Internet relay network, or cryptographically verifiable remote PIR.
- **Do not expose the research relay to the Internet or route personal/sensitive traffic through it.** The local relay intentionally restricts its bind address to loopback; changing that guard is not a deployment step.

If the goal is a service that real users can rely on, the next engineering stage is not merely hosting this code: it requires a defined client/server product, authenticated relay discovery and key management, protocol threat review, abuse controls, integration and adversarial tests, deployment automation, observability, and independent security review. Until those are implemented and validated, treat this repository as an executable research lab rather than a secure anonymity product.

## Current upload status

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

AEGIS is a research prototype, not a production-ready or independently audited anonymity system. Remote PIR retrieval is refused by default because TLS does not prove correct PIR computation; callers can explicitly opt into unverified research mode, which remains unsafe for sensitive data. The two-server XOR PIR prototype assumes non-colluding replicas; colluding replicas can recover the requested index. The four-server consistency check is not a cryptographic proof of correct computation and cannot prevent collusion or common-mode failures. Garlic-clove delivery/batching semantics are not implemented. The relay testbed and RPC/TLS demos do not establish security on a live multi-operator network. The cryptographic verifiable-PIR blocker remains tracked in [Issue #2](https://github.com/LU9DI/AEGIS/issues/2).

Simulator outputs and route-selection examples are hypothetical or synthetic, not measurements of Tor or a live network. **Do not use this prototype for sensitive or production communications.**

## Recovery integrity

Historical ZIP snapshots are not a reconstructed original Git commit graph. The recovered Git bundle contains a recovery baseline, not all original commits. Missing artifacts and checksum discrepancies are documented in `recovery/`. Keep an independent copy of the recovery archives outside this repository and outside temporary workspaces.
