# THOR measurement report — 20261118T195633-public-20261118

- **Tier**: `public`
- **Run id**: `20261118T195633-public-20261118`
- **Seed**: `20261118`
- **Revision**: `1aa9130539a30c7ab7c62f116b4fa8771709c584` (dirty: `False`)
- **Environment**: Python 3.14.6 on Windows-10-10.0.19045-SP0; 4 logical CPUs; cryptography 50.0.2
- **Configuration digest**: `8a2b930e052d601fd9830d6c4c82039d70f47f657f3272eff333656d93c2f7a3`
- **Raw trials**: 12 records (2 warmup, 0 errors), digest `ced15accc8fa926e…`

> Real public-network endpoints over the local access link. Results depend on this host's ISP, time of day and the remote server, and Tor's path changes per connection. They are a baseline for the Surface/Tor gap on this machine, not a property of the networks in general.

## Target gate: AEGIS goodput ≥ 90% of Surface

| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |
|---|---|---|---|---|---|
| `http_get:1xcachefly.cachefly.net/1mb.test` | `tor_socks` | 5 | 0.217 [0.130, 1.858] | 4.15 | **not_met** |

## Workload `http_get:1xcachefly.cachefly.net/1mb.test`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `surface` | 5 | 5.95 [0.83, 17.74] | 136.32 | 2,504.59 | 2,512.72 | 352.54 | 1.37 | 0.001 | 1.002 | 0.000 | 32.36 |
| `tor_socks` | 5 | 1.58 [1.19, 2.31] | 324.57 | 1,682.99 | 1,740.84 | 1,326.09 | 330.42 | 0.001 | 1.002 | 0.019 | 32.48 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Reproducing this artifact

```
python -m anonlab.thor_lab summarize 20261118T195633-public-20261118
python -m anonlab.thor_lab verify <run-directory>
```

`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.

