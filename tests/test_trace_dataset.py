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
    assert "not established" in result["warning"]


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
