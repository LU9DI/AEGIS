# Validation — v0.16.0

- Full suite: 106 passed, 11 subtests passed.
- Full-duplex echo integration test sends exactly 256 KiB in one acknowledged write, then half-closes and verifies echoed bytes plus trailing server data.
- Oversized-write test rejects `STREAM_WRITE_MAX_BYTES + 1` locally.
- Three-way paired benchmark: 3 trials per batch size, 8 streams × 256 KiB per stream, three-hop IPv4 loopback.
- Median useful goodput: 178.66 Mb/s at 16 KiB, 230.15 Mb/s at 64 KiB, and 246.17 Mb/s at 256 KiB.
- All integrity, relay-observability and cleanup checks passed in all nine trial runs.
- Wheel build completed without network access. Clean-venv installation and CLI smoke run passed; smoke benchmark reported version 0.16.0 and passed integrity, relay-observability, and cleanup checks. ZIP extraction and the full test rerun passed after packaging.

This is a single-host laboratory result. It does not prove WAN throughput, anonymity, or production security.


The installed-wheel smoke workload used two streams × 256 KiB and one trial. It showed essentially no difference between 64 KiB and 256 KiB (about +0.05% for 256 KiB), illustrating that the larger command cap is workload-dependent and not a universal optimization.
