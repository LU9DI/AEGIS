# Validation — v0.15.0

- `python -m pytest -q`: **106 passed, 11 subtests passed**.
- Paired write-batch benchmark: **5 trials per mode**, 8 streams × 65,536 bytes per stream, three-hop IPv4 loopback.
- 16 KiB batch median useful goodput: **152.46 Mb/s**.
- 64 KiB batch median useful goodput: **193.71 Mb/s** (+27.1% in this benchmark).
- Integrity, relay-observability and cleanup checks passed in all benchmark trials.
- The test `test_full_duplex_stream_write_half_close_read_and_close` exercises an exact 64 KiB write and a trailing partial write.
- The oversized-write test rejects a 64 KiB + 1 payload locally.

This is a local research testbed result, not evidence of WAN performance, anonymity or production security.

- Built `rea_anon_lab-0.15.0-py3-none-any.whl` without network access.
- Installed the wheel into a clean virtual environment (using system-site packages only for the optional `cryptography` test dependency) and ran `rea-anon-write-batch-bench --trials 1 --streams 2 --payload-bytes 2048`; integrity, relay-observability and cleanup checks all passed. This smoke workload showed +13.3% for 64 KiB writes, but with only one trial and small payloads it is an installation smoke test, not the performance headline.
