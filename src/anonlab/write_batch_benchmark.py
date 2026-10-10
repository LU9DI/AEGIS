"""Paired loopback benchmark for AEGIS acknowledged write batching.

Compares 16 KiB, 64 KiB, and 256 KiB client-to-destination writes with identical
stream counts, payload sizes, and seeds. Results are host-local microbenchmarks,
not WAN predictions and not claims about anonymity or cryptographic security.
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
from .telescoping import STREAM_CHUNK_BYTES, STREAM_WRITE_MAX_BYTES

BASELINE_WRITE_CHUNK_BYTES = 16 * 1024
MID_WRITE_CHUNK_BYTES = 64 * 1024


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * p + 0.999999)))
    return ordered[index]


async def run_write_batch_benchmark(
    *, trials: int = 5, stream_count: int = 8, payload_bytes: int = 256 * 1024,
    seed: int = 20261009,
) -> dict[str, Any]:
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 25:
        raise ValueError("trials must be within 1..25")
    if not isinstance(stream_count, int) or isinstance(stream_count, bool) or not 1 <= stream_count <= 64:
        raise ValueError("stream_count must be within 1..64")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1 <= payload_bytes <= 4 * 1024 * 1024:
        raise ValueError("payload_bytes must be within 1..4 MiB")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    batch_sizes = (BASELINE_WRITE_CHUNK_BYTES, MID_WRITE_CHUNK_BYTES, STREAM_WRITE_MAX_BYTES)
    records: list[dict[str, Any]] = []
    # Reverse execution order every other trial to reduce simple order/thermal bias.
    for trial_index in range(trials):
        rotate = trial_index % len(batch_sizes)
        ordered_sizes = batch_sizes[rotate:] + batch_sizes[:rotate]
        for batch_size in ordered_sizes:
            result = await run_duplex_benchmark(
                stream_count=stream_count,
                payload_bytes=payload_bytes,
                seed=seed + trial_index,
                write_chunk_bytes=batch_size,
            )
            records.append({
                "trial": trial_index + 1,
                "write_chunk_bytes": batch_size,
                "seed": seed + trial_index,
                "results": result["results"],
                "benchmark_config": result["config"],
            })

    summaries: dict[str, dict[str, float | int | bool]] = {}
    for batch_size in batch_sizes:
        selected = [r for r in records if r["write_chunk_bytes"] == batch_size]
        goodput = [float(r["results"]["duplex_goodput_mbps"]) for r in selected]
        p50 = [float(r["results"]["duplex_stream_latency_p50_ms"]) for r in selected]
        p95 = [float(r["results"]["duplex_stream_latency_p95_ms"]) for r in selected]
        direct = [float(r["results"]["direct_goodput_mbps"]) for r in selected]
        summaries[str(batch_size)] = {
            "write_chunk_bytes": batch_size,
            "write_acknowledgements_per_full_64k_stream": (64 * 1024 + batch_size - 1) // batch_size,
            "write_acknowledgements_per_full_256k_stream": (256 * 1024 + batch_size - 1) // batch_size,
            "write_acknowledgements_per_payload_stream": (payload_bytes + batch_size - 1) // batch_size,
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
        }

    baseline = summaries[str(BASELINE_WRITE_CHUNK_BYTES)]
    mid = summaries[str(MID_WRITE_CHUNK_BYTES)]
    batched = summaries[str(STREAM_WRITE_MAX_BYTES)]
    baseline_goodput = float(baseline["duplex_goodput_mbps_median"])
    mid_goodput = float(mid["duplex_goodput_mbps_median"])
    batched_goodput = float(batched["duplex_goodput_mbps_median"])
    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "three-way write-batching comparison on three-hop loopback circuit",
            "trials_per_batch_size": trials,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "is_loopback_only": True,
            "is_production_security_test": False,
            "warning": "This is a single-host loopback microbenchmark. It does not predict WAN performance, prove anonymity, or compare against Tor. A higher result must be reproduced on other hosts and workloads.",
        },
        "config": {
            "streams": stream_count,
            "payload_bytes_per_stream": payload_bytes,
            "hop_count": 3,
            "response_event_chunk_bytes": STREAM_CHUNK_BYTES,
            "batch_sizes_bytes": list(batch_sizes),
            "batch_order_rotates_each_trial": True,
            "base_seed": seed,
        },
        "summary": {
            "all_integrity_checks_passed": all(bool(value["integrity_all_trials"]) for value in summaries.values()),
            "all_relay_observability_checks_passed": all(bool(value["relay_observability_all_trials"]) for value in summaries.values()),
            "all_cleanup_checks_passed": all(bool(value["cleanup_all_trials"]) for value in summaries.values()),
            "goodput_median_ratio_64k_vs_16k": mid_goodput / baseline_goodput if baseline_goodput > 0 else 0.0,
            "goodput_percent_change_64k_vs_16k": ((mid_goodput / baseline_goodput) - 1.0) * 100.0 if baseline_goodput > 0 else 0.0,
            "goodput_median_ratio_256k_vs_16k": batched_goodput / baseline_goodput if baseline_goodput > 0 else 0.0,
            "goodput_percent_change_256k_vs_16k": ((batched_goodput / baseline_goodput) - 1.0) * 100.0 if baseline_goodput > 0 else 0.0,
            "goodput_median_ratio_256k_vs_64k": batched_goodput / mid_goodput if mid_goodput > 0 else 0.0,
            "goodput_percent_change_256k_vs_64k": ((batched_goodput / mid_goodput) - 1.0) * 100.0 if mid_goodput > 0 else 0.0,
        },
        "by_write_chunk_bytes": summaries,
        "trials": records,
        "limitations": [
            "All relays and the destination use one host and IPv4 loopback.",
            "The 16 KiB, 64 KiB and 256 KiB options vary acknowledged command size, not cryptographic design or anonymity properties.",
            "Direct TCP is not an anonymity-equivalent baseline.",
            "Benchmark values include Python scheduling and local process overhead, which can dominate small payloads.",
            "No fairness proof, congestion-control analysis, WAN path, or global traffic-analysis test is included.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS loopback benchmark for 16 KiB, 64 KiB, and 256 KiB writes")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--streams", type=int, default=8)
    parser.add_argument("--payload-bytes", type=int, default=262144)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_write_batch_benchmark(
        trials=args.trials,
        stream_count=args.streams,
        payload_bytes=args.payload_bytes,
        seed=args.seed,
    ))
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
