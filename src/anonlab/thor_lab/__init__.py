"""THOR lab: reproducible performance and privacy measurement for AEGIS.

This package is a *measurement* layer, not a protocol. It exists because the
existing per-harness benchmarks in :mod:`anonlab` each measure one workload with
one comparison and none of them report CPU, memory, wire-byte overhead, p99, or
a confidence interval.

Rules this package follows (see ``docs/research/thor/05-BENCHMARK-PLAN.md``):

* every trial is written to an append-only JSONL record before any aggregation,
  including warmup and failed trials;
* derived numbers come from :mod:`anonlab.thor_lab.metrics`, which can be
  re-run from the raw file;
* each run records the code revision, environment, configuration digest and
  seed so a ratio can be traced back to the commit that produced it;
* loopback, link-emulated and public-network results are summarized per tier
  and are never combined into one headline ratio;
* nothing here claims anonymity, Tor equivalence, or production security.
"""
from __future__ import annotations

__all__ = ["SCHEMA_VERSION", "TIERS"]

#: Bumped whenever the JSONL/summary schema changes in an incompatible way.
SCHEMA_VERSION = 1

#: Measurement tiers. A ratio is only valid *inside* one tier.
TIERS = {
    "lab": "All endpoints on IPv4 loopback in one host; no WAN modelling.",
    "emulated": "Loopback plus the existing user-space link shaper profile.",
    "public": "Real public-network endpoints; subject to the local access link.",
}
