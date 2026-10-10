# Write batching v0.16.0 — three-way comparison (experimental)

## Change

`DuplexCircuitStream.write()` now accepts up to **256 KiB** per acknowledged command, increased from 64 KiB in v0.15.0. The write cap is explicit. Response events remain capped at 16 KiB, and the initial read-credit window remains 64 KiB per stream. Every write still waits for its command acknowledgement; this release does not add command pipelining or remove acknowledgements.

The `rea-anon-write-batch-bench` command now compares 16 KiB, 64 KiB, and 256 KiB write batches. Its default workload is 256 KiB per stream so the number of acknowledgements differs across all variants. Execution order rotates between trials to reduce simple order bias.

## Loopback benchmark

The v0.16.0 benchmark used 8 streams, 256 KiB useful payload per stream, 3 trials per size, and a three-relay IPv4 loopback circuit. Medians were:

| Write batch | ACKs per 256 KiB stream | Median useful goodput | Median stream p50 |
|---:|---:|---:|---:|
| 16 KiB | 16 | 178.66 Mb/s | 90.86 ms |
| 64 KiB | 4 | 230.15 Mb/s | 69.52 ms |
| 256 KiB | 1 | 246.17 Mb/s | 63.75 ms |

The median 256 KiB result was **37.8% higher than 16 KiB** and **7.0% higher than 64 KiB** in this run. Integrity, relay-observability, and cleanup checks passed in all trials. Full per-trial data is in `../experiments/write-batch-v0.16.0.json`.

These figures apply only to this host, Python implementation, workload, and loopback configuration. They are not WAN predictions, a Tor comparison, or evidence of anonymity. The direct TCP reference is unencrypted and is not an anonymity-equivalent baseline.

## Memory and security trade-off

At the default client stream limit of 128, one 256 KiB application write per active stream corresponds to up to 32 MiB of application payload represented by concurrent writes, before Python copies, framing/AEAD buffers, TCP buffers, payloads retained by calling code, or per-relay state are counted. This is an estimate of payload scale, **not a strict process memory bound**. Keep the cap explicit; do not expose the testbed relays to the Internet.

The existing per-hop AEAD, per-hop command sequence checks, destination allowlist, and bounded read-credit flow remain in place. The larger command uses more memory and CPU per operation. A larger batch does not establish fairness or production congestion control.

## Not established

No global-observer or traffic-correlation resistance, no Tor-compatible protocol, no production security, no independent crypto audit, and no performance claim for non-loopback networks is established by this release.
