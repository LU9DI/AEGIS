"""Exploratory completion-rate fairness benchmark for AEGIS loopback circuits.

This tool measures how similarly finite, equal-sized streams complete when
sharing a shaped three-relay circuit. Jain's index here is a completion-rate
proxy, not proof of steady-state fairness or production congestion control.
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
        counts = [int(piece.strip()) for piece in value.split(",") if piece.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("stream counts must be comma-separated integers") from exc
    if not counts or any(count < 1 or count > 32 for count in counts):
        raise argparse.ArgumentTypeError("stream counts must be between 1 and 32")
    if len(set(counts)) != len(counts):
        raise argparse.ArgumentTypeError("stream counts must not contain duplicates")
    return counts


async def run_fairness_matrix(
    *,
    profile_name: str = "metro",
    stream_counts: list[int] | None = None,
    trials: int = 3,
    payload_bytes: int = 32 * 1024,
    seed: int = 20261021,
) -> dict[str, Any]:
    """Run a rotated-order matrix and report per-stream completion-rate fairness."""
    counts = list(stream_counts or [1, 2, 4, 8])
    if profile_name not in DEFAULT_PROFILES:
        raise ValueError("unknown profile")
    if not counts or len(set(counts)) != len(counts) or any(
        not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 32 for value in counts
    ):
        raise ValueError("stream_counts must be unique integers within 1..32")
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1024 <= payload_bytes <= 1024 * 1024:
        raise ValueError("payload_bytes must be within 1024..1048576")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    base_profile = DEFAULT_PROFILES[profile_name]
    raw_runs: list[dict[str, Any]] = []
    order_by_trial: list[list[int]] = []
    for trial_index in range(trials):
        shift = trial_index % len(counts)
        order = counts[shift:] + counts[:shift]
        order_by_trial.append(order)
        for position, stream_count in enumerate(order):
            run_seed = seed + trial_index * 1_000_003 + position * 97_409 + stream_count * 65_537
            profile = replace(base_profile, seed=base_profile.seed + run_seed % 1_000_000_007)
            result = await run_network_impairment_benchmark(
                profile=profile,
                stream_count=stream_count,
                payload_bytes=payload_bytes,
                seed=run_seed,
            )
            results = result["results"]
            if not results["integrity_verified"]:
                raise RuntimeError("integrity check failed in fairness run")
            if not results["relay_observability_check"]:
                raise RuntimeError("relay observability check failed in fairness run")
            if not results["all_relay_connections_closed"]:
                raise RuntimeError("relay cleanup check failed in fairness run")
            if results["active_proxy_connections_after_close"] != [0, 0, 0, 0]:
                raise RuntimeError("proxy cleanup check failed in fairness run")
            if len(results["circuit_per_stream"]) != stream_count or len(results["direct_per_stream"]) != stream_count:
                raise RuntimeError("per-stream measurements are incomplete")
            raw_runs.append({
                "trial": trial_index + 1,
                "position_in_trial": position + 1,
                "stream_count": stream_count,
                "seed": run_seed,
                "profile": profile_name,
                "circuit_goodput_mbps": results["circuit_goodput_mbps"],
                "direct_goodput_mbps": results["direct_goodput_mbps"],
                "circuit_completion_rate_jain_index": results["circuit_completion_rate_jain_index"],
                "direct_completion_rate_jain_index": results["direct_completion_rate_jain_index"],
                "circuit_stream_latency_p50_ms": results["circuit_stream_latency_p50_ms"],
                "circuit_stream_latency_p95_ms": results["circuit_stream_latency_p95_ms"],
                "circuit_per_stream": results["circuit_per_stream"],
                "direct_per_stream": results["direct_per_stream"],
                "integrity_verified": results["integrity_verified"],
                "relay_observability_check": results["relay_observability_check"],
                "all_relay_connections_closed": results["all_relay_connections_closed"],
                "active_proxy_connections_after_close": results["active_proxy_connections_after_close"],
            })

    summary: list[dict[str, Any]] = []
    for stream_count in counts:
        subset = [item for item in raw_runs if item["stream_count"] == stream_count]
        circuit_goodputs = [float(item["circuit_goodput_mbps"]) for item in subset]
        circuit_fairness = [float(item["circuit_completion_rate_jain_index"]) for item in subset]
        direct_goodputs = [float(item["direct_goodput_mbps"]) for item in subset]
        direct_fairness = [float(item["direct_completion_rate_jain_index"]) for item in subset]
        summary.append({
            "stream_count": stream_count,
            "trials": len(subset),
            "circuit_goodput_mbps_median": _median(circuit_goodputs),
            "circuit_completion_rate_jain_index_median": _median(circuit_fairness),
            "direct_goodput_mbps_median": _median(direct_goodputs),
            "direct_completion_rate_jain_index_median": _median(direct_fairness),
            "circuit_stream_latency_p50_ms_median": _median([float(item["circuit_stream_latency_p50_ms"]) for item in subset]),
            "circuit_stream_latency_p95_ms_median": _median([float(item["circuit_stream_latency_p95_ms"]) for item in subset]),
            "all_integrity_checks_passed": all(item["integrity_verified"] for item in subset),
            "all_observability_checks_passed": all(item["relay_observability_check"] for item in subset),
            "all_cleanup_checks_passed": all(item["all_relay_connections_closed"] and item["active_proxy_connections_after_close"] == [0, 0, 0, 0] for item in subset),
        })

    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "finite equal-sized flow completion-rate fairness matrix",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "is_loopback_only": True,
            "is_real_wan_measurement": False,
            "is_packet_loss_simulation": False,
            "is_production_congestion_control_test": False,
            "fairness_metric": "Jain index calculated over finite-transfer per-stream goodput estimates derived from each stream's completion time",
            "warning": "This completion-rate index is an exploratory proxy, not steady-state fairness proof. User-space shaping preserves TCP reliability and is not a WAN or packet-loss simulation.",
        },
        "config": {
            "profile": profile_name,
            "stream_counts": counts,
            "trials": trials,
            "payload_bytes_per_stream": payload_bytes,
            "seed": seed,
            "hop_count": 3,
            "trial_order_by_trial": order_by_trial,
            "profile_bandwidth_mbps_per_direction": base_profile.bandwidth_mbps,
            "profile_latency_ms_per_direction": base_profile.latency_ms,
            "profile_jitter_ms_plus_minus": base_profile.jitter_ms,
        },
        "summary": summary,
        "runs": raw_runs,
        "limitations": [
            "All relays, proxies and destination run on one host using IPv4 loopback.",
            "Per-stream goodput uses finite transfer completion time and includes startup/teardown effects.",
            "Jain's index here is not a proof of fairness for long-lived flows or heterogeneous workloads.",
            "The proxy shapes TCP byte-stream chunks and does not simulate IP packet loss or retransmission behavior.",
            "Direct comparison has a different path length and does not offer equivalent anonymity.",
            "The protocol is custom, experimental and unaudited.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure completion-rate fairness across AEGIS loopback circuit streams")
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="metro")
    parser.add_argument("--stream-counts", type=_parse_stream_counts, default=[1, 2, 4, 8])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--payload-bytes", type=int, default=32 * 1024)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_fairness_matrix(
        profile_name=args.profile,
        stream_counts=args.stream_counts,
        trials=args.trials,
        payload_bytes=args.payload_bytes,
        seed=args.seed,
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
