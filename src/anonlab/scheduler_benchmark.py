"""A/B benchmark for the opt-in round-robin write scheduler.

The benchmark intentionally reports throughput, finite-flow completion fairness,
and latency together. It does not assume that round-robin scheduling is better.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__
from .network_impairment import DEFAULT_PROFILES
from .network_impairment_benchmark import run_network_impairment_benchmark


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _parse_stream_counts(value: str) -> list[int]:
    try:
        values = [int(piece.strip()) for piece in value.split(",") if piece.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("stream counts must be comma-separated integers") from exc
    if not values or any(v < 1 or v > 32 for v in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("stream counts must be unique values within 1..32")
    return values


async def run_scheduler_comparison(
    *,
    profile_name: str = "metro",
    stream_counts: list[int] | None = None,
    trials: int = 3,
    payload_bytes: int = 256 * 1024,
    write_chunk_bytes: int = 64 * 1024,
    pipeline_depth: int = 4,
    seed: int = 20261022,
) -> dict[str, Any]:
    """Compare baseline FIFO batch dispatch with opt-in round-robin scheduling."""
    counts = list(stream_counts or [2, 4, 8])
    if profile_name not in DEFAULT_PROFILES:
        raise ValueError("unknown profile")
    if not counts or len(set(counts)) != len(counts) or any(
        not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 32 for v in counts
    ):
        raise ValueError("stream_counts must be unique integers within 1..32")
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1024 <= payload_bytes <= 1024 * 1024:
        raise ValueError("payload_bytes must be within 1024..1048576")
    if not isinstance(write_chunk_bytes, int) or isinstance(write_chunk_bytes, bool) or not 1 <= write_chunk_bytes <= 256 * 1024:
        raise ValueError("write_chunk_bytes must be within 1..262144")
    if not isinstance(pipeline_depth, int) or isinstance(pipeline_depth, bool) or not 1 <= pipeline_depth <= 4:
        raise ValueError("pipeline_depth must be within 1..4")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    base = DEFAULT_PROFILES[profile_name]
    conditions = [(count, fair) for count in counts for fair in (False, True)]
    raw_runs: list[dict[str, Any]] = []
    order_by_trial: list[list[dict[str, Any]]] = []
    for trial_index in range(trials):
        shift = trial_index % len(conditions)
        order = conditions[shift:] + conditions[:shift]
        order_by_trial.append([
            {"stream_count": count, "scheduler": "round_robin" if fair else "baseline"}
            for count, fair in order
        ])
        for position, (stream_count, fair) in enumerate(order):
            run_seed = seed + trial_index * 1_000_003 + position * 97_409 + stream_count * 65_537 + int(fair) * 17_171
            profile = replace(base, seed=base.seed + run_seed % 1_000_000_007)
            result = await run_network_impairment_benchmark(
                profile=profile,
                stream_count=stream_count,
                payload_bytes=payload_bytes,
                seed=run_seed,
                write_chunk_bytes=write_chunk_bytes,
                pipeline_depth=pipeline_depth,
                fair_write_scheduling=fair,
            )
            measured = result["results"]
            if not measured["integrity_verified"]:
                raise RuntimeError("integrity check failed in scheduler comparison")
            if not measured["relay_observability_check"]:
                raise RuntimeError("relay observability check failed in scheduler comparison")
            if not measured["all_relay_connections_closed"] or measured["active_proxy_connections_after_close"] != [0, 0, 0, 0]:
                raise RuntimeError("resource cleanup check failed in scheduler comparison")
            raw_runs.append({
                "trial": trial_index + 1,
                "position_in_trial": position + 1,
                "stream_count": stream_count,
                "scheduler": "round_robin" if fair else "baseline",
                "fair_write_scheduling": fair,
                "seed": run_seed,
                "circuit_goodput_mbps": measured["circuit_goodput_mbps"],
                "circuit_completion_rate_jain_index": measured["circuit_completion_rate_jain_index"],
                "circuit_stream_latency_p50_ms": measured["circuit_stream_latency_p50_ms"],
                "circuit_stream_latency_p95_ms": measured["circuit_stream_latency_p95_ms"],
                "circuit_per_stream": measured["circuit_per_stream"],
                "integrity_verified": measured["integrity_verified"],
                "relay_observability_check": measured["relay_observability_check"],
                "all_relay_connections_closed": measured["all_relay_connections_closed"],
                "active_proxy_connections_after_close": measured["active_proxy_connections_after_close"],
            })

    summary: list[dict[str, Any]] = []
    for stream_count in counts:
        by_mode: dict[str, dict[str, Any]] = {}
        for mode in ("baseline", "round_robin"):
            subset = [r for r in raw_runs if r["stream_count"] == stream_count and r["scheduler"] == mode]
            def med(field: str) -> float:
                return _median([float(r[field]) for r in subset])
            by_mode[mode] = {
                "trials": len(subset),
                "goodput_mbps_median": med("circuit_goodput_mbps"),
                "jain_index_median": med("circuit_completion_rate_jain_index"),
                "latency_p50_ms_median": med("circuit_stream_latency_p50_ms"),
                "latency_p95_ms_median": med("circuit_stream_latency_p95_ms"),
                "all_checks_passed": all(
                    r["integrity_verified"] and r["relay_observability_check"] and
                    r["all_relay_connections_closed"] and r["active_proxy_connections_after_close"] == [0, 0, 0, 0]
                    for r in subset
                ),
            }
        base_goodput = by_mode["baseline"]["goodput_mbps_median"]
        fair_goodput = by_mode["round_robin"]["goodput_mbps_median"]
        base_p95 = by_mode["baseline"]["latency_p95_ms_median"]
        fair_p95 = by_mode["round_robin"]["latency_p95_ms_median"]
        summary.append({
            "stream_count": stream_count,
            "by_scheduler": by_mode,
            "round_robin_goodput_delta_percent": ((fair_goodput / base_goodput) - 1) * 100 if base_goodput else 0.0,
            "round_robin_jain_delta": by_mode["round_robin"]["jain_index_median"] - by_mode["baseline"]["jain_index_median"],
            "round_robin_p95_latency_delta_percent": ((fair_p95 / base_p95) - 1) * 100 if base_p95 else 0.0,
        })
    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "paired baseline-vs-round-robin client write scheduler A/B",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "is_loopback_only": True,
            "is_real_wan_measurement": False,
            "is_packet_loss_simulation": False,
            "is_production_congestion_control_test": False,
            "warning": "Scheduler effects are workload-dependent; finite-flow Jain index is exploratory and does not prove steady-state fairness.",
        },
        "config": {
            "profile": profile_name,
            "stream_counts": counts,
            "trials_per_mode_and_count": trials,
            "payload_bytes_per_stream": payload_bytes,
            "write_chunk_bytes": write_chunk_bytes,
            "pipeline_depth": pipeline_depth,
            "seed": seed,
            "order_by_trial": order_by_trial,
            "hop_count": 3,
        },
        "summary": summary,
        "runs": raw_runs,
        "limitations": [
            "All relays, proxies and destination run on one host using IPv4 loopback.",
            "User-space shaping affects TCP byte-stream chunks and does not model IP packet loss or retransmissions.",
            "Both modes have the same protocol, cryptography and write-batch configuration; only client scheduling differs.",
            "Finite transfer metrics include startup and teardown and are not a proof of steady-state fairness.",
            "The custom protocol remains experimental and unaudited.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B test baseline and round-robin AEGIS write schedulers")
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="metro")
    parser.add_argument("--stream-counts", type=_parse_stream_counts, default=[2, 4, 8])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--payload-bytes", type=int, default=256 * 1024)
    parser.add_argument("--write-chunk-bytes", type=int, default=64 * 1024)
    parser.add_argument("--pipeline-depth", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_scheduler_comparison(
        profile_name=args.profile,
        stream_counts=args.stream_counts,
        trials=args.trials,
        payload_bytes=args.payload_bytes,
        write_chunk_bytes=args.write_chunk_bytes,
        pipeline_depth=args.pipeline_depth,
        seed=args.seed,
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
