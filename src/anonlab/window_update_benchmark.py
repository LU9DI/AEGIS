"""Sensitivity matrix for per-stream WINDOW_UPDATE credit batching.

The benchmark holds the default write scheduler fixed and changes only the
client's WINDOW_UPDATE byte threshold. Runs use shaped IPv4-loopback TCP paths;
they do not model IP packet loss, retransmission, or real-WAN congestion.
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
from typing import Any, Sequence

from . import __version__
from .mixed_workload_benchmark import run_mixed_workload_benchmark
from .network_impairment import DEFAULT_PROFILES
from .telescoping import MAX_STREAM_WINDOW_BYTES, WINDOW_UPDATE_BATCH_BYTES

DEFAULT_BATCH_SIZES = (16 * 1024, 32 * 1024, WINDOW_UPDATE_BATCH_BYTES, 128 * 1024)

# Deltas are intentionally reported rather than collapsed into one "winner"
# score; credit batching trades command frequency against feedback latency.
METRICS: dict[str, str] = {
    "bulk_goodput_mbps": "higher",
    "bulk_completion_ms": "lower",
    "early_interactive_rtt_p50_ms": "lower",
    "early_interactive_rtt_p95_ms": "lower",
    "late_interactive_rtt_p50_ms": "lower",
    "late_interactive_rtt_p95_ms": "lower",
    "window_update_commands": "context",
    "flow_pause_over_1ms_count": "lower",
    "flow_pause_over_1ms_total_ms": "lower",
}


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _validate_batch_sizes(batch_sizes: Sequence[int]) -> tuple[int, ...]:
    if not isinstance(batch_sizes, (list, tuple)) or not batch_sizes:
        raise ValueError("batch_sizes must be a non-empty list or tuple")
    normalized: list[int] = []
    for value in batch_sizes:
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_STREAM_WINDOW_BYTES:
            raise ValueError("each batch size must be within 1..262144")
        if value in normalized:
            raise ValueError("batch_sizes must not contain duplicates")
        normalized.append(value)
    if WINDOW_UPDATE_BATCH_BYTES not in normalized:
        raise ValueError("batch_sizes must include the default 65536-byte threshold as control")
    return tuple(normalized)


def summarize_batch_sensitivity(runs: list[dict[str, Any]], control_bytes: int = WINDOW_UPDATE_BATCH_BYTES) -> dict[str, Any]:
    """Summarize medians and paired deltas against the default 64 KiB threshold."""
    if not isinstance(control_bytes, int) or isinstance(control_bytes, bool) or not 1 <= control_bytes <= MAX_STREAM_WINDOW_BYTES:
        raise ValueError(f"control_bytes must be within 1..{MAX_STREAM_WINDOW_BYTES}")
    by_batch: dict[int, list[dict[str, Any]]] = {}
    for row in runs:
        batch = row.get("window_update_batch_bytes")
        if not isinstance(batch, int) or isinstance(batch, bool):
            raise ValueError("each run must have an integer window_update_batch_bytes")
        by_batch.setdefault(batch, []).append(row)

    if control_bytes not in by_batch:
        raise ValueError(f"control batch size {control_bytes} is missing")

    control_by_trial = {int(row["trial"]): row for row in by_batch[control_bytes]}
    summary: dict[str, Any] = {}
    for batch in sorted(by_batch):
        rows_for_batch = by_batch[batch]
        per_metric: dict[str, Any] = {}
        for metric, direction in METRICS.items():
            values = [float(row[metric]) for row in rows_for_batch if row.get(metric) is not None]
            control_values = [float(row[metric]) for row in by_batch[control_bytes] if row.get(metric) is not None]
            paired_pct: list[float] = []
            wins = losses = ties = 0
            paired_count = 0
            for row in rows_for_batch:
                trial = int(row["trial"])
                control = control_by_trial.get(trial)
                if control is None or row.get(metric) is None or control.get(metric) is None:
                    continue
                candidate = float(row[metric])
                baseline = float(control[metric])
                paired_count += 1
                if baseline != 0:
                    paired_pct.append((candidate / baseline - 1.0) * 100.0)
                if candidate == baseline:
                    ties += 1
                elif direction == "higher":
                    wins += int(candidate > baseline)
                    losses += int(candidate < baseline)
                elif direction == "lower":
                    wins += int(candidate < baseline)
                    losses += int(candidate > baseline)
            median = _median(values)
            control_median = _median(control_values)
            per_metric[metric] = {
                "preference": direction,
                "median": median,
                "control_median": control_median,
                "median_delta_vs_control_percent": (
                    (median / control_median - 1.0) * 100.0
                    if median is not None and control_median not in (None, 0.0) else None
                ),
                "median_paired_trial_delta_percent": _median(paired_pct),
                "paired_trials": paired_count,
                "wins_vs_control": wins,
                "losses_vs_control": losses,
                "ties_vs_control": ties,
            }
        summary[str(batch)] = {
            "window_update_batch_bytes": batch,
            "trials": len(rows_for_batch),
            "metrics": per_metric,
        }
    return summary


async def run_window_update_sensitivity(
    *,
    profile_name: str = "metro",
    trials: int = 3,
    batch_sizes: Sequence[int] = DEFAULT_BATCH_SIZES,
    bulk_bytes: int = 256 * 1024,
    interactive_requests: int = 5,
    request_bytes: int = 128,
    request_gap_ms: float = 5.0,
    stagger_after_ms: float = 20.0,
    write_chunk_bytes: int = 16 * 1024,
    pipeline_depth: int = 4,
    seed: int = 20261024,
) -> dict[str, Any]:
    if profile_name not in DEFAULT_PROFILES:
        raise ValueError("profile_name must identify a named impairment profile")
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    thresholds = _validate_batch_sizes(batch_sizes)
    if not isinstance(bulk_bytes, int) or isinstance(bulk_bytes, bool) or not 1024 <= bulk_bytes <= 1024 * 1024:
        raise ValueError("bulk_bytes must be within 1024..1048576")
    if not isinstance(interactive_requests, int) or isinstance(interactive_requests, bool) or not 1 <= interactive_requests <= 100:
        raise ValueError("interactive_requests must be within 1..100")

    rows: list[dict[str, Any]] = []
    order_by_trial: list[dict[str, Any]] = []
    base_profile = DEFAULT_PROFILES[profile_name]
    for trial_idx in range(trials):
        # Rotate the order so a given threshold does not always run first or last.
        shift = trial_idx % len(thresholds)
        order = thresholds[shift:] + thresholds[:shift]
        order_by_trial.append({"trial": trial_idx + 1, "batch_sizes_in_order": list(order)})
        # Each candidate shares the configured shaper seed within a trial.
        run_seed = seed + trial_idx * 1_000_003
        for batch_bytes in order:
            profile = replace(base_profile, seed=base_profile.seed + run_seed % 1_000_000_007)
            run = await run_mixed_workload_benchmark(
                profile=profile,
                bulk_bytes=bulk_bytes,
                interactive_requests=interactive_requests,
                request_bytes=request_bytes,
                request_gap_ms=request_gap_ms,
                stagger_after_ms=stagger_after_ms,
                write_chunk_bytes=write_chunk_bytes,
                pipeline_depth=pipeline_depth,
                fair_write_scheduling=False,
                window_update_batch_bytes=batch_bytes,
                seed=run_seed,
            )
            result = run["results"]
            exit_relay = result["relay_stage_diagnostics"][2]
            flow_pause = exit_relay["flow_control_pause_summary"]
            row = {
                "trial": trial_idx + 1,
                "seed": run_seed,
                "window_update_batch_bytes": batch_bytes,
                "window_update_batch_kib": batch_bytes / 1024.0,
                "bulk_goodput_mbps": result["bulk"]["goodput_mbps"],
                "bulk_completion_ms": result["bulk"]["completion_ms"],
                "bulk_time_to_first_byte_ms": result["bulk"]["time_to_first_byte_ms"],
                "early_interactive_rtt_p50_ms": result["early_interactive"]["request_rtt_p50_ms"],
                "early_interactive_rtt_p95_ms": result["early_interactive"]["request_rtt_p95_ms"],
                "late_interactive_rtt_p50_ms": result["staggered_interactive"]["request_rtt_p50_ms"],
                "late_interactive_rtt_p95_ms": result["staggered_interactive"]["request_rtt_p95_ms"],
                "window_update_commands": int(exit_relay["command_counts"].get("window_update", 0)),
                "flow_credit_wait_samples": int(flow_pause["wait_samples"]),
                "flow_pause_over_1ms_count": int(flow_pause["pauses_over_threshold"]),
                "flow_pause_over_1ms_total_ms": float(flow_pause["time_over_threshold_ms"]),
                "flow_pause_longest_over_1ms_ms": float(flow_pause["longest_pause_ms"]),
                "destination_read_wait_p95_ms": float(exit_relay["summary_by_stage"].get("destination_read_wait", {}).get("p95_ms", 0.0)),
                "destination_write_drain_p95_ms": float(exit_relay["summary_by_stage"].get("destination_write_drain", {}).get("p95_ms", 0.0)),
                "late_flow_started_while_bulk_active": bool(result["staggered_flow_started_while_bulk_active"]),
                "integrity_verified": bool(result["integrity_verified"]),
                "relay_observability_check": bool(result["relay_observability_check"]),
                "resources_closed": bool(result["resources_closed"]),
                "all_relays_event_buffers_bounded": all(
                    relay["event_count"] <= 8192 and relay["dropped_events"] == 0
                    for relay in result["relay_stage_diagnostics"]
                ),
            }
            rows.append(row)

    summary = summarize_batch_sensitivity(rows)
    checks_passed = all(
        row["integrity_verified"] and row["relay_observability_check"]
        and row["resources_closed"] and row["all_relays_event_buffers_bounded"]
        for row in rows
    )
    late_flows_overlapped = all(row["late_flow_started_while_bulk_active"] for row in rows)
    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "WINDOW_UPDATE byte-threshold sensitivity under mixed bulk and interactive load",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "loopback_only": True,
            "real_wan_measurement": False,
            "packet_loss_simulation": False,
            "production_congestion_test": False,
            "scheduler_held_constant": "default (fair_write_scheduling=False)",
            "default_control_bytes": WINDOW_UPDATE_BATCH_BYTES,
            "interpretation_warning": "Small finite-flow loopback experiment; paired seeds do not make TCP shaping traces identical when timing changes.",
        },
        "config": {
            "profile": profile_name,
            "trials_per_threshold": trials,
            "batch_sizes_bytes": list(thresholds),
            "bulk_bytes": bulk_bytes,
            "interactive_requests": interactive_requests,
            "request_bytes": request_bytes,
            "request_gap_ms": request_gap_ms,
            "stagger_after_ms": stagger_after_ms,
            "write_chunk_bytes": write_chunk_bytes,
            "pipeline_depth": pipeline_depth,
            "seed": seed,
            "order_by_trial": order_by_trial,
            "paired_seed_policy": "same configured shaper seed for each threshold within a trial; threshold execution order rotates",
        },
        "summary": summary,
        "runs": rows,
        "all_integrity_cleanup_and_bounds_checks_passed": checks_passed,
        "all_late_flows_started_during_bulk": late_flows_overlapped,
        "limitations": [
            "Relays, shaping proxies and echo destination run on one host over IPv4 loopback.",
            "The proxy shapes TCP byte-stream chunks; it does not simulate IP packet loss or retransmissions.",
            "A smaller WINDOW_UPDATE threshold increases control-command frequency; a larger threshold can delay credit return until either the threshold or short flush timeout is reached.",
            "The two-millisecond delayed flush remains fixed in this matrix, so results isolate the byte threshold, not the timer.",
            "Relay metrics are bounded and payload-free but add measurement overhead and expose timing metadata.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep AEGIS WINDOW_UPDATE credit-batching thresholds")
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="metro")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=list(DEFAULT_BATCH_SIZES))
    parser.add_argument("--bulk-bytes", type=int, default=256 * 1024)
    parser.add_argument("--interactive-requests", type=int, default=5)
    parser.add_argument("--request-bytes", type=int, default=128)
    parser.add_argument("--request-gap-ms", type=float, default=5.0)
    parser.add_argument("--stagger-after-ms", type=float, default=20.0)
    parser.add_argument("--write-chunk-bytes", type=int, default=16 * 1024)
    parser.add_argument("--pipeline-depth", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_window_update_sensitivity(
        profile_name=args.profile,
        trials=args.trials,
        batch_sizes=args.batch_sizes,
        bulk_bytes=args.bulk_bytes,
        interactive_requests=args.interactive_requests,
        request_bytes=args.request_bytes,
        request_gap_ms=args.request_gap_ms,
        stagger_after_ms=args.stagger_after_ms,
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
