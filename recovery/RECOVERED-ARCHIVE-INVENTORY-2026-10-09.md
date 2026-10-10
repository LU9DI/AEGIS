# Recovered AEGIS / MALEBOLGE archive inventory

Date: 2026-10-09. The hashes below were calculated from files in the current working session. This inventory is a checksum reference; it does not embed the binary archives themselves.

## Main recovery packages

| Artifact | SHA-256 |
|---|---|
| `AEGIS-FULL-HISTORY-RECOVERY-2026-10-09.zip` | `8b0f01c8b54e356234dab4920e228af98fe3f63b06ecbd0060906626ed7265c2` |
| `AEGIS-consolidated-recovery-2026-10-09.zip` | `ae59e83cf68caebdebeb7522dd36c0bc16f9bbe288bbff1ce99bd7880c659be3` |
| `AEGIS-local-recovery-history.bundle` | `b607f2474c6ee27d88d1281b03019e69e7af065673fed25bacf307026c5b45c2` |
| `AEGIS-research-lab-v0.26.0-pir-ops.zip` | `fb423c7074c2ba7c98fdf703eca406865dffaa2bb1e796435c89b36e05acba1c` |

## Research snapshots

| Artifact | SHA-256 |
|---|---|
| `AEGIS-v0.26.0-verifiable-PIR-design.zip` | `e0b423add94930c2eb00e473593cd8fe5e020df2ae87cd614c52f82544d96310` |
| `AEGIS-v0.27.0-signed-snapshot-manifests-research.zip` | `b78ed3e50498679e05ec48be1bd9becbbfa0c553e979b68a8bef0e63ff980527` |
| `AEGIS-v0.27.0-verifiable-PIR-research.zip` | `e6a8e2e88f4644ff907d0b4662ce813a1e5e6c4b618ccd442bb1d72656a43208` |
| `AEGIS-v0.27.1-persistent-checkpoint-research.zip` | `fb1e39da32061316a3801a10d0d346b884597b1ac1b74a2c345f0acd95a83325` |
| `AEGIS-v0.27.2-pinned-snapshot-rpc-research.zip` | `151f3edd424266b39d0691030e18eff4056280f19bbc45147b3d8144bd0a2369` |
| `AEGIS-v0.27.3-adversarial-PIR-characterization-research.zip` | `ee54a3c6db474d1c126108b259179b9fdd552514b502cb35474496e3f5d6b95f` |
| `AEGIS-v0.27.4-four-server-fault-detection-research.zip` | `0c8e8c8e4ad49c36cea1db3c39c6a2fc53d719b98eb3d361ed5a579af51dc375` |

## Known integrity and completeness caveats

- The full-history ZIP contains 458 archive entries and was checked locally. Its SHA-256 is the value above.
- The latest source snapshot was reported as 246 tracked files. The publish-stage export currently contains 233 files excluding caches/bytecode; do not confuse these counts.
- The recovery audit found 36 manifests with 120 checksum records: 110 matched, 8 historical v0.22.0 wheel variants were unavailable, and 2 ancillary outputs were missing by expected hash.
- The original historical Git commit graph was not recovered. The local bundle is a recovery baseline, not a reconstructed full history.
- The GitHub repository contains only the source files and reports listed in the README's current status; the ZIP archives and bundle are not yet hosted as GitHub binary assets.
- v0.27.x are research snapshots, not declared official releases. The package metadata identifies v0.26.0.
