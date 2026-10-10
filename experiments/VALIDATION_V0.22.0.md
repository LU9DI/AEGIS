# Validation — v0.22.0

- Full source suite: 143 tests passed, 11 subtests passed.
- Round-robin integration: four simultaneous streams interleave one command per stream in the first scheduler round, return byte-for-byte identical payloads, and leave queue command/byte counters at zero.
- Admission limit: exceeding the scheduler byte budget is rejected before dispatch and leaves the circuit usable for a subsequent smaller write.
- A/B benchmark: 18 runs (baseline and round-robin × 2/4/8 streams × 3 trials) passed payload-integrity, relay-observability, relay-cleanup and proxy-cleanup checks. The resulting A/B summary is recorded in `experiments/SCHEDULER_AB_REPORT_V0.22.0.md` and raw measurements in `experiments/scheduler-ab-v0.22.0.json`.
- Benchmark CLI registered as `rea-anon-scheduler-bench`.
- Wheel built as `rea_anon_lab-0.22.0-py3-none-any.whl`, installed into a fresh virtual environment, and `rea-anon-scheduler-bench` smoke-tested with 2 runs; version, integrity, observability and cleanup checks passed.
- The release ZIP was extracted into a clean directory; the full suite passed from the extracted source: 143 tests and 11 subtests.
- Final package checksums are generated separately in `MALEBOLGE-v0.22.0-SHA256SUMS.txt`.

All results are loopback-only. They do not constitute a cryptographic audit, WAN performance prediction, or proof of anonymity/fairness.
