"""Short soak: alternate two arms for N seconds and check for drift.

This is a *short* sustained loopback load (minutes, not hours). It repeats the
full 1 MiB workload and reports drift between the first and second half plus
RSS growth; it is not a durability test and not a WAN test.

Usage:
    python experiments/thor-p2-lab/soak.py --seconds 120 --output experiments/thor-p2-lab/soak-01
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import statistics
import time

from anonlab.thor_p2_lab.runner import WORKLOADS, percentile, run_trial
from anonlab.thor_p2_lab.variants import VARIANTS


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p95": None, "count": 0}
    return {
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "count": len(values),
    }


async def soak(arms: list[str], workload: str, seconds: float, seed: int) -> dict:
    spec = WORKLOADS[workload]
    rows: list[dict] = []
    started = time.perf_counter()
    trial = 0
    while time.perf_counter() - started < seconds:
        for arm in arms:
            result = await run_trial(VARIANTS[arm], spec, seed=seed + trial)
            rows.append({"arm": arm, "trial": trial, **result.payload})
            trial += 1
        if trial and trial % 20 == 0:
            print(f"{time.perf_counter() - started:6.1f}s / {trial} trials", flush=True)
    elapsed = time.perf_counter() - started

    report: dict = {
        "schema_version": 1,
        "kind": "short_soak",
        "workload": workload,
        "workload_config": spec.to_dict(),
        "seconds_requested": seconds,
        "seconds_elapsed": elapsed,
        "arms": arms,
        "trials": len(rows),
        "integrity_all_ok": all(
            row["integrity"]["verified"] for row in rows
        ),
        "per_arm": {},
    }
    for arm in arms:
        arm_rows = [row for row in rows if row["arm"] == arm]
        goodputs = [row["transfer"]["goodput_mbps"] for row in arm_rows]
        half = len(goodputs) // 2
        first = _summary(goodputs[:half])["median"] if half else None
        second = _summary(goodputs[half:])["median"] if half else None
        rss_start = arm_rows[0]["resources"]["rss_start_kb"] if arm_rows else None
        rss_end = arm_rows[-1]["resources"]["rss_end_kb"] if arm_rows else None
        peaks = [row["resources"]["peak_rss_kb"] for row in arm_rows
                 if row["resources"]["peak_rss_kb"]]
        report["per_arm"][arm] = {
            "trials": len(arm_rows),
            "goodput_mbps": _summary(goodputs),
            "goodput_drift_second_half_over_first": (
                second / first if first and second else None
            ),
            "ttfb_ms": _summary([row["transfer"]["ttfb_ms_median"] for row in arm_rows
                                 if row["transfer"]["ttfb_ms_median"]]),
            "read_p99_ms": _summary([row["transfer"]["read_latency_ms_p99"] for row in arm_rows
                                     if row["transfer"]["read_latency_ms_p99"]]),
            "rss_start_kb": rss_start,
            "rss_end_kb": rss_end,
            "peak_rss_kb": max(peaks) if peaks else None,
            "rss_growth_kb": (rss_end - rss_start) if rss_start and rss_end else None,
            "window_updates_median": statistics.median(
                [row["counts"]["window_update_count"] for row in arm_rows]
            ) if arm_rows else None,
            "errors": [row["integrity"]["errors"] for row in arm_rows
                       if row["integrity"]["errors"]],
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--workload", default="bulk_1mib_c16k")
    parser.add_argument("--arms", default="control,credit-policy-window-aware")
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    arms = [name.strip() for name in args.arms.split(",") if name.strip()]
    report = asyncio.run(soak(arms, args.workload, args.seconds, args.seed))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "soak.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["per_arm"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
