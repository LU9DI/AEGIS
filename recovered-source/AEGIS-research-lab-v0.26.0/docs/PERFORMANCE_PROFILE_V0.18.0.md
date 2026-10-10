# MALEBOLGE v0.18.0 — descriptor-cache performance profile

## Change

`RelayNode.descriptor` previously constructed a new immutable `RelayDescriptor`
for each property access. Circuit forwarding and event wrapping consult this
property on hot paths, so every call repeated validation of the loopback host,
port, identity digest and public-key lengths. The v0.18.0 implementation caches
the immutable descriptor after binding. Its cache key includes the port,
bound host, identity digest and strong references to the identity-key objects;
changes to any of those values invalidate the cached descriptor. Keeping the
objects in the key avoids relying on recyclable numeric `id()` values.

The cache does not bypass validation when a descriptor is built or when its
endpoint/key identity changes. It only avoids reconstructing and revalidating
the same descriptor repeatedly.

## cProfile evidence

The paired profiling run used Python 3.13 on the same Linux host, an 8-stream,
256 KiB-per-stream duplex echo workload, 256 KiB maximum WRITE size, and pipeline
depth 4. cProfile overhead changes wall-clock benchmark times, so the following
numbers are call counts and cumulative profiler time, not throughput claims.

| Profiled function | Before cache | After cache |
|---|---:|---:|
| `RelayNode.descriptor` calls | 1,425 | 1,425 |
| `RelayDescriptor.__post_init__` calls | 1,429 | 7 |
| `_ensure_loopback` calls | 1,458 | 36 |
| `ipaddress.ip_address` calls | 1,458 | 36 |
| `RelayNode.descriptor` cumulative time | 29.54 ms | 1.31 ms |

The descriptor property is still read on the hot path, but repeated object
construction and validation are avoided. The cProfile cumulative time for the
property fell by approximately 95.6% in this instrumented run. The remaining
profile shows time in relay handlers, `asyncio` scheduling/read loops, per-hop
AEAD (`seal`/`open_sealed`) and command/response dispatch.

To reproduce profiling on an installed v0.18.0 build, use `rea-anon-profile-hotpath`; it emits cProfile binary/text/JSON artifacts and summarizes selected function counts only (no frame payloads or local variables):

```bash
rea-anon-profile-hotpath --streams 8 --payload-bytes 262144 \
  --write-chunk-bytes 262144 --pipeline-depth 4 \
  --output-prefix experiments/reproduced-profile
```

Raw artifacts from the comparison in this report:

- `experiments/cprofile-before-cache-v0.17.0.txt`
- `experiments/cprofile-after-cache-v0.18.0.txt`
- corresponding `.prof` snapshots and JSON summaries.

## Throughput comparison

Two separate five-trial blocks were run on the same host with identical
settings: 8 streams × 1 MiB per stream, 64 KiB writes, 3 relays, depths 1/2/4,
rotating configuration order and the same seed. The unoptimized v0.17.0 run
was performed first; the cached v0.18.0 run followed. Because the runs were not
interleaved, thermal/system drift is still possible. The direct-TCP control
also moved between blocks, so this is evidence of a likely local improvement,
not a cross-host causal guarantee.

| Pipeline depth | Goodput before | Goodput after | Change | stream p50 before → after |
|---:|---:|---:|---:|---:|
| 1 | 253.75 Mb/s | 289.96 Mb/s | +14.3% | 260.50 → 227.66 ms |
| 2 | 252.25 Mb/s | 295.70 Mb/s | +17.2% | 261.60 → 222.76 ms |
| 4 | 247.35 Mb/s | 279.09 Mb/s | +12.8% | 265.84 → 233.40 ms |

All trials in both blocks passed integrity, relay-observability and resource
cleanup checks. Data is stored in:

- `experiments/pipeline-depth-1mib-baseline-v0.17.0.json`
- `experiments/pipeline-depth-1mib-descriptor-cache-v0.18.0.json`
- `experiments/descriptor-cache-comparison-v0.18.0.json`

## Interpretation and limitations

The change removes substantial redundant validation and was followed by 12.8–
17.2% higher median goodput in these separate local benchmark blocks. Do not
interpret this as a promised speedup on the public Internet. All relays and the
destination run on one host over IPv4 loopback. This benchmark does not model
WAN latency/loss, prove anonymity, or compare against Tor with equivalent
security properties.

The next bottlenecks to investigate are relay command handling, per-hop AEAD,
read-credit update round trips, and asyncio scheduling. Any further optimization
must preserve authentication, stream isolation, sequence validation, and bounded
resource accounting.
