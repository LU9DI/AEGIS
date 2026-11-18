# THOR measurement report — 20261118T195525-lab-20261118

- **Tier**: `lab`
- **Run id**: `20261118T195525-lab-20261118`
- **Seed**: `20261118`
- **Revision**: `1aa9130539a30c7ab7c62f116b4fa8771709c584` (dirty: `False`)
- **Environment**: Python 3.14.6 on Windows-10-10.0.19045-SP0; 4 logical CPUs; cryptography 50.0.2
- **Configuration digest**: `b2e001db92303bb5d76c368985a252c36104708e4af0f0faed1254a6a2f942bf`
- **Raw trials**: 144 records (18 warmup, 0 errors), digest `88220ea1f296d89e…`

> All endpoints are IPv4 loopback on one host inside one Python process. These numbers are **not** WAN performance, **not** Tor performance and do not establish anonymity. They isolate implementation cost under identical origin, destination, payload, duration and (absent an explicit link profile) network conditions.

## Target gate: AEGIS goodput ≥ 90% of Surface

| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |
|---|---|---|---|---|---|
| `bulk_echo:1048576x1@c16384i4` | `aegis_telescope3` | 7 | 0.100 [0.088, 0.112] | 9.03 | **not_met** |
| `bulk_echo:1048576x1@c16384i4` | `relay3_plain` | 7 | 0.465 [0.370, 0.485] | 1.94 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `aegis_telescope3` | 7 | 0.173 [0.144, 0.450] | 5.20 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `relay3_plain` | 7 | 0.832 [0.460, 1.174] | 1.08 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `aegis_telescope3` | 7 | 0.160 [0.141, 0.176] | 5.63 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `relay3_plain` | 7 | 0.464 [0.388, 0.535] | 1.94 | **not_met** |
| `bulk_echo:262144x1@c65536i4` | `aegis_telescope3` | 7 | 0.147 [0.124, 0.163] | 6.11 | **not_met** |
| `bulk_echo:262144x1@c65536i4` | `relay3_plain` | 7 | 0.373 [0.243, 0.467] | 2.41 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `aegis_telescope3` | 7 | 0.107 [0.073, 0.125] | 8.39 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `relay3_plain` | 7 | 0.472 [0.363, 0.500] | 1.91 | **not_met** |
| `small_rtt:1024x50@c16384i4` | `aegis_telescope3` | 7 | 0.215 [0.151, 0.262] | 4.20 | **not_met** |
| `small_rtt:1024x50@c16384i4` | `relay3_plain` | 7 | 0.391 [0.261, 0.451] | 2.30 | **not_met** |

## Workload `bulk_echo:1048576x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 7 | 18.84 [17.28, 26.05] | 250.54 | 550.70 | 573.08 | n/a | 28.57 | 1.014 | 1.024 | 0.663 | 48.13 |
| `relay3_plain` | 7 | 98.64 [63.70, 120.46] | 54.51 | 153.09 | 160.43 | n/a | 1.69 | 1.000 | 1.000 | 0.668 | 48.13 |
| `surface` | 7 | 211.90 [181.88, 261.40] | 29.93 | 55.83 | 59.15 | n/a | 1.58 | 1.000 | 1.000 | 0.747 | 48.13 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 7 | 21.90 [15.72, 33.31] | 62.25 | 138.54 | 140.30 | n/a | 25.80 | 1.017 | 1.027 | 0.843 | 48.13 |
| `relay3_plain` | 7 | 90.80 [60.92, 108.45] | 22.42 | 75.61 | 89.72 | n/a | 3.05 | 1.000 | 1.000 | 0.901 | 48.13 |
| `surface` | 7 | 109.14 [33.08, 196.69] | 17.19 | 81.54 | 87.75 | n/a | 2.13 | 1.000 | 1.000 | 0.889 | 48.13 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c262144i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 7 | 37.77 [25.91, 41.75] | 22.51 | 93.50 | 97.81 | n/a | 25.50 | 1.007 | 1.018 | 0.644 | 48.13 |
| `relay3_plain` | 7 | 105.21 [84.73, 128.17] | 19.21 | 41.75 | 47.58 | n/a | 2.08 | 1.000 | 1.000 | 0.612 | 48.13 |
| `surface` | 7 | 236.40 [161.97, 301.47] | 8.13 | 44.44 | 55.24 | n/a | 1.54 | 1.000 | 1.000 | 1.108 | 48.13 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c65536i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 7 | 35.32 [21.74, 37.61] | 26.38 | 109.38 | 113.82 | n/a | 27.91 | 1.009 | 1.019 | 1.025 | 48.13 |
| `relay3_plain` | 7 | 94.33 [55.19, 101.15] | 21.45 | 77.25 | 90.71 | n/a | 2.04 | 1.000 | 1.000 | 0.590 | 48.13 |
| `surface` | 7 | 253.04 [147.23, 265.12] | 7.30 | 16.87 | 17.77 | n/a | 1.61 | 1.000 | 1.000 | 0.000 | 48.13 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `parallel_bulk:8x65536@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 7 | 10.35 [5.29, 12.05] | n/a | 1,555.06 | 1,816.62 | n/a | 229.07 | 1.028 | 1.036 | 0.915 | 48.13 |
| `relay3_plain` | 7 | 47.06 [25.74, 48.63] | n/a | 179.31 | 184.91 | n/a | 7.65 | 1.000 | 1.000 | 0.820 | 48.13 |
| `surface` | 7 | 98.26 [72.34, 100.83] | n/a | 64.70 | 67.00 | n/a | 6.79 | 1.000 | 1.000 | 0.989 | 48.13 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `small_rtt:1024x50@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_telescope3` | 7 | 1.31 [1.14, 1.75] | n/a | 442.44 | 471.02 | 9.39 | 30.36 | 1.181 | 1.350 | 0.900 | 48.13 |
| `relay3_plain` | 7 | 2.91 [1.93, 3.00] | n/a | 268.58 | 288.00 | 5.44 | 1.85 | 1.000 | 1.000 | 0.776 | 48.13 |
| `surface` | 7 | 7.41 [5.39, 7.84] | n/a | 129.20 | 147.46 | 2.53 | 1.48 | 1.000 | 1.000 | 0.835 | 48.13 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Reproducing this artifact

```
python -m anonlab.thor_lab summarize 20261118T195525-lab-20261118
python -m anonlab.thor_lab verify <run-directory>
```

`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.

