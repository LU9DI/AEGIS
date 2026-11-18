"""Derive summaries and gates from a raw THOR run directory.

Nothing here reads the network or re-runs a trial: the input is
``trials.jsonl`` plus ``manifest.json``, so a summary can always be regenerated
and audited. Two rules matter for honesty:

* only non-warmup, ``status == "ok"`` records with matching workload parameters
  enter a ratio, and the number of paired trials is always reported;
* a ratio is computed only between arms in the *same tier and same workload*.
  With fewer than five paired trials the confidence interval is flagged
  ``reliable: false`` and a gate is ``insufficient_data`` below three.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .provenance import canonical_digest
from .stats import bootstrap_ci, ratio_ci, summarize

__all__ = ["RunData", "load_run", "summarize_run", "evaluate_gates", "verify_run_digest", "GATE_TARGET"]

#: The non-negotiable performance target: AEGIS goodput >= 90% of Surface.
GATE_TARGET = 0.90
_MIN_TRIALS_FOR_GATE = 3
_MIN_TRIALS_FOR_CI = 5


@dataclass(slots=True)
class RunData:
    directory: Path
    manifest: dict[str, Any]
    run: dict[str, Any]
    availability: list[dict[str, Any]]
    records: list[dict[str, Any]]

    @property
    def trials_path(self) -> Path:
        return self.directory / "trials.jsonl"

    def raw_digest(self) -> str:
        return hashlib.sha256(self.trials_path.read_bytes()).hexdigest()

    @property
    def tier(self) -> str:
        return str(self.manifest.get("tier"))

    @property
    def measured_arms(self) -> list[str]:
        return sorted({str(record["arm"]) for record in self.records})


def load_run(directory: Path | str) -> RunData:
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"run directory {root} does not exist")
    manifest_path = root / "manifest.json"
    trials_path = root / "trials.jsonl"
    if not manifest_path.is_file() or not trials_path.is_file():
        raise FileNotFoundError(f"{root} is not a THOR run (manifest.json + trials.jsonl required)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = json.loads((root / "run.json").read_text(encoding="utf-8")) if (root / "run.json").is_file() else {}
    availability_path = root / "availability.json"
    availability = (
        json.loads(availability_path.read_text(encoding="utf-8"))
        if availability_path.is_file()
        else []
    )
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(trials_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or "arm" not in record or "status" not in record:
            raise ValueError(f"trials.jsonl line {line_number} is not a THOR trial record")
        records.append(record)
    return RunData(directory=root, manifest=manifest, run=run, availability=availability, records=records)


def _workload_key(record: dict[str, Any]) -> str:
    return str(record.get("workload_label") or record.get("workload", {}).get("kind"))


def _qualifying(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if not record.get("warmup") and record.get("status") == "ok" and record.get("outcome")
    ]


def _by_trial(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(record["trial"]): record for record in records}


def _metric_series(records: list[dict[str, Any]], *path: str) -> list[float]:
    values: list[float] = []
    for record in records:
        cursor: Any = record
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if isinstance(cursor, (int, float)) and not isinstance(cursor, bool):
            values.append(float(cursor))
    return values


def _trial_percentile(records: list[dict[str, Any]], key: str, fraction: float) -> list[float]:
    results: list[float] = []
    for record in records:
        samples = (record.get("outcome") or {}).get(key) or []
        values = [float(value) for value in samples if isinstance(value, (int, float))]
        if not values:
            continue
        from .stats import percentile  # local import keeps the module surface small

        results.append(percentile(values, fraction))
    return results


def _summarize_metric(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    summary = summarize(values)
    summary["ci"] = bootstrap_ci(values, resamples=2000, seed=20261118)
    summary["reliable_ci"] = len(values) >= _MIN_TRIALS_FOR_CI
    return summary


def summarize_run(data: RunData, *, include_gates: bool = True) -> dict[str, Any]:
    """Build the derived summary dictionary (also written as summary.json)."""
    measured = _qualifying(data.records)
    arms: dict[str, Any] = {}
    for arm in sorted({str(record["arm"]) for record in data.records}):
        arm_records = [record for record in data.records if record["arm"] == arm]
        arms[arm] = {
            "family": next((record.get("family") for record in arm_records), None),
            "records": len(arm_records),
            "warmup_records": sum(1 for record in arm_records if record.get("warmup")),
            "ok_records": sum(1 for record in arm_records if record.get("status") == "ok"),
            "error_records": sum(1 for record in arm_records if record.get("status") == "error"),
            "integrity_failures": sum(
                1
                for record in arm_records
                if record.get("status") == "ok"
                and (record.get("outcome") or {}).get("integrity") is False
            ),
        }

    workloads: dict[str, Any] = {}
    labels = sorted({_workload_key(record) for record in measured})
    for label in labels:
        per_arm: dict[str, Any] = {}
        for arm in sorted({str(record["arm"]) for record in measured if _workload_key(record) == label}):
            subset = [
                record
                for record in measured
                if record["arm"] == arm and _workload_key(record) == label
            ]
            entry: dict[str, Any] = {
                "trials": len(subset),
                "payload_bytes": sorted({int((record.get("outcome") or {}).get("payload_bytes") or 0) for record in subset}),
                "goodput_mbps": _summarize_metric(_metric_series(subset, "outcome", "goodput_mbps")),
                "ttfb_ms": _summarize_metric(_metric_series(subset, "outcome", "ttfb_ms")),
                "total_ms": _summarize_metric(_metric_series(subset, "outcome", "total_ms")),
                "setup_ms": _summarize_metric(_metric_series(subset, "setup_ms")),
                "wall_ms": _summarize_metric(_metric_series(subset, "wall_ms")),
                "wire_up_ratio": _summarize_metric(_metric_series(subset, "overhead", "wire_up_ratio")),
                "wire_down_ratio": _summarize_metric(_metric_series(subset, "overhead", "wire_down_ratio")),
                "cpu_fraction_of_one_core": _summarize_metric(
                    _metric_series(subset, "resources", "cpu_fraction_of_one_core")
                ),
                "peak_rss_kb": _summarize_metric(_metric_series(subset, "resources", "peak_rss_kb")),
                "latency_p50_ms": _summarize_metric(_trial_percentile(subset, "latency_ms", 0.50)),
                "latency_p95_ms": _summarize_metric(_trial_percentile(subset, "latency_ms", 0.95)),
                "latency_p99_ms": _summarize_metric(_trial_percentile(subset, "latency_ms", 0.99)),
                "ttfb_first_body_ms": _summarize_metric(
                    _trial_percentile(subset, "ttfb_samples_ms", 0.50)
                ),
            }
            key_hops = sorted({len(record.get("setup_calls") or []) for record in subset})
            entry["connections_per_trial"] = key_hops
            per_arm[arm] = entry
        workloads[label] = per_arm

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": data.run.get("run_id") or data.manifest.get("extra", {}).get("run_id"),
        "tier": data.tier,
        "seed": data.manifest.get("seed"),
        "code": data.manifest.get("code"),
        "environment": data.manifest.get("environment"),
        "configuration": data.manifest.get("configuration"),
        "configuration_digest": data.manifest.get("configuration_digest"),
        "configuration_digest_recomputed": canonical_digest(data.manifest.get("configuration") or {}),
        "raw": {
            "trials_sha256": data.raw_digest(),
            "records": len(data.records),
            "warmup_records": sum(1 for record in data.records if record.get("warmup")),
            "error_records": sum(1 for record in data.records if record.get("status") == "error"),
            "qualifying_records": len(measured),
        },
        "availability": data.availability,
        "arms": arms,
        "workloads": workloads,
        "claim_scope": (
            "Derived from one THOR run. Loopback/lab ratios are not public-network "
            "performance and do not establish anonymity or Tor equivalence."
        ),
    }
    if include_gates:
        summary["gates"] = evaluate_gates(data, summary)
    return summary


def _paired_metric(
    data: RunData,
    reference: str,
    candidate: str,
    label: str,
    *path: str,
) -> tuple[list[float], list[float], list[int]]:
    reference_by_trial = _by_trial(
        [
            record
            for record in _qualifying(data.records)
            if record["arm"] == reference and _workload_key(record) == label
        ]
    )
    candidate_by_trial = _by_trial(
        [
            record
            for record in _qualifying(data.records)
            if record["arm"] == candidate and _workload_key(record) == label
        ]
    )
    common = sorted(set(reference_by_trial) & set(candidate_by_trial))
    left: list[float] = []
    right: list[float] = []
    for trial in common:
        reference_value = _metric_series([reference_by_trial[trial]], *path)
        candidate_value = _metric_series([candidate_by_trial[trial]], *path)
        if reference_value and candidate_value:
            left.append(reference_value[0])
            right.append(candidate_value[0])
    return left, right, common


def evaluate_gates(data: RunData, summary: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Evaluate the >=90% goodput target per workload, inside one tier only."""
    labels = sorted(
        {
            _workload_key(record)
            for record in _qualifying(data.records)
            if record["arm"] == "surface"
        }
    )
    gates: list[dict[str, Any]] = []
    measured_arms = {str(record["arm"]) for record in data.records}
    if "surface" not in measured_arms:
        return [
            {
                "workload": None,
                "status": "insufficient_data",
                "reason": "no_surface_reference_arm",
                "tier": data.tier,
            }
        ]
    for label in labels:
        for candidate in sorted(measured_arms - {"surface"}):
            goodput_reference, goodput_candidate, paired_trials = _paired_metric(
                data, "surface", candidate, label, "outcome", "goodput_mbps"
            )
            if len(paired_trials) < _MIN_TRIALS_FOR_GATE:
                gates.append(
                    {
                        "workload": label,
                        "candidate": candidate,
                        "reference": "surface",
                        "tier": data.tier,
                        "metric": "goodput_mbps",
                        "status": "insufficient_data",
                        "paired_trials": len(paired_trials),
                        "required_paired_trials": _MIN_TRIALS_FOR_GATE,
                        "reason": "too_few_paired_ok_trials",
                    }
                )
                continue
            goodput_ratio = ratio_ci(goodput_candidate, goodput_reference, seed=20261118)
            latency_reference, latency_candidate, _ = _paired_metric(
                data, "surface", candidate, label, "wall_ms"
            )
            latency_ratio = (
                ratio_ci(latency_candidate, latency_reference, seed=20261119)
                if len(latency_candidate) >= _MIN_TRIALS_FOR_GATE and all(latency_reference)
                else None
            )
            point = float(goodput_ratio["point"])
            gates.append(
                {
                    "workload": label,
                    "candidate": candidate,
                    "reference": "surface",
                    "tier": data.tier,
                    "metric": "goodput_mbps",
                    "criterion": f"candidate/surface median goodput >= {GATE_TARGET:.2f}",
                    "status": "met" if point >= GATE_TARGET else "not_met",
                    "paired_trials": len(paired_trials),
                    "goodput_ratio": goodput_ratio,
                    "headroom_needed_factor": round(GATE_TARGET / point, 4) if point > 0 else None,
                    "latency_ratio": latency_ratio,
                    "ci_reliable": len(paired_trials) >= _MIN_TRIALS_FOR_CI,
                }
            )
    if not gates:
        gates.append(
            {
                "workload": None,
                "candidate": None,
                "reference": "surface",
                "tier": data.tier,
                "metric": "goodput_mbps",
                "status": "insufficient_data",
                "paired_trials": 0,
                "required_paired_trials": _MIN_TRIALS_FOR_GATE,
                "reason": "no_candidate_arm_measured_against_surface",
            }
        )
    return gates


def verify_run_digest(data: RunData, summary: dict[str, Any]) -> dict[str, Any]:
    """Compare the summary's recorded raw digest and configuration digest to disk."""
    expected_raw = summary.get("raw", {}).get("trials_sha256")
    actual_raw = data.raw_digest()
    recomputed_configuration = canonical_digest(data.manifest.get("configuration") or {})
    recorded_configuration = data.manifest.get("configuration_digest")
    checks = {
        "raw_digest_sha256": {"matches": expected_raw == actual_raw, "actual": actual_raw},
        "configuration_digest_sha256": {
            "matches": recorded_configuration == recomputed_configuration,
            "recorded": recorded_configuration,
            "recomputed": recomputed_configuration,
        },
        "revision_recorded": {"value": (data.manifest.get("code") or {}).get("revision")},
        "dirty_tree": {"value": (data.manifest.get("code") or {}).get("dirty")},
    }
    record_checks = all(int(record.get("schema_version", -1)) >= 1 for record in data.records)
    checks["record_schema"] = {"matches": record_checks, "records": len(data.records)}
    checks["ok"] = all(
        bool(value.get("matches", False)) for key, value in checks.items() if key in {"raw_digest_sha256", "configuration_digest_sha256", "record_schema"}
    )
    return checks
