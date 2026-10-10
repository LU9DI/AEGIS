"""Paired loopback benchmark comparing bounded WRITE pipeline depths.

This benchmark varies only the number of acknowledged WRITE commands allowed
in flight per stream. It is a single-host microbenchmark, not a WAN forecast or
proof of anonymity.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .duplex_benchmark import run_duplex_benchmark
from .telescoping import STREAM_WRITE_MAX_BYTES

PIPELINE_DEPTHS = (1, 2, 4)
DEFAULT_CHUNK_BYTES = 64 * 1024


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * 0.95 + 0.999999)))]


async def run_pipeline_benchmark(
    *, trials: int = 3, stream_count: int = 8, payload_bytes: int = 256 * 1024,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES, seed: int = 20261009,
) -> dict[str, Any]:
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(stream_count, int) or isinstance(stream_count, bool) or not 1 <= stream_count <= 64:
        raise ValueError("stream_count must be within 1..64")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1 <= payload_bytes <= 4 * 1024 * 1024:
        raise ValueError("payload_bytes must be within 1..4 MiB")
    if not isinstance(chunk_bytes, int) or isinstance(chunk_bytes, bool) or not 1 <= chunk_bytes <= STREAM_WRITE_MAX_BYTES:
        raise ValueError(f"chunk_bytes must be within 1..{STREAM_WRITE_MAX_BYTES}")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    records: list[dict[str, Any]] = []
    # Rotate depth order to reduce simple warm-up/thermal bias.
    for trial_index in range(trials):
        shift = trial_index % len(PIPELINE_DEPTHS)
        depths = PIPELINE_DEPTHS[shift:] + PIPELINE_DEPTHS[:shift]
        for depth in depths:
            result = await run_duplex_benchmark(
                stream_count=stream_count,
                payload_bytes=payload_bytes,
                seed=seed + trial_index,
                write_chunk_bytes=chunk_bytes,
                pipeline_depth=depth,
            )
            records.append({
                "trial": trial_index + 1,
                "pipeline_depth": depth,
                "seed": seed + trial_index,
                "results": result["results"],
                "benchmark_config": result["config"],
            })

    by_depth: dict[str, dict[str, float | int | bool]] = {}
    for depth in PIPELINE_DEPTHS:
        selected = [r for r in records if r["pipeline_depth"] == depth]
        goodput = [float(r["results"]["duplex_goodput_mbps"]) for r in selected]
        p50 = [float(r["results"]["duplex_stream_latency_p50_ms"]) for r in selected]
        p95 = [float(r["results"]["duplex_stream_latency_p95_ms"]) for r in selected]
        direct = [float(r["results"]["direct_goodput_mbps"]) for r in selected]
        by_depth[str(depth)] = {
            "pipeline_depth": depth,
            "trials": len(selected),
            "integrity_all_trials": all(bool(r["results"]["integrity_verified"]) for r in selected),
            "relay_observability_all_trials": all(bool(r["results"]["relay_observability_check"]) for r in selected),
            "cleanup_all_trials": all(
                r["results"]["active_streams_after_completion"] == 0
                and r["results"]["active_connections_after_close"] == [0, 0, 0]
                for r in selected
            ),
            "duplex_goodput_mbps_median": _median(goodput),
            "duplex_goodput_mbps_min": min(goodput, default=0.0),
            "duplex_goodput_mbps_max": max(goodput, default=0.0),
            "duplex_stream_latency_p50_ms_median": _median(p50),
            "duplex_stream_latency_p95_ms_median": _median(p95),
            "direct_goodput_mbps_median": _median(direct),
            "direct_p95_ms_median": _median([
                float(r["results"]["direct_stream_latency_p95_ms"]) for r in selected
            ]),
            "pipeline_payload_bytes_per_stream": min(payload_bytes, chunk_bytes * depth),
        }

    serial = by_depth["1"]
    summary = {
        "all_integrity_checks_passed": all(bool(v["integrity_all_trials"]) for v in by_depth.values()),
        "all_relay_observability_checks_passed": all(bool(v["relay_observability_all_trials"]) for v in by_depth.values()),
        "all_cleanup_checks_passed": all(bool(v["cleanup_all_trials"]) for v in by_depth.values()),
        "goodput_ratio_depth_2_vs_1": float(by_depth["2"]["duplex_goodput_mbps_median"]) / max(1e-12, float(serial["duplex_goodput_mbps_median"])),
        "goodput_percent_change_depth_2_vs_1": (
            float(by_depth["2"]["duplex_goodput_mbps_median"]) / max(1e-12, float(serial["duplex_goodput_mbps_median"])) - 1
        ) * 100,
        "goodput_ratio_depth_4_vs_1": float(by_depth["4"]["duplex_goodput_mbps_median"]) / max(1e-12, float(serial["duplex_goodput_mbps_median"])),
        "goodput_percent_change_depth_4_vs_1": (
            float(by_depth["4"]["duplex_goodput_mbps_median"]) / max(1e-12, float(serial["duplex_goodput_mbps_median"])) - 1
        ) * 100,
    }
    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "bounded WRITE pipeline-depth comparison on three-hop IPv4 loopback circuit",
            "trials_per_depth": trials,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "is_loopback_only": True,
            "is_production_security_test": False,
            "warning": "Single-host loopback microbenchmark only. Results do not predict WAN performance, prove anonymity, or compare securely with Tor. Re-run on different hosts and workloads.",
        },
        "config": {
            "streams": stream_count,
            "payload_bytes_per_stream": payload_bytes,
            "chunk_bytes": chunk_bytes,
            "pipeline_depths": list(PIPELINE_DEPTHS),
            "max_in_flight_bytes_per_stream": chunk_bytes * max(PIPELINE_DEPTHS),
            "hop_count": 3,
            "order_rotates_each_trial": True,
            "base_seed": seed,
        },
        "summary": summary,
        "by_pipeline_depth": by_depth,
        "trials": records,
        "limitations": [
            "All relays and the destination are on one host and IPv4 loopback.",
            "Pipeline depths are bounded to four commands per stream; relays cap per-stream and aggregate in-flight bytes.",
            "TCP direct is unencrypted and is not an anonymity-equivalent baseline.",
            "No fairness proof, WAN congestion analysis, traffic-correlation analysis, or independent protocol audit is included.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare AEGIS bounded WRITE pipeline depths 1, 2, and 4")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--streams", type=int, default=8)
    parser.add_argument("--payload-bytes", type=int, default=256 * 1024)
    parser.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_pipeline_benchmark(
        trials=args.trials, stream_count=args.streams, payload_bytes=args.payload_bytes,
        chunk_bytes=args.chunk_bytes, seed=args.seed,
    ))
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
