# THOR measurement report — 20261118T224635-lab-20261118

- **Tier**: `lab`
- **Run id**: `20261118T224635-lab-20261118`
- **Seed**: `20261118`
- **Revision**: `bbb0e3f4affbe305cd10053e3b980021f5233c1d` (dirty: `False`)
- **Environment**: Python 3.14.6 on Windows-10-10.0.19045-SP0; 4 logical CPUs; cryptography 50.0.2
- **Configuration digest**: `271cac6e78d414f7244c3249a0c00f70eaabdcb3fb0d61ec28f79a96d8e94d4f`
- **Raw trials**: 192 records (24 warmup, 0 errors), digest `c9f3c3e1177b397e…`

> All endpoints are IPv4 loopback on one host inside one Python process. These numbers are **not** WAN performance, **not** Tor performance and do not establish anonymity. They isolate implementation cost under identical origin, destination, payload, duration and (absent an explicit link profile) network conditions.

## Target gate: AEGIS goodput ≥ 90% of Surface

| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |
|---|---|---|---|---|---|
| `bulk_echo:1048576x1@c16384i4` | `aegis_combined` | 7 | 0.105 [0.095, 0.118] | 8.58 | **not_met** |
| `bulk_echo:1048576x1@c16384i4` | `aegis_io_batch` | 7 | 0.117 [0.081, 0.142] | 7.66 | **not_met** |
| `bulk_echo:1048576x1@c16384i4` | `aegis_lean_dispatch` | 7 | 0.115 [0.092, 0.148] | 7.82 | **not_met** |
| `bulk_echo:1048576x1@c16384i4` | `aegis_telescope3` | 7 | 0.123 [0.102, 0.130] | 7.34 | **not_met** |
| `bulk_echo:1048576x1@c16384i4` | `relay3_plain` | 7 | 0.460 [0.416, 0.473] | 1.96 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `aegis_combined` | 7 | 0.146 [0.102, 0.206] | 6.15 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `aegis_io_batch` | 7 | 0.156 [0.097, 0.184] | 5.75 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `aegis_lean_dispatch` | 7 | 0.155 [0.108, 0.179] | 5.81 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `aegis_telescope3` | 7 | 0.133 [0.099, 0.177] | 6.77 | **not_met** |
| `bulk_echo:262144x1@c16384i4` | `relay3_plain` | 7 | 0.370 [0.332, 0.581] | 2.43 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `aegis_combined` | 7 | 0.123 [0.112, 0.143] | 7.30 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `aegis_io_batch` | 7 | 0.129 [0.104, 0.158] | 6.97 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `aegis_lean_dispatch` | 7 | 0.130 [0.127, 0.143] | 6.93 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `aegis_telescope3` | 7 | 0.131 [0.117, 0.140] | 6.85 | **not_met** |
| `bulk_echo:262144x1@c262144i4` | `relay3_plain` | 7 | 0.340 [0.302, 0.406] | 2.65 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `aegis_combined` | 7 | 0.112 [0.107, 0.131] | 8.04 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `aegis_io_batch` | 7 | 0.116 [0.099, 0.148] | 7.74 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `aegis_lean_dispatch` | 7 | 0.126 [0.107, 0.139] | 7.16 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `aegis_telescope3` | 7 | 0.120 [0.106, 0.143] | 7.52 | **not_met** |
| `parallel_bulk:8x65536@c16384i4` | `relay3_plain` | 7 | 0.554 [0.434, 0.686] | 1.62 | **not_met** |

## Workload `bulk_echo:1048576x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_combined` | 7 | 33.14 [31.16, 36.29] | 152.16 | 352.16 | 380.58 | n/a | 21.97 | 1.014 | 1.024 | 0.948 | 49.67 |
| `aegis_io_batch` | 7 | 35.00 [29.26, 41.21] | 137.50 | 405.80 | 446.63 | n/a | 23.74 | 1.014 | 1.024 | 0.956 | 49.67 |
| `aegis_lean_dispatch` | 7 | 33.65 [28.69, 39.65] | 137.81 | 294.42 | 295.11 | n/a | 22.16 | 1.014 | 1.024 | 0.930 | 49.67 |
| `aegis_telescope3` | 7 | 37.36 [27.87, 40.67] | 126.19 | 363.60 | 385.07 | n/a | 23.02 | 1.014 | 1.024 | 0.927 | 49.67 |
| `relay3_plain` | 7 | 147.83 [95.76, 158.79] | 38.92 | 88.32 | 88.56 | n/a | 1.28 | 1.000 | 1.000 | 0.979 | 49.67 |
| `surface` | 7 | 312.42 [227.31, 350.88] | 20.17 | 39.26 | 40.06 | n/a | 1.34 | 1.000 | 1.000 | 0.934 | 49.67 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_combined` | 7 | 36.97 [30.28, 40.03] | 37.62 | 79.08 | 82.45 | n/a | 21.05 | 1.017 | 1.027 | 0.983 | 49.67 |
| `aegis_io_batch` | 7 | 34.85 [26.80, 41.51] | 39.41 | 84.74 | 86.97 | n/a | 23.17 | 1.017 | 1.027 | 0.806 | 49.67 |
| `aegis_lean_dispatch` | 7 | 36.56 [30.65, 39.29] | 36.41 | 70.45 | 71.14 | n/a | 24.06 | 1.017 | 1.027 | 1.000 | 49.67 |
| `aegis_telescope3` | 7 | 33.62 [27.81, 37.89] | 42.97 | 87.09 | 91.09 | n/a | 23.46 | 1.017 | 1.027 | 0.989 | 49.67 |
| `relay3_plain` | 7 | 111.49 [85.49, 128.60] | 17.42 | 24.85 | 24.95 | n/a | 1.80 | 1.000 | 1.000 | 0.732 | 49.67 |
| `surface` | 7 | 247.04 [191.75, 305.75] | 6.98 | 13.44 | 14.30 | n/a | 1.58 | 1.000 | 1.000 | 1.004 | 49.67 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c262144i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_combined` | 7 | 50.05 [35.19, 58.74] | 17.92 | 60.87 | 61.31 | n/a | 19.29 | 1.007 | 1.018 | 0.870 | 49.67 |
| `aegis_io_batch` | 7 | 49.43 [44.11, 60.91] | 17.60 | 50.36 | 51.33 | n/a | 17.77 | 1.007 | 1.018 | 0.890 | 49.67 |
| `aegis_lean_dispatch` | 7 | 56.86 [49.57, 60.69] | 16.96 | 50.53 | 53.35 | n/a | 20.56 | 1.007 | 1.018 | 1.035 | 49.67 |
| `aegis_telescope3` | 7 | 56.64 [44.30, 57.67] | 17.79 | 55.30 | 58.03 | n/a | 25.11 | 1.007 | 1.018 | 1.004 | 49.67 |
| `relay3_plain` | 7 | 132.32 [96.26, 164.85] | 15.05 | 40.75 | 47.25 | n/a | 1.54 | 1.000 | 1.000 | 0.932 | 49.67 |
| `surface` | 7 | 406.02 [353.90, 446.08] | 4.33 | 6.58 | 6.80 | n/a | 1.12 | 1.000 | 1.000 | 0.917 | 49.67 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `parallel_bulk:8x65536@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_combined` | 7 | 14.70 [12.76, 16.09] | n/a | 438.16 | 475.66 | n/a | 148.30 | 1.028 | 1.036 | 0.953 | 49.67 |
| `aegis_io_batch` | 7 | 14.03 [12.61, 16.66] | n/a | 416.21 | 444.91 | n/a | 145.97 | 1.028 | 1.036 | 0.939 | 49.67 |
| `aegis_lean_dispatch` | 7 | 14.46 [12.66, 15.65] | n/a | 365.27 | 376.91 | n/a | 132.63 | 1.028 | 1.036 | 0.926 | 49.67 |
| `aegis_telescope3` | 7 | 13.64 [12.21, 16.17] | n/a | 385.80 | 400.27 | n/a | 168.39 | 1.028 | 1.036 | 0.938 | 49.67 |
| `relay3_plain` | 7 | 59.50 [56.38, 63.92] | n/a | 87.58 | 92.09 | n/a | 7.04 | 1.000 | 1.000 | 0.986 | 49.67 |
| `surface` | 7 | 115.06 [80.66, 131.86] | n/a | 61.19 | 64.34 | n/a | 6.89 | 1.000 | 1.000 | 0.852 | 49.67 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Reproducing this artifact

```
python -m anonlab.thor_lab summarize 20261118T224635-lab-20261118
python -m anonlab.thor_lab verify <run-directory>
```

`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.

