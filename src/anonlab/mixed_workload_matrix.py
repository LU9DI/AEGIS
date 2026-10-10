"""Configuration matrix for mixed-workload scheduler experiments.

Runs paired baseline/round-robin comparisons across a small, declared set of
profiles and pipeline settings. This is exploratory loopback research, not a
real-WAN benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import platform
from pathlib import Path
from typing import Any

from . import __version__
from .mixed_workload_benchmark import run_mixed_scheduler_comparison

# Keep the matrix deliberately compact and interpretable: first hold workload
# fixed and vary shaping, then vary pipeline depth, then increase bulk size.
DEFAULT_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "loopback-pipeline-1-256k",
        "profile_name": "loopback",
        "bulk_bytes": 256 * 1024,
        "write_chunk_bytes": 16 * 1024,
        "pipeline_depth": 1,
    },
    {
        "case_id": "metro-pipeline-1-256k",
        "profile_name": "metro",
        "bulk_bytes": 256 * 1024,
        "write_chunk_bytes": 16 * 1024,
        "pipeline_depth": 1,
    },
    {
        "case_id": "metro-pipeline-4-256k",
        "profile_name": "metro",
        "bulk_bytes": 256 * 1024,
        "write_chunk_bytes": 16 * 1024,
        "pipeline_depth": 4,
    },
    {
        "case_id": "metro-pipeline-4-1m",
        "profile_name": "metro",
        "bulk_bytes": 1024 * 1024,
        "write_chunk_bytes": 64 * 1024,
        "pipeline_depth": 4,
    },
)

# Explicit direction indicates whether larger or smaller is preferable.
METRICS: dict[str, str] = {
    "bulk_goodput_mbps": "higher",
    "bulk_time_to_first_byte_ms": "lower",
    "bulk_completion_ms": "lower",
    "early_interactive_first_response_rtt_ms": "lower",
    "early_interactive_rtt_p50_ms": "lower",
    "early_interactive_rtt_p95_ms": "lower",
    "early_interactive_completion_ms": "lower",
    "late_interactive_first_response_rtt_ms": "lower",
    "late_interactive_rtt_p50_ms": "lower",
    "late_interactive_rtt_p95_ms": "lower",
    "late_interactive_completion_ms": "lower",
}


def summarize_paired_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize paired per-trial deltas, not just differences between medians."""
    by_trial: dict[int, dict[str, dict[str, Any]]] = {}
    for row in runs:
        by_trial.setdefault(int(row["trial"]), {})[str(row["scheduler"])] = row

    missing_pairs = [
        trial for trial, conditions in by_trial.items()
        if not {"baseline", "round_robin"}.issubset(conditions)
    ]
    if missing_pairs:
        raise ValueError(f"missing paired scheduler condition for trial(s): {missing_pairs}")

    result: dict[str, Any] = {}
    for metric, direction in METRICS.items():
        pairs: list[dict[str, float]] = []
        for trial in sorted(by_trial):
            conditions = by_trial[trial]
            baseline = conditions["baseline"].get(metric)
            round_robin = conditions["round_robin"].get(metric)
            if baseline is None or round_robin is None:
                continue
            baseline_f = float(baseline)
            rr_f = float(round_robin)
            pct = ((rr_f / baseline_f) - 1.0) * 100.0 if baseline_f else None
            if direction == "higher":
                rr_win = rr_f > baseline_f
            else:
                rr_win = rr_f < baseline_f
            tie = rr_f == baseline_f
            pairs.append({
                "trial": float(trial),
                "baseline": baseline_f,
                "round_robin": rr_f,
                "delta_percent": pct if pct is not None else float("nan"),
                "round_robin_win": float(rr_win),
                "tie": float(tie),
            })
        valid_delta = [p["delta_percent"] for p in pairs if p["delta_percent"] == p["delta_percent"]]
        result[metric] = {
            "direction": direction,
            "paired_trials": len(pairs),
            "baseline_median": float(statistics.median(p["baseline"] for p in pairs)) if pairs else None,
            "round_robin_median": float(statistics.median(p["round_robin"] for p in pairs)) if pairs else None,
            "median_paired_delta_percent": float(statistics.median(valid_delta)) if valid_delta else None,
            "round_robin_wins": int(sum(p["round_robin_win"] for p in pairs)),
            "baseline_wins": int(sum(
                1 for p in pairs if p["round_robin_win"] == 0 and p["tie"] == 0
            )),
            "ties": int(sum(p["tie"] for p in pairs)),
        }
    return result


async def run_mixed_workload_matrix(
    *, trials: int = 5, seed: int = 20261023,
    interactive_requests: int = 5, request_bytes: int = 128,
    request_gap_ms: float = 5.0, stagger_after_ms: float = 20.0,
) -> dict[str, Any]:
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    case_results: list[dict[str, Any]] = []
    for index, case in enumerate(DEFAULT_CASES):
        # Loopback transfers can finish in less than the default 20 ms. Start
        # the third stream after 1 ms in that case so the run genuinely tests
        # contention instead of measuring a post-transfer connection.
        effective_stagger_after_ms = min(stagger_after_ms, 1.0) if case["profile_name"] == "loopback" else stagger_after_ms
        comparison = await run_mixed_scheduler_comparison(
            profile_name=case["profile_name"], trials=trials,
            bulk_bytes=case["bulk_bytes"],
            interactive_requests=interactive_requests,
            request_bytes=request_bytes,
            request_gap_ms=request_gap_ms,
            stagger_after_ms=effective_stagger_after_ms,
            write_chunk_bytes=case["write_chunk_bytes"],
            pipeline_depth=case["pipeline_depth"],
            seed=seed + index * 10_000_019,
        )
        case_config = dict(case)
        case_config["effective_stagger_after_ms"] = effective_stagger_after_ms
        case_results.append({
            "case": case_config,
            "summary": comparison["summary"],
            "paired_analysis": summarize_paired_runs(comparison["runs"]),
            "runs": comparison["runs"],
            "all_integrity_and_cleanup_checks_passed": comparison["all_integrity_and_cleanup_checks_passed"],
            "all_late_flows_started_during_bulk": comparison["all_late_flows_started_during_bulk"],
        })

    all_passed = all(c["all_integrity_and_cleanup_checks_passed"] for c in case_results)
    return {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "mixed-workload paired scheduler sensitivity matrix",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "loopback_only": True,
            "real_wan_measurement": False,
            "note": "Use paired deltas and raw trial values; a small matrix cannot establish universal scheduler superiority.",
        },
        "config": {
            "trials_per_scheduler_per_case": trials,
            "seed": seed,
            "interactive_requests": interactive_requests,
            "request_bytes": request_bytes,
            "request_gap_ms": request_gap_ms,
            "stagger_after_ms": stagger_after_ms,
            "case_count": len(DEFAULT_CASES),
            "total_scheduler_runs_expected": len(DEFAULT_CASES) * trials * 2,
        },
        "cases": case_results,
        "all_integrity_and_cleanup_checks_passed": all_passed,
        "all_late_flows_started_during_bulk": all(c["all_late_flows_started_during_bulk"] for c in case_results),
        "decision_rule": "Do not promote round-robin to default based on this matrix alone; require consistent paired interactive improvements without unacceptable bulk regressions across profiles and pipeline settings.",
        "limitations": [
            "Single-host IPv4 loopback; no real-WAN measurement.",
            "Proxy shapes TCP byte-stream traffic and does not model packet loss/retransmission.",
            "Finite-flow test does not prove steady-state fairness or production congestion control.",
            "No cryptographic audit, anonymity proof, or global-observer resistance evaluation is performed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a matrix of paired mixed-workload scheduler benchmarks")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--interactive-requests", type=int, default=5)
    parser.add_argument("--request-bytes", type=int, default=128)
    parser.add_argument("--request-gap-ms", type=float, default=5.0)
    parser.add_argument("--stagger-after-ms", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_mixed_workload_matrix(
        trials=args.trials, seed=args.seed,
        interactive_requests=args.interactive_requests,
        request_bytes=args.request_bytes,
        request_gap_ms=args.request_gap_ms,
        stagger_after_ms=args.stagger_after_ms,
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
