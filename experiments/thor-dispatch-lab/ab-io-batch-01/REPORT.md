# THOR measurement report — 20261118T224714-lab-20261119

- **Tier**: `lab`
- **Run id**: `20261118T224714-lab-20261119`
- **Seed**: `20261119`
- **Revision**: `bbb0e3f4affbe305cd10053e3b980021f5233c1d` (dirty: `False`)
- **Environment**: Python 3.14.6 on Windows-10-10.0.19045-SP0; 4 logical CPUs; cryptography 50.0.2
- **Configuration digest**: `674112f15c7b2429ae24edce828079e96a2af9a8ca4a86cd01d155526a303680`
- **Raw trials**: 88 records (8 warmup, 0 errors), digest `b72186c0b9079208…`

> All endpoints are IPv4 loopback on one host inside one Python process. These numbers are **not** WAN performance, **not** Tor performance and do not establish anonymity. They isolate implementation cost under identical origin, destination, payload, duration and (absent an explicit link profile) network conditions.

## Target gate: AEGIS goodput ≥ 90% of Surface

| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |
|---|---|---|---|---|---|
| `None` | `None` | 0 | n/a | n/a | **insufficient data** (no_surface_reference_arm) |

## Workload `bulk_echo:1048576x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_io_batch` | 20 | 37.97 [33.68, 39.89] | 129.82 | 293.37 | 300.56 | n/a | 21.57 | 1.014 | 1.024 | 0.952 | 41.74 |
| `aegis_telescope3` | 20 | 37.14 [32.42, 40.46] | 128.20 | 304.82 | 328.44 | n/a | 20.71 | 1.014 | 1.024 | 0.952 | 41.74 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Workload `bulk_echo:262144x1@c16384i4`

| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `aegis_io_batch` | 20 | 35.40 [33.14, 41.32] | 34.86 | 69.37 | 70.60 | n/a | 20.00 | 1.017 | 1.027 | 0.967 | 41.74 |
| `aegis_telescope3` | 20 | 34.97 [31.67, 38.93] | 37.99 | 75.25 | 78.29 | n/a | 20.26 | 1.017 | 1.027 | 0.910 | 41.74 |

Goodput is payload bits divided by the wall time from first write to last echoed byte (one direction of useful payload per round trip). Completion p95/p99 is the per-trial total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. Wire ratios are counted by the per-arm edge proxy and include every byte the client put on its access link, including AEAD tags, headers and window updates.

## Reproducing this artifact

```
python -m anonlab.thor_lab summarize 20261118T224714-lab-20261119
python -m anonlab.thor_lab verify <run-directory>
```

`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.

