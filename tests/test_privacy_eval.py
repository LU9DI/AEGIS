from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from anonlab.privacy_eval import (
    CandidatePath,
    evaluate_nearest_centroid,
    make_synthetic_traces,
    pad_trace,
    run_evaluation,
    select_path,
)

ROOT = Path(__file__).resolve().parents[1]


def test_path_selector_rejects_as_overlap_and_excess_detour() -> None:
    paths = [
        CandidatePath("shared", 1, ("AS1", "AS2", "AS1"), 3),
        CandidatePath("slow", 50, ("AS3", "AS4", "AS5"), 3),
        CandidatePath("good", 7, ("AS6", "AS7", "AS8"), 3),
    ]
    chosen = select_path(paths, max_detour_ms=10, rng=__import__("random").Random(2))
    assert chosen.path_id == "good"


def test_path_selector_fails_closed_when_no_candidate_qualifies() -> None:
    paths = [CandidatePath("bad", 2, ("AS1", "AS2", "AS1"), 3)]
    try:
        select_path(paths, max_detour_ms=10, rng=__import__("random").Random(1))
    except ValueError as exc:
        assert "no path satisfies" in str(exc)
    else:
        raise AssertionError("expected no eligible route to be rejected")


def test_padding_records_overhead_and_keeps_labels() -> None:
    trace = {"label": 2, "packets": [(1, 301, 10.0), (-1, 100, 20.0)]}
    padded = pad_trace(trace, bucket_bytes=256, cover_rate=1.0, seed=4)
    assert padded["label"] == 2
    assert padded["original_bytes"] == 401
    assert padded["observed_bytes"] >= padded["original_bytes"]
    assert len(padded["packets"]) == 4
    assert all(size % 256 == 0 for _, size, _ in padded["packets"])


def test_classifier_is_deterministic_and_reports_chance_baseline() -> None:
    traces = make_synthetic_traces(classes=3, samples_per_class=12, seed=9)
    first = evaluate_nearest_centroid(traces, seed=9)
    second = evaluate_nearest_centroid(traces, seed=9)
    assert first == second
    assert first["classifier"] == "nearest-centroid synthetic baseline"
    assert first["test_samples"] > 0
    assert first["chance_accuracy"] == 1 / 3
    assert 0 <= first["accuracy"] <= 1


def test_cli_emits_explicit_non_production_flags() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "anonlab.privacy_eval", "--seed", "123"],
        cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    data = json.loads(completed.stdout)
    assert data["is_live_network_test"] is False
    assert data["is_security_proof"] is False
    assert data["path_selection"]["selection_count"] == 500
    assert data["fingerprinting"]["padding"]["observed_bytes"] > 0


def test_run_evaluation_output_is_reproducible() -> None:
    assert run_evaluation(77) == run_evaluation(77)
