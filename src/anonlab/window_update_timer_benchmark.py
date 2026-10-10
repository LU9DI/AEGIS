"""Sensitivity matrix for the sparse-stream WINDOW_UPDATE flush timer.

The byte credit threshold and write scheduler remain fixed while the maximum
wait before flushing sub-threshold receive credit varies. Results are local
loopback experiments, not claims about WAN latency or production congestion.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .mixed_workload_benchmark import run_mixed_workload_benchmark
from .network_impairment import DEFAULT_PROFILES
from .telescoping import WINDOW_UPDATE_BATCH_BYTES, WINDOW_UPDATE_MAX_DELAY_SECONDS

DEFAULT_TIMER_VALUES_MS = (0.5, WINDOW_UPDATE_MAX_DELAY_SECONDS * 1000.0, 5.0)
CONTROL_TIMER_MS = WINDOW_UPDATE_MAX_DELAY_SECONDS * 1000.0
METRICS: dict[str, str] = {
    "bulk_goodput_mbps": "higher",
    "bulk_completion_ms": "lower",
    "bulk_time_to_first_byte_ms": "lower",
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


def _validate_timer_values(timer_values_ms: Sequence[float]) -> tuple[float, ...]:
    if not isinstance(timer_values_ms, (tuple, list)) or not timer_values_ms:
        raise ValueError("timer_values_ms must be a non-empty list or tuple")
    normalized: list[float] = []
    for value in timer_values_ms:
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or not 0.1 <= float(value) <= 100.0):
            raise ValueError("each timer value must be finite and within 0.1..100 ms")
        value = float(value)
        if value in normalized:
            raise ValueError("timer_values_ms must not contain duplicates")
        normalized.append(value)
    if CONTROL_TIMER_MS not in normalized:
        raise ValueError(f"timer_values_ms must include the default {CONTROL_TIMER_MS:g} ms control")
    return tuple(normalized)


def summarize_timer_sensitivity(runs: list[dict[str, Any]], control_timer_ms: float = CONTROL_TIMER_MS) -> dict[str, Any]:
    """Summarize each timer value with medians and paired per-trial deltas."""
    if (not isinstance(control_timer_ms, (int, float)) or isinstance(control_timer_ms, bool)
            or not math.isfinite(control_timer_ms) or not 0.1 <= control_timer_ms <= 100.0):
        raise ValueError("control_timer_ms must be finite and within 0.1..100 ms")
    by_timer: dict[float, list[dict[str, Any]]] = {}
    for row in runs:
        value = row.get("window_update_max_delay_ms")
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value)):
            raise ValueError("each run must have a finite window_update_max_delay_ms")
        by_timer.setdefault(float(value), []).append(row)
    control_key = float(control_timer_ms)
    if control_key not in by_timer:
        raise ValueError(f"control timer {control_timer_ms:g} ms is missing")
    control_by_trial = {int(row["trial"]): row for row in by_timer[control_key]}
    summary: dict[str, Any] = {}
    for timer_ms in sorted(by_timer):
        candidates = by_timer[timer_ms]
        per_metric: dict[str, Any] = {}
        for metric, direction in METRICS.items():
            values = [float(row[metric]) for row in candidates if row.get(metric) is not None]
            control_values = [float(row[metric]) for row in by_timer[control_key] if row.get(metric) is not None]
            paired_pct: list[float] = []
            wins = losses = ties = paired_trials = 0
            for row in candidates:
                control = control_by_trial.get(int(row["trial"]))
                if control is None or row.get(metric) is None or control.get(metric) is None:
                    continue
                candidate, baseline = float(row[metric]), float(control[metric])
                paired_trials += 1
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
                "paired_trials": paired_trials,
                "wins_vs_control": wins,
                "losses_vs_control": losses,
                "ties_vs_control": ties,
            }
        summary[f"{timer_ms:g}"] = {
            "window_update_max_delay_ms": timer_ms,
            "trials": len(candidates),
            "metrics": per_metric,
        }
    return summary


async def run_window_update_timer_sensitivity(
    *,
    profile_name: str = "metro",
    trials: int = 3,
    timer_values_ms: Sequence[float] = DEFAULT_TIMER_VALUES_MS,
    batch_bytes: int = WINDOW_UPDATE_BATCH_BYTES,
    bulk_bytes: int = 256 * 1024,
    interactive_requests: int = 5,
    request_bytes: int = 128,
    request_gap_ms: float = 5.0,
    stagger_after_ms: float = 20.0,
    write_chunk_bytes: int = 16 * 1024,
    pipeline_depth: int = 4,
    seed: int = 20261025,
) -> dict[str, Any]:
    if profile_name not in DEFAULT_PROFILES:
        raise ValueError("profile_name must identify a named impairment profile")
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if not isinstance(batch_bytes, int) or isinstance(batch_bytes, bool) or not 1 <= batch_bytes <= 256 * 1024:
        raise ValueError("batch_bytes must be within 1..262144")
    timers = _validate_timer_values(timer_values_ms)
    rows: list[dict[str, Any]] = []
    order_by_trial: list[dict[str, Any]] = []
    base_profile = DEFAULT_PROFILES[profile_name]
    for trial_idx in range(trials):
        shift = trial_idx % len(timers)
        order = timers[shift:] + timers[:shift]
        order_by_trial.append({"trial": trial_idx + 1, "timers_ms_in_order": list(order)})
        run_seed = seed + trial_idx * 1_000_003
        for timer_ms in order:
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
                window_update_max_delay_seconds=timer_ms / 1000.0,
                seed=run_seed,
            )
            result = run["results"]
            exit_relay = result["relay_stage_diagnostics"][2]
            flow_pause = exit_relay["flow_control_pause_summary"]
            rows.append({
                "trial": trial_idx + 1,
                "seed": run_seed,
                "window_update_max_delay_ms": timer_ms,
                "window_update_batch_bytes": batch_bytes,
                "bulk_goodput_mbps": float(result["bulk"]["goodput_mbps"]),
                "bulk_completion_ms": float(result["bulk"]["completion_ms"]),
                "bulk_time_to_first_byte_ms": float(result["bulk"]["time_to_first_byte_ms"] or 0.0),
                "early_interactive_rtt_p50_ms": float(result["early_interactive"]["request_rtt_p50_ms"]),
                "early_interactive_rtt_p95_ms": float(result["early_interactive"]["request_rtt_p95_ms"]),
                "late_interactive_rtt_p50_ms": float(result["staggered_interactive"]["request_rtt_p50_ms"]),
                "late_interactive_rtt_p95_ms": float(result["staggered_interactive"]["request_rtt_p95_ms"]),
                "window_update_commands": int(exit_relay["command_counts"].get("window_update", 0)),
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
                "configured_batch_bytes_match": run["config"]["window_update_batch_bytes"] == batch_bytes,
                "configured_timer_matches": abs(run["config"]["window_update_max_delay_ms"] - timer_ms) < 1e-9,
            })
    summary = summarize_timer_sensitivity(rows)
    checks_passed = all(
        row["integrity_verified"] and row["relay_observability_check"] and row["resources_closed"]
        and row["all_relays_event_buffers_bounded"] and row["configured_batch_bytes_match"]
        and row["configured_timer_matches"] for row in rows
    )
    late_flows_overlapped = all(row["late_flow_started_while_bulk_active"] for row in rows)
    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "WINDOW_UPDATE sparse-credit flush timer sensitivity under mixed bulk and interactive load",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "loopback_only": True,
            "real_wan_measurement": False,
            "packet_loss_simulation": False,
            "production_congestion_test": False,
            "scheduler_held_constant": "default (fair_write_scheduling=False)",
            "batch_threshold_held_constant_bytes": batch_bytes,
            "default_control_timer_ms": CONTROL_TIMER_MS,
            "interpretation_warning": "Small finite-flow loopback experiment; paired seeds control configured random seeds, not identical TCP-shaper timing traces.",
        },
        "config": {
            "profile": profile_name,
            "trials_per_timer": trials,
            "timer_values_ms": list(timers),
            "batch_threshold_bytes": batch_bytes,
            "bulk_bytes": bulk_bytes,
            "interactive_requests": interactive_requests,
            "request_bytes": request_bytes,
            "request_gap_ms": request_gap_ms,
            "stagger_after_ms": stagger_after_ms,
            "write_chunk_bytes": write_chunk_bytes,
            "pipeline_depth": pipeline_depth,
            "seed": seed,
            "order_by_trial": order_by_trial,
            "paired_seed_policy": "same configured shaper seed for all timer values within each trial; timer order rotates",
        },
        "summary": summary,
        "runs": rows,
        "all_integrity_cleanup_configuration_and_bounds_checks_passed": checks_passed,
        "all_late_flows_started_during_bulk": late_flows_overlapped,
        "limitations": [
            "Relays, TCP shaping proxies and the echo destination run on one host over IPv4 loopback.",
            "The proxy shapes TCP byte-stream chunks; it does not simulate IP packet loss or TCP retransmissions.",
            "Only the receive-credit flush timer was varied; the byte threshold and write scheduler remain fixed.",
            "Timer values are upper bounds while read_chunk waits with pending sub-threshold credit; this is not a timer on every WINDOW_UPDATE.",
            "Relay telemetry is bounded and payload-free but adds measurement overhead and exposes timing metadata.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep AEGIS WINDOW_UPDATE sparse-credit flush timer values")
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="metro")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timer-values-ms", type=float, nargs="+", default=list(DEFAULT_TIMER_VALUES_MS))
    parser.add_argument("--batch-bytes", type=int, default=WINDOW_UPDATE_BATCH_BYTES)
    parser.add_argument("--bulk-bytes", type=int, default=256 * 1024)
    parser.add_argument("--interactive-requests", type=int, default=5)
    parser.add_argument("--request-bytes", type=int, default=128)
    parser.add_argument("--request-gap-ms", type=float, default=5.0)
    parser.add_argument("--stagger-after-ms", type=float, default=20.0)
    parser.add_argument("--write-chunk-bytes", type=int, default=16 * 1024)
    parser.add_argument("--pipeline-depth", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--seed", type=int, default=20261025)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_window_update_timer_sensitivity(
        profile_name=args.profile, trials=args.trials, timer_values_ms=args.timer_values_ms,
        batch_bytes=args.batch_bytes, bulk_bytes=args.bulk_bytes,
        interactive_requests=args.interactive_requests, request_bytes=args.request_bytes,
        request_gap_ms=args.request_gap_ms, stagger_after_ms=args.stagger_after_ms,
        write_chunk_bytes=args.write_chunk_bytes, pipeline_depth=args.pipeline_depth, seed=args.seed,
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
