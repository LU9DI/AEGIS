# THOR measurement report — 20261118T200149-public-20261119

- **Tier**: `public`
- **Run id**: `20261118T200149-public-20261119`
- **Seed**: `20261119`
- **Revision**: `1aa9130539a30c7ab7c62f116b4fa8771709c584` (dirty: `False`)
- **Environment**: Python 3.14.6 on Windows-10-10.0.19045-SP0; 4 logical CPUs; cryptography 50.0.2
- **Configuration digest**: `f4f704beedd1831b8fb007dd33046eb8bd4cc7e79910ac0e65b3fd2e8eb3882a`
- **Raw trials**: 12 records (2 warmup, 0 errors), digest `46f6a6fcb2b1aa7a…`

> Real public-network endpoints over the local access link. Results depend on this host's ISP, time of day and the remote server, and Tor's path changes per connection. They are a baseline for the Surface/Tor gap on this machine, not a property of the networks in general.

## Target gate: AEGIS goodput ≥ 90% of Surface

| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |
|---|---|---|---|---|---|
| `http_get:1xcachefly.cachefly.net/1mb.test` | `tor_socks` | 5 | 0.172 [0.051, 0.572] | 5.23 | **not_met** |

## Workload `http_get:1xcachefly.cachefly.net/1mb.test`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `surface` | 5 | 11.91 [0.65, 14.05] | 93.35 | 2,642.57 | 3,121.65 | 176.03 | 1.55 | 0.001 | 1.002 | 0.024 | 31.73 |
| `tor_socks` | 5 | 1.91 [0.37, 2.45] | 362.84 | 5,114.89 | 5,557.85 | 1,098.35 | 419.93 | 0.001 | 1.002 | 0.005 | 31.73 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Reproducing this artifact

```
python -m anonlab.thor_lab summarize 20261118T200149-public-20261119
python -m anonlab.thor_lab verify <run-directory>
```

`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.

