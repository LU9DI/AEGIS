# Validation record — MALEBOLGE v0.18.0

- Source test suite: `115 passed, 11 subtests passed`.
- Descriptor-cache tests cover cached object identity, access before bind,
  endpoint invalidation, digest invalidation, and onion-key object replacement.
- Benchmark comparison: 5 trials per pipeline depth for both the v0.17.0
  baseline and v0.18.0 cache variant. All integrity, relay-observability and
  resource-cleanup checks passed in every trial.
- cProfile captures use the same single-host workload parameters before/after;
  profiler timings are not used as throughput values. The new
  `rea-anon-profile-hotpath` command was smoke-tested from source and from the
  installed wheel.
- Wheel `rea_anon_lab-0.18.0-py3-none-any.whl` built and installed into a fresh
  virtual environment. The `rea-anon-lab`, `rea-anon-pipeline-bench`, and
  `rea-anon-profile-hotpath` commands all completed smoke tests and reported
  version 0.18.0.
- The source ZIP was extracted to a clean directory and the full suite passed
  there: `115 passed, 11 subtests passed`.
- SHA-256 checksums are provided alongside the final ZIP and wheel.

This remains a loopback-only, custom, unaudited research prototype. Test success
is not proof of anonymity or production security.
