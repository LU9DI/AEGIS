# MALEBOLGE v0.20.0 — network-condition experiment report

## Result

Added a bounded loopback TCP shaper and exercised the three-relay encrypted circuit under five synthetic conditions plus a sparse-write scenario. The shaper rate cap is aggregate per proxy and per direction, shared among connections; this is important because applying a full bandwidth cap separately to each direct connection would unfairly favor a scenario that opens more connections.

The run matrix consisted of two trials for `loopback`, `lan`, `metro`, `intercontinental`, and `constrained`, each using two 8 KiB streams. The sparse case used two 4 KiB streams, 512-byte application writes, and 1 ms gaps under the intercontinental profile. All 12 runs passed integrity, relay-observability and cleanup checks, and no proxy queue exceeded its configured chunk bound.

## Summary

| Profile | Circuit median goodput | Circuit median p50 latency | Circuit median p95 latency |
|---|---:|---:|---:|
| `loopback` | 35.181 Mb/s | 2.766 ms | 3.051 ms |
| `lan` | 4.079 Mb/s | 19.691 ms | 22.623 ms |
| `metro` | 0.938 Mb/s | 82.068 ms | 93.870 ms |
| `intercontinental` | 0.207 Mb/s | 377.340 ms | 429.641 ms |
| `constrained` | 0.098 Mb/s | 916.517 ms | 993.602 ms |
| `intercontinental_sparse` | 0.038 Mb/s | 1,472.512 ms | 1,516.115 ms |

Direct-control medians and individual trials are recorded in the machine-readable JSON files. The direct path has one shaped proxy link; the circuit has four, so the table is diagnostic of path-length sensitivity, not an equivalent privacy/performance comparison.

## Interpretation

1. Delay adds substantial cost to a circuit that performs acknowledged control/data operations over multiple relays.
2. Sparse writes are especially expensive under high simulated delay, making application write coalescing and future stream protocol changes worthwhile areas to test.
3. The rate shaper has a shared per-direction serialization schedule across connections, rather than giving every connection an independent full link rate.
4. The testbed retains TCP reliability and shapes user-space reads. It does not emulate packet loss, TCP retransmissions, real congestion control, NAT or wireless behavior.
5. These small two-trial profiles are exploratory only. No inference about Tor-relative speed, global-observer anonymity, or real WAN performance is supported.

See `docs/NETWORK_IMPAIRMENT_V0.20.0.md` for methodology and reproduction commands.
