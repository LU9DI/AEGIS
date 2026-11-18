# THOR measurement report — 20261118T195613-emulated-20261118

- **Tier**: `emulated`
- **Run id**: `20261118T195613-emulated-20261118`
- **Seed**: `20261118`
- **Revision**: `1aa9130539a30c7ab7c62f116b4fa8771709c584` (dirty: `False`)
- **Environment**: Python 3.14.6 on Windows-10-10.0.19045-SP0; 4 logical CPUs; cryptography 50.0.2
- **Configuration digest**: `4c108effcfd297b1c26fa2da0f7df8356808624719063e1a7e852411960d46f6`
- **Raw trials**: 54 records (9 warmup, 0 errors), digest `d8d567c30265c10b…`

> Loopback plus the repository's user-space link shaper. The shaper models one-way delay, jitter and serialization rate on **byte-stream chunks**, not IP packets: there is no loss, no retransmission model and no queueing discipline. Treat these numbers as a sensitivity study, not a forecast.

## Target gate: AEGIS goodput ≥ 90% of Surface

| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |
|---|---|---|---|---|---|
| `bulk_echo:262144x1@c16384i4` | `aegis_telescope3` | 5 | 0.159 [0.132, 0.218] | 5.66 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `relay3_plain` | 5 | 0.913 [0.747, 0.988] | 0.99 | **met** |
| `bulk_echo:262144x1@c65536i4` | `aegis_telescope3` | 5 | 0.266 [0.213, 0.313] | 3.38 | **not_met** |
| `bulk_echo:262144x1@c65536i4` | `relay3_plain` | 5 | 0.916 [0.731, 1.022] | 0.98 | **met** |
| `small_rtt:1024x20@c16384i4` | `aegis_telescope3` | 5 | 0.760 [0.696, 0.872] | 1.18 | **not_met** |
| `small_rtt:1024x20@c16384i4` | `relay3_plain` | 5 | 0.954 [0.919, 1.004] | 0.94 | **met** |

## Workload `bulk_echo:262144x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 5 | 9.95 [8.07, 12.94] | 127.29 | 257.00 | 259.19 | n/a | 84.00 | 1.017 | 1.027 | 0.341 | 39.69 |
| `relay3_plain` | 5 | 54.28 [44.93, 65.38] | 22.55 | 45.80 | 46.50 | n/a | 1.02 | 1.000 | 1.000 | 0.610 | 39.69 |
| `surface` | 5 | 62.65 [59.43, 66.17] | 21.08 | 35.20 | 35.27 | n/a | 1.52 | 1.000 | 1.000 | 0.430 | 39.69 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c65536i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 5 | 18.44 [11.19, 20.11] | 35.21 | 173.31 | 184.55 | n/a | 83.90 | 1.009 | 1.019 | 0.218 | 39.69 |
| `relay3_plain` | 5 | 53.74 [50.64, 64.00] | 25.76 | 41.34 | 41.40 | n/a | 1.57 | 1.000 | 1.000 | 0.678 | 39.69 |
| `surface` | 5 | 67.02 [52.60, 69.91] | 20.13 | 38.43 | 39.58 | n/a | 1.41 | 1.000 | 1.000 | 0.426 | 39.69 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `small_rtt:1024x20@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 5 | 0.43 [0.34, 0.52] | n/a | 465.55 | 481.09 | 23.68 | 96.18 | 1.212 | 1.375 | 0.252 | 39.69 |
| `relay3_plain` | 5 | 0.56 [0.48, 0.59] | n/a | 339.48 | 343.20 | 17.07 | 0.96 | 1.000 | 1.000 | 0.166 | 39.69 |
| `surface` | 5 | 0.59 [0.47, 0.62] | n/a | 335.36 | 343.46 | 16.48 | 1.23 | 1.000 | 1.000 | 0.000 | 39.69 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Reproducing this artifact

```
python -m anonlab.thor_lab summarize 20261118T195613-emulated-20261118
python -m anonlab.thor_lab verify <run-directory>
```

`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.

