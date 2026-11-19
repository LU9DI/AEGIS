"""Campaign runner: interleaved, seeded, paired comparison of P2 variants.

Protocol of the campaign (fixed in code, reported with the artifacts):

* warmup: one discarded trial per (workload, arm) before any measurement;
* 7 valid trials per (workload, arm), arm order rotated per trial so no arm
  always runs first or last;
* the same payload seed is used by every arm within a trial, so per-trial
  differences are paired;
* every trial rebuilds the whole testbed (fresh relays, keys, replay guards) so
  no state leaks between trials;
* failures are recorded, never replaced by a retry that hides them.
"""
from __future__ import annotations

import asyncio
import json
import platform
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import __version__
from .runner import WORKLOADS, LabWorkload, percentile, run_trial
from .variants import VARIANTS, VariantSpec

__all__ = ["CampaignConfig", "run_campaign", "summarize"]

DEFAULT_TRIALS = 7
DEFAULT_WARMUPS = 1
BOOTSTRAP_SAMPLES = 4000


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    arms: tuple[str, ...]
    workloads: tuple[str, ...]
    trials: int = DEFAULT_TRIALS
    warmups: int = DEFAULT_WARMUPS
    base_seed: int = 20261118
    bootstrap_seed: int = 7717

    def __post_init__(self) -> None:
        if not self.arms or "control" not in self.arms:
            raise ValueError("the campaign must include the control arm")
        for name in self.arms:
            if name not in VARIANTS:
                raise ValueError(f"unknown arm {name!r}")
        for name in self.workloads:
            if name not in WORKLOADS:
                raise ValueError(f"unknown workload {name!r}")
        if not 3 <= self.trials <= 50:
            raise ValueError("trials must be within 3..50")
        if not 0 <= self.warmups <= 5:
            raise ValueError("warmups must be within 0..5")


def _git_state() -> dict[str, Any]:
    def _run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], capture_output=True, text=True, check=False, timeout=20
            ).stdout.strip()
        except Exception:  # noqa: BLE001 - provenance must never break a run
            return ""

    return {
        "commit": _run("rev-parse", "HEAD"),
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
        # Only tracked modifications count: campaign artifacts are written
        # untracked while the run is in progress and are not code changes.
        "dirty": bool(_run("status", "--porcelain", "--untracked-files=no")),
    }


def _trial_seed(base: int, workload: str, trial: int) -> int:
    digest = sum(ord(ch) for ch in workload) * 101
    return base + trial * 1009 + digest


def _ordered_arms(arms: tuple[str, ...], workload: str, trial: int, warmup: bool) -> list[str]:
    """Rotate the arm order deterministically: no arm is always first or last."""
    order = list(arms)
    rotation = (trial * 3 + len(workload)) % len(order)
    if warmup:
        rotation = (rotation + 1) % len(order)
    return order[rotation:] + order[:rotation]


def _bootstrap_median_ci(values: list[float], *, seed: int) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    if len(values) == 1:
        return values[0], values[0], values[0]
    rng = random.Random(seed)
    medians = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [values[rng.randrange(len(values))] for _ in values]
        medians.append(statistics.median(sample))
    medians.sort()
    low = medians[int(0.025 * (len(medians) - 1))]
    high = medians[int(0.975 * (len(medians) - 1))]
    return statistics.median(values), low, high


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _metric(trial: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = trial
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize(trials: list[dict[str, Any]], config: CampaignConfig) -> dict[str, Any]:
    """Aggregate raw trials into per-arm summaries with paired comparisons."""
    by_cell: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    for trial in trials:
        key = (trial["workload"], trial["variant"])
        by_cell.setdefault(key, {})[trial["seed"]] = trial

    goodput_path = ("transfer", "goodput_mbps")
    wall_path = ("transfer", "wall_ms")
    ttfb_path = ("transfer", "ttfb_ms_median")
    p95_path = ("transfer", "read_latency_ms_p95")
    p99_path = ("transfer", "read_latency_ms_p99")
    ack_wait_path = ("waits", "downstream_response_wait_ms")
    credit_wait_path = ("waits", "flow_credit_wait_ms")

    summary: dict[str, Any] = {"cells": {}, "paired": {}}
    for workload in config.workloads:
        control = by_cell.get((workload, "control"), {})
        for arm in config.arms:
            cell = by_cell.get((workload, arm), {})
            if not cell:
                continue
            goodputs = [v for v in (_metric(t, goodput_path) for t in cell.values()) if v]
            walls = [v for v in (_metric(t, wall_path) for t in cell.values()) if v]
            ttfbs = [v for v in (_metric(t, ttfb_path) for t in cell.values()) if v]
            p95s = [v for v in (_metric(t, p95_path) for t in cell.values()) if v]
            p99s = [v for v in (_metric(t, p99_path) for t in cell.values()) if v]
            acks = [v for v in (_metric(t, ack_wait_path) for t in cell.values()) if v is not None]
            credits = [v for v in (_metric(t, credit_wait_path) for t in cell.values()) if v is not None]
            events = [float(t["counts"]["client_visible_events"]) for t in cell.values()]
            vupds = [float(t["counts"]["window_update_count"]) for t in cell.values()]
            aead = [float(t["counts"]["aead_ops_per_kib"] or 0) for t in cell.values()]
            rss = [float(t["resources"]["peak_rss_kb"] or 0) for t in cell.values()]
            integrity = all(bool(t["integrity"]["verified"]) for t in cell.values())
            errors = [t["integrity"]["errors"] for t in cell.values() if t["integrity"]["errors"]]

            paired_goodput: list[float] = []
            paired_wall: list[float] = []
            paired_ack_wait: list[float] = []
            paired_credit_wait: list[float] = []
            paired_p95: list[float] = []
            paired_p99: list[float] = []
            if arm != "control":
                for seed, trial in cell.items():
                    reference = control.get(seed)
                    if not reference:
                        continue
                    for target, path in (
                        (paired_goodput, goodput_path),
                        (paired_wall, wall_path),
                        (paired_ack_wait, ack_wait_path),
                        (paired_credit_wait, credit_wait_path),
                        (paired_p95, p95_path),
                        (paired_p99, p99_path),
                    ):
                        value = _ratio(_metric(trial, path), _metric(reference, path))
                        if value is not None:
                            target.append(value)

            def _ci(values: list[float], salt: int) -> dict[str, float | None]:
                median, low, high = _bootstrap_median_ci(values, seed=config.bootstrap_seed + salt)
                return {"median": median, "ci_low": low, "ci_high": high, "samples": len(values)}

            summary["cells"][f"{workload}/{arm}"] = {
                "workload": workload,
                "arm": arm,
                "variant_config": VARIANTS[arm].to_dict(),
                "trials": len(cell),
                "integrity_verified": integrity,
                "errors": errors,
                "goodput_mbps_median": statistics.median(goodputs) if goodputs else None,
                "goodput_mbps_p95": percentile(goodputs, 0.95),
                "wall_ms_median": statistics.median(walls) if walls else None,
                "ttfb_ms_median": statistics.median(ttfbs) if ttfbs else None,
                "read_latency_ms_p95_median": statistics.median(p95s) if p95s else None,
                "read_latency_ms_p99_median": statistics.median(p99s) if p99s else None,
                "downstream_response_wait_ms_median": statistics.median(acks) if acks else None,
                "flow_credit_wait_ms_median": statistics.median(credits) if credits else None,
                "client_visible_events_median": statistics.median(events),
                "window_updates_median": statistics.median(vupds),
                "aead_ops_per_kib_median": statistics.median(aead),
                "peak_rss_kb_median": statistics.median(rss) if rss else None,
            }
            summary["paired"][f"{workload}/{arm}"] = {
                "goodput_ratio": _ci(paired_goodput, 1),
                "wall_ratio": _ci(paired_wall, 2),
                "downstream_response_wait_ratio": _ci(paired_ack_wait, 3),
                "flow_credit_wait_ratio": _ci(paired_credit_wait, 4),
                "read_latency_p95_ratio": _ci(paired_p95, 5),
                "read_latency_p99_ratio": _ci(paired_p99, 6),
                "wins": sum(1 for value in paired_goodput if value > 1.0),
                "losses": sum(1 for value in paired_goodput if value < 1.0),
            }
    return summary


def decide(summary: dict[str, Any], config: CampaignConfig) -> dict[str, Any]:
    """Apply the pre-registered acceptance criteria to each non-control arm."""
    decisions: dict[str, Any] = {}
    for arm in config.arms:
        if arm == "control":
            continue
        cells = [
            summary["paired"][f"{workload}/{arm}"]
            for workload in config.workloads
            if f"{workload}/{arm}" in summary["paired"]
        ]
        if not cells:
            continue
        gains = [
            cell["goodput_ratio"]["ci_low"]
            for cell in cells
            if cell["goodput_ratio"]["ci_low"] is not None
        ]
        p95_regressions = [
            cell["read_latency_p95_ratio"]["median"]
            for cell in cells
            if cell["read_latency_p95_ratio"]["median"] is not None
        ]
        p99_regressions = [
            cell["read_latency_p99_ratio"]["median"]
            for cell in cells
            if cell["read_latency_p99_ratio"]["median"] is not None
        ]
        integrity_ok = all(
            summary["cells"][f"{workload}/{arm}"]["integrity_verified"]
            for workload in config.workloads
            if f"{workload}/{arm}" in summary["cells"]
        )
        reproducible_gain = sum(1 for value in gains if value is not None and value > 1.0)
        p95_ok = all(value is None or value <= 1.05 for value in p95_regressions)
        p99_ok = all(value is None or value <= 1.05 for value in p99_regressions)
        decisions[arm] = {
            "workloads_with_ci_lower_bound_above_1": reproducible_gain,
            "workloads_measured": len(gains),
            "p95_within_5_percent": p95_ok,
            "p99_within_5_percent": p99_ok,
            "integrity_ok": integrity_ok,
            "accepted": bool(
                reproducible_gain >= 2 and p95_ok and p99_ok and integrity_ok
            ),
        }
    return decisions


async def run_campaign(config: CampaignConfig, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trials_path = output_dir / "trials.jsonl"
    started_at = time.time()
    raw: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    with trials_path.open("w", encoding="utf-8") as handle:
        for workload_name in config.workloads:
            workload = WORKLOADS[workload_name]
            for warmup in range(config.warmups):
                for arm in _ordered_arms(config.arms, workload_name, warmup, warmup=True):
                    result = await run_trial(
                        VARIANTS[arm], workload,
                        seed=_trial_seed(config.base_seed, workload_name, -1 - warmup),
                    )
                    if not result.ok:
                        failures.append({"phase": "warmup", "arm": arm,
                                         "workload": workload_name,
                                         "errors": result.payload["integrity"]["errors"]})
            for trial in range(config.trials):
                seed = _trial_seed(config.base_seed, workload_name, trial)
                for arm in _ordered_arms(config.arms, workload_name, trial, warmup=False):
                    result = await run_trial(VARIANTS[arm], workload, seed=seed)
                    payload = result.payload
                    payload["trial"] = trial
                    raw.append(payload)
                    handle.write(json.dumps(payload, sort_keys=True) + "\n")
                    handle.flush()
                    if not result.ok:
                        failures.append({"phase": "trial", "arm": arm,
                                         "workload": workload_name, "trial": trial,
                                         "errors": payload["integrity"]["errors"]})

    summary = summarize(raw, config)
    decisions = decide(summary, config)
    finished_at = time.time()
    result = {
        "schema_version": 1,
        "experiment": "THOR P2 relay credit, WINDOW_UPDATE policy, response-event size and ACK pipelining",
        "tier": "loopback",
        "metadata": {
            "aegis_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "started_at_unix": started_at,
            "finished_at_unix": finished_at,
            "duration_s": finished_at - started_at,
            "git": _git_state(),
            "trials_per_cell": config.trials,
            "warmups_per_cell": config.warmups,
            "base_seed": config.base_seed,
            "bootstrap_seed": config.bootstrap_seed,
            "arms": list(config.arms),
            "workloads": list(config.workloads),
            "workload_definitions": {name: WORKLOADS[name].to_dict() for name in config.workloads},
            "variant_definitions": {name: VARIANTS[name].to_dict() for name in config.arms},
            "warning": (
                "Loopback only, one host, relays in the same Python process. "
                "No WAN, Tor, anonymity or 90%-of-Surface claim follows from these numbers."
            ),
        },
        "summary": summary,
        "decisions": decisions,
        "failures": failures,
    }
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
