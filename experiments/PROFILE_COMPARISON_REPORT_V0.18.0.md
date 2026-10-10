# Performance profile comparison — v0.18.0 descriptor cache

## Change under test

The only runtime behavior change in this version is caching the immutable
`RelayDescriptor` built by each bound `RelayNode`. The cache is invalidated if
the bound host, listener port, identity digest or any private-key object changes.
The key holds strong references to key objects so Python `id()` reuse cannot
cause a stale descriptor to be returned.

## cProfile observations

Profile inputs: Python 3.13, same single-host Linux environment, eight streams,
256 KiB per stream, 256 KiB write chunks, pipeline depth 4, seed 20261018. The
baseline used the v0.17.0 source; the second profile used v0.18.0. cProfile
instrumentation affects wall times, so don't use these numbers for throughput.

| Function/call site | Before (v0.17) | After (v0.18) |
|---|---:|---:|
| `RelayNode.descriptor` call count | 1,425 | 1,425 |
| `RelayDescriptor.__post_init__` call count | 1,429 | 7 |
| `_ensure_loopback` call count | 1,458 | 36 |
| `ipaddress.ip_address` call count | 1,458 | 36 |
| `RelayNode.descriptor` cumulative time | 29.54 ms | 1.31 ms |

The descriptor property is still queried often, but normally returns the cached
object rather than reconstructing and revalidating it. Its cumulative profiled
time fell by about 95.6%; descriptor construction validations fell by more than
99%. Remaining profile time was concentrated in relay handlers, Python asyncio
scheduling/reads, AEAD seal/open calls, and request/response dispatch.

Raw profile summaries and snapshots are in `cprofile-before-cache-v0.17.0.*`
and `cprofile-after-cache-v0.18.0.*`.

## Five-trial benchmark comparison

Both blocks use eight streams of 1 MiB each, 64 KiB command chunks, three hops,
seed 20261018, pipeline depths 1/2/4 with rotating order, five trials per depth.
The v0.17 block was run first, then v0.18. These are separate blocks rather than
interleaved pairs, so system/thermal drift remains possible. Direct TCP's own
median also moved, which is a useful warning against overstating causality.

| Depth | v0.17 goodput median | v0.18 goodput median | Change | p50 per stream before → after |
|---:|---:|---:|---:|---:|
| 1 | 253.75 Mb/s | 289.96 Mb/s | +14.3% | 260.50 → 227.66 ms |
| 2 | 252.25 Mb/s | 295.70 Mb/s | +17.2% | 261.60 → 222.76 ms |
| 4 | 247.35 Mb/s | 279.09 Mb/s | +12.8% | 265.84 → 233.40 ms |

All 30 trials across the two blocks passed data integrity, relay-observability,
and connection/stream cleanup checks.

Raw JSON:

- `pipeline-depth-1mib-baseline-v0.17.0.json`
- `pipeline-depth-1mib-descriptor-cache-v0.18.0.json`
- `descriptor-cache-comparison-v0.18.0.json`

## Interpretation

Caching removed a clear, avoidable cost. The resulting goodput improvement is
consistent across three tested pipeline depths in this host, and the direct
control did not rise in parallel for all depths. Still, this is not a definitive
causal estimate, a multi-host result, a Tor comparison, or evidence of anonymity.
We should next profile window-update round trips and command dispatch, then run
interleaved benchmarks with controlled RTT/loss on separate machines.
