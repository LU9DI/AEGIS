from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonlab.trace_dataset import load_normalized_jsonl


def _record(trace_id: str, group_id: str, label: int) -> dict:
    return {
        "trace_id": trace_id,
        "group_id": group_id,
        "label": label,
        "packets": [
            {"direction": 1, "size_bytes": 512, "delta_ms": 0},
            {"direction": -1, "size_bytes": 1200, "delta_ms": 12.5},
        ],
    }


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


def test_loads_normalized_jsonl_and_records_sha256(tmp_path: Path) -> None:
    path = _write(tmp_path / "traces.jsonl", [_record("t1", "session-a", 0), _record("t2", "session-b", 1)])
    result = load_normalized_jsonl(path)
    assert result["trace_count"] == 2
    assert result["class_count"] == 2
    assert len(result["sha256"]) == 64
    assert result["traces"][0]["group_id"] == "session-a"
    assert result["traces"][0]["packets"] == [(1, 512, 0.0), (-1, 1200, 12.5)]
    assert "is established" in result["warning"]


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.update(extra="no"), "exactly"),
    (lambda r: r.update(trace_id=""), "trace_id"),
    (lambda r: r.update(label=True), "label"),
    (lambda r: r.update(group_id=""), "group_id"),
    (lambda r: r.update(packets=[]), "packets"),
    (lambda r: r["packets"][0].update(direction=0), "direction"),
    (lambda r: r["packets"][0].update(size_bytes=0), "size_bytes"),
    (lambda r: r["packets"][0].update(delta_ms=float("nan")), "non-finite"),
])
def test_rejects_invalid_trace_records(tmp_path: Path, mutate, message: str) -> None:
    record = _record("t1", "session-a", 0)
    mutate(record)
    path = _write(tmp_path / "bad.jsonl", [record, _record("t2", "session-b", 1)])
    with pytest.raises(ValueError, match=message):
        load_normalized_jsonl(path)


def test_rejects_duplicate_trace_ids_and_duplicate_json_keys(tmp_path: Path) -> None:
    path = _write(tmp_path / "duplicate-id.jsonl", [_record("same", "a", 0), _record("same", "b", 1)])
    with pytest.raises(ValueError, match="duplicate trace_id"):
        load_normalized_jsonl(path)

    duplicate_key = '{"trace_id":"x","trace_id":"y","group_id":"g","label":0,"packets":[{"direction":1,"size_bytes":1,"delta_ms":0}]}\n'
    path.write_text(duplicate_key + json.dumps(_record("t2", "b", 1)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_normalized_jsonl(path)


def test_rejects_single_class_empty_and_invalid_utf8(tmp_path: Path) -> None:
    path = _write(tmp_path / "one-class.jsonl", [_record("t1", "a", 0), _record("t2", "b", 0)])
    with pytest.raises(ValueError, match="two label classes"):
        load_normalized_jsonl(path)
    path.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no records"):
        load_normalized_jsonl(path)
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="UTF-8"):
        load_normalized_jsonl(path)


def test_rejects_non_finite_and_wrong_packet_types(tmp_path: Path) -> None:
    path = tmp_path / "bad-packet.jsonl"
    record = _record("t1", "a", 0)
    record["packets"][0]["direction"] = 1.0
    path.write_text(json.dumps(record) + "\n" + json.dumps(_record("t2", "b", 1)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="direction"):
        load_normalized_jsonl(path)



def test_grouped_split_is_deterministic_group_disjoint_and_class_complete() -> None:
    from anonlab.trace_dataset import grouped_train_test_split

    traces = []
    for group_id in range(12):
        for label in (0, 1, 2):
            traces.append({
                "trace_id": f"g{group_id}-c{label}",
                "group_id": f"session-{group_id}",
                "label": label,
                "packets": [],
            })

    first = grouped_train_test_split(traces, seed=17)
    second = grouped_train_test_split(traces, seed=17)
    assert first == second
    assert first["group_disjoint"] is True
    assert first["all_classes_in_both_sets"] is True
    assert set(first["train_group_ids"]).isdisjoint(first["test_group_ids"])
    assert set(first["train_indices"]).isdisjoint(first["test_indices"])
    assert len(first["train_indices"]) + len(first["test_indices"]) == len(traces)
    assert {traces[i]["label"] for i in first["train_indices"]} == {0, 1, 2}
    assert {traces[i]["label"] for i in first["test_indices"]} == {0, 1, 2}


def test_grouped_split_fails_when_labels_are_confounded_with_groups() -> None:
    from anonlab.trace_dataset import grouped_train_test_split

    traces = [
        {"trace_id": "a1", "group_id": "only-class-0", "label": 0},
        {"trace_id": "a2", "group_id": "only-class-0", "label": 0},
        {"trace_id": "b1", "group_id": "only-class-1", "label": 1},
        {"trace_id": "b2", "group_id": "only-class-1", "label": 1},
    ]
    with pytest.raises(ValueError, match="could not create a group-disjoint split"):
        grouped_train_test_split(traces, seed=3, attempts=100)


def test_grouped_split_rejects_invalid_parameters_and_trace_metadata() -> None:
    from anonlab.trace_dataset import grouped_train_test_split

    traces = [
        {"trace_id": "a", "group_id": "a", "label": 0},
        {"trace_id": "b", "group_id": "b", "label": 1},
        {"trace_id": "c", "group_id": "c", "label": 0},
        {"trace_id": "d", "group_id": "d", "label": 1},
    ]
    with pytest.raises(ValueError, match="train_fraction"):
        grouped_train_test_split(traces, train_fraction=0.9)
    with pytest.raises(ValueError, match="attempts"):
        grouped_train_test_split(traces, attempts=0)
    traces[0]["group_id"] = ""
    with pytest.raises(ValueError, match="group_id"):
        grouped_train_test_split(traces)
