from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

from anonlab.privacy_eval import (
    CandidatePath,
    evaluate_nearest_centroid,
    make_synthetic_traces,
    pad_trace,
    repeated_as_observers,
    run_evaluation,
    run_external_trace_evaluation,
    run_seed_stability,
    select_path,
    stratified_split_indices,
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
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "anonlab.privacy_eval", "--seed", "123"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    data = json.loads(completed.stdout)
    assert data["is_live_network_test"] is False
    assert data["is_security_proof"] is False
    assert data["path_selection"]["selection_count"] == 500
    assert data["fingerprinting"]["padding"]["observed_bytes"] > 0
    sweep = data["fingerprinting"]["defense_sweep"]
    assert len(sweep) == 20
    assert {row["bucket_bytes"] for row in sweep} == {128, 256, 512, 1024}
    assert {row["cover_rate"] for row in sweep} == {0.0, 0.25, 0.5, 0.75, 1.0}
    assert all(0 <= row["fingerprinting_accuracy"] <= 1 for row in sweep)
    assert all(row["byte_overhead_ratio"] >= 0 for row in sweep)


def test_run_evaluation_output_is_reproducible() -> None:
    assert run_evaluation(77) == run_evaluation(77)


def test_acceptance_threshold_fails_with_machine_readable_evidence() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "anonlab.privacy_eval", "--seed", "123",
         "--max-padding-overhead", "0"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 2
    data = json.loads(completed.stdout)
    assert data["acceptance_checks"]["passed"] is False
    assert data["acceptance_checks"]["checks"][0]["metric"] == "padding_byte_overhead_ratio"
    assert data["acceptance_checks"]["checks"][0]["passed"] is False


def test_repeated_as_observers_rejects_partial_route_observers() -> None:
    # Entry and exit ASes differ, but AS64520 hosts the entry and a middle hop,
    # so that AS observes two positions of the path.
    repeated = CandidatePath("repeated", 3, ("AS64520", "AS64521", "AS64520", "AS64522"), 4)
    distinct = CandidatePath("distinct", 5, ("AS64530", "AS64531", "AS64532", "AS64533"), 4)
    assert repeated_as_observers(repeated.relay_asns) == ("AS64520",)
    assert repeated_as_observers(distinct.relay_asns) == ()
    chosen = select_path([repeated, distinct], max_detour_ms=10, rng=random.Random(5))
    assert chosen.path_id == "distinct"
    # Document the gap the stricter policy closes: entry-vs-exit-only accepts it.
    legacy = select_path(
        [repeated], max_detour_ms=10, rng=random.Random(5),
        require_distinct_as_observers=False,
    )
    assert legacy.path_id == "repeated"


def test_path_selector_fails_closed_when_only_partial_route_observers_exist() -> None:
    paths = [CandidatePath("repeated-only", 2, ("AS1", "AS2", "AS1", "AS3"), 4)]
    try:
        select_path(paths, max_detour_ms=10, rng=random.Random(1))
    except ValueError as exc:
        assert "no path satisfies" in str(exc)
    else:
        raise AssertionError("expected repeated-AS path to be rejected")


def test_split_indices_are_disjoint_covering_and_deterministic() -> None:
    traces = make_synthetic_traces(classes=3, samples_per_class=10, seed=3)
    labels = [int(trace["label"]) for trace in traces]
    train, test = stratified_split_indices(labels, seed=3)
    assert set(train) & set(test) == set()
    assert sorted(train + test) == list(range(len(traces)))
    assert (train, test) == stratified_split_indices(labels, seed=3)


def test_evaluation_reuses_the_same_holdout_for_plain_and_padded() -> None:
    traces = make_synthetic_traces(classes=4, samples_per_class=10, seed=8)
    split = stratified_split_indices([int(t["label"]) for t in traces], seed=8)
    plain = evaluate_nearest_centroid(traces, seed=8, split=split)
    padded = [
        pad_trace(trace, bucket_bytes=256, cover_rate=0.5, seed=8 + index)
        for index, trace in enumerate(traces)
    ]
    defended = evaluate_nearest_centroid(padded, seed=8, split=split)
    assert plain["split"] == defended["split"]
    assert plain["test_samples"] == defended["test_samples"]


def test_split_rejects_leakage_and_out_of_range_indices() -> None:
    traces = make_synthetic_traces(classes=3, samples_per_class=8, seed=4)
    try:
        evaluate_nearest_centroid(traces, split=((0, 1), (1, 2)))
    except ValueError as exc:
        assert "leak" in str(exc)
    else:
        raise AssertionError("expected an overlapping split to be rejected")
    try:
        evaluate_nearest_centroid(traces, split=((0,), (1, len(traces))))
    except ValueError as exc:
        assert "within the trace range" in str(exc)
    else:
        raise AssertionError("expected an out-of-range split to be rejected")


def test_confusion_matrix_and_per_class_metrics_are_consistent() -> None:
    traces = make_synthetic_traces(classes=3, samples_per_class=12, seed=6)
    result = evaluate_nearest_centroid(traces, seed=6)
    confusion = result["confusion_matrix"]
    total = 0
    diagonal = 0
    for actual, row in confusion.items():
        assert sum(row.values()) == result["per_class"][actual]["support"]
        total += sum(row.values())
        diagonal += row[actual]
    assert total == result["test_samples"]
    assert abs(diagonal / total - result["accuracy"]) < 1e-12
    for label, metrics in result["per_class"].items():
        assert 0 <= metrics["precision"] <= 1
        assert 0 <= metrics["recall"] <= 1
        assert 0 <= metrics["f1"] <= 1
        # Legacy per-class accuracy field stays consistent with recall.
        assert metrics["recall"] == result["per_class_accuracy"][label]


def test_seed_stability_reports_spread_for_every_sweep_point() -> None:
    stability = run_seed_stability([7, 8, 9])
    assert stability["seeds"] == [7, 8, 9]
    assert len(stability["runs"]) == 3
    rows = stability["defense_sweep_spread"]
    assert len(rows) == 20
    for row in rows:
        assert set(row) == {
            "bucket_bytes", "cover_rate", "accuracy_spread", "byte_overhead_ratio_spread",
        }
        spread = row["accuracy_spread"]
        assert spread["min"] <= spread["mean"] <= spread["max"]
        assert spread["pstdev"] >= 0
    for spread in (stability["plain_accuracy_spread"], stability["padded_accuracy_spread"]):
        assert 0 <= spread["min"] <= 1
        assert 0 <= spread["max"] <= 1


def test_seed_stability_requires_at_least_two_integer_seeds() -> None:
    try:
        run_seed_stability([1])
    except ValueError as exc:
        assert "two seeds" in str(exc)
    else:
        raise AssertionError("expected a single seed to be rejected")
    try:
        run_seed_stability([1, "two"])  # type: ignore[list-item]
    except ValueError as exc:
        assert "integers" in str(exc)
    else:
        raise AssertionError("expected a non-integer seed to be rejected")


def test_run_evaluation_records_as_policy_evidence_and_scope_limits() -> None:
    data = run_evaluation(55)
    assert data["schema_version"] == 2
    selection = data["path_selection"]
    assert selection["selected_paths_with_as_conflict"] == 0
    assert selection["as_conflict_rejections"] == {
        "bad-repeated-middle-as": ["AS64520"],
        "bad-shared-as": ["AS64510"],
    }
    assert selection["selected_path_counts"]["bad-repeated-middle-as"] == 0
    assert selection["as_policy"]["all_positions_distinct"] is True
    assert set(data["not_measured"]) == {"latency", "throughput", "real_traffic"}


def test_cli_stability_flag_repeats_evaluation_across_seeds() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "anonlab.privacy_eval", "--seed", "5",
         "--stability-seeds", "5,6"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    stability = json.loads(completed.stdout)["seed_stability"]
    assert stability["seeds"] == [5, 6]
    assert len(stability["defense_sweep_spread"]) == 20
    invalid = subprocess.run(
        [sys.executable, "-m", "anonlab.privacy_eval", "--stability-seeds", "5"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert invalid.returncode == 2



def _write_external_dataset(path: Path, *, groups: int = 8) -> Path:
    records = []
    for group in range(groups):
        for label in (0, 1):
            records.append({
                "trace_id": f"trace-{group}-{label}",
                "group_id": f"session-{group}",
                "label": label,
                "packets": [
                    {"direction": 1, "size_bytes": 400 + label * 200, "delta_ms": 0},
                    {"direction": -1, "size_bytes": 900 + label * 100, "delta_ms": 10 + label},
                ],
            })
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_external_trace_evaluation_uses_group_disjoint_holdout(tmp_path: Path) -> None:
    dataset_path = _write_external_dataset(tmp_path / "external.jsonl")
    result = run_external_trace_evaluation(dataset_path, seed=42)
    assert result["experiment"] == "external_trace_fingerprinting_baseline"
    assert "provenance and authenticity are not independently verified" in result["dataset_origin"]
    assert result["is_live_network_test"] is False
    assert result["is_security_proof"] is False
    assert result["dataset"]["trace_count"] == 16
    assert len(result["dataset"]["sha256"]) == 64
    split = result["split"]
    assert split["group_disjoint"] is True
    assert split["all_classes_in_both_sets"] is True
    assert split["train_group_count"] > 0
    assert split["test_group_count"] > 0
    assert len(split["train_groups_sha256"]) == 64
    assert len(split["test_groups_sha256"]) == 64
    assert "train_group_ids" not in split
    assert "test_group_ids" not in split
    assert split["train_trace_count"] + split["test_trace_count"] == 16
    assert result["attacker"]["test_samples"] == split["test_trace_count"]
    defense = result["toy_defense"]
    assert defense["same_group_disjoint_holdout"] is True
    assert defense["attacker"]["split"] == result["attacker"]["split"]
    assert defense["original_bytes"] > 0
    assert defense["observed_bytes"] >= defense["original_bytes"]
    assert defense["byte_overhead_ratio"] >= 0
    assert defense["accuracy_delta_vs_undefended"] == (
        defense["attacker"]["accuracy"] - result["attacker"]["accuracy"]
    )
    assert "not Deep Fingerprinting" in result["warning"]


def test_external_trace_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    dataset_path = _write_external_dataset(tmp_path / "external.jsonl")
    output_path = tmp_path / "external-eval.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [
            sys.executable, "-m", "anonlab.privacy_eval",
            "--trace-dataset", str(dataset_path),
            "--seed", "42",
            "--output", str(output_path),
        ],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    stdout_result = json.loads(completed.stdout)
    file_result = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_result == file_result
    assert stdout_result["experiment"] == "external_trace_fingerprinting_baseline"
    assert completed.stdout.endswith("\n")


def test_external_trace_cli_rejects_synthetic_only_flags(tmp_path: Path) -> None:
    dataset_path = _write_external_dataset(tmp_path / "external.jsonl")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [
            sys.executable, "-m", "anonlab.privacy_eval",
            "--trace-dataset", str(dataset_path),
            "--max-padding-overhead", "0.5",
        ],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 2
    assert "cannot be combined" in completed.stderr
