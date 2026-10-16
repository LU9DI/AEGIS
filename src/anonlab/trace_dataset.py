"""Strict loader for normalized, externally collected traffic traces.

This module validates dataset integrity only. It does not capture traffic, anonymize
identifiers, provide consent, or make the synthetic privacy evaluator a real-trace
benchmark. Callers must handle trace provenance, licensing, and privacy safely.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

MAX_DATASET_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024
MAX_TRACES = 100_000
MAX_PACKETS_PER_TRACE = 100_000
_ALLOWED_TRACE_KEYS = {"trace_id", "group_id", "label", "packets"}
_ALLOWED_PACKET_KEYS = {"direction", "size_bytes", "delta_ms"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def load_normalized_jsonl(path: str | Path) -> dict[str, Any]:
    """Load validated JSONL traces and return normalized tuples plus provenance.

    Each non-empty line must be an object with exactly:
      trace_id (unique non-empty string), group_id (non-empty string),
      label (non-negative integer), packets (non-empty list).
    Each packet has exactly direction (+1/-1), size_bytes (1..65535),
    and delta_ms (finite non-negative number).

    group_id is retained so a future evaluator can split by capture/session group
    rather than randomly splitting correlated traces. This function deliberately
    does not perform that split or claim that the dataset is representative.
    """
    dataset_path = Path(path)
    try:
        raw = dataset_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read trace dataset: {exc}") from exc
    if not raw:
        raise ValueError("trace dataset is empty")
    if len(raw) > MAX_DATASET_BYTES:
        raise ValueError(f"trace dataset exceeds {MAX_DATASET_BYTES} bytes")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("trace dataset must be UTF-8") from exc

    traces: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    labels: set[int] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError(f"line {line_number} exceeds {MAX_LINE_BYTES} bytes")
        try:
            record = json.loads(
                line, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
        if not isinstance(record, dict) or set(record) != _ALLOWED_TRACE_KEYS:
            raise ValueError(
                f"line {line_number} must contain exactly {sorted(_ALLOWED_TRACE_KEYS)}"
            )

        trace_id = record["trace_id"]
        group_id = record["group_id"]
        label = record["label"]
        packets = record["packets"]
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError(f"line {line_number}: trace_id must be a non-empty string")
        if trace_id in seen_ids:
            raise ValueError(f"line {line_number}: duplicate trace_id {trace_id!r}")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError(f"line {line_number}: group_id must be a non-empty string")
        if isinstance(label, bool) or not isinstance(label, int) or label < 0:
            raise ValueError(f"line {line_number}: label must be a non-negative integer")
        if not isinstance(packets, list) or not packets:
            raise ValueError(f"line {line_number}: packets must be a non-empty list")
        if len(packets) > MAX_PACKETS_PER_TRACE:
            raise ValueError(f"line {line_number}: too many packets")

        normalized_packets: list[tuple[int, int, float]] = []
        for packet_number, packet in enumerate(packets, start=1):
            if not isinstance(packet, dict) or set(packet) != _ALLOWED_PACKET_KEYS:
                raise ValueError(
                    f"line {line_number}, packet {packet_number}: expected exactly "
                    f"{sorted(_ALLOWED_PACKET_KEYS)}"
                )
            direction = packet["direction"]
            size = packet["size_bytes"]
            delta_ms = packet["delta_ms"]
            if isinstance(direction, bool) or not isinstance(direction, int) or direction not in (-1, 1):
                raise ValueError(
                    f"line {line_number}, packet {packet_number}: direction must be -1 or 1"
                )
            if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 65535:
                raise ValueError(
                    f"line {line_number}, packet {packet_number}: size_bytes must be in [1, 65535]"
                )
            if isinstance(delta_ms, bool) or not isinstance(delta_ms, (int, float)) or delta_ms < 0:
                raise ValueError(
                    f"line {line_number}, packet {packet_number}: delta_ms must be finite and >= 0"
                )
            try:
                delay_value = float(delta_ms)
            except (OverflowError, ValueError) as exc:
                raise ValueError(
                    f"line {line_number}, packet {packet_number}: delta_ms must be finite and >= 0"
                ) from exc
            if not math.isfinite(delay_value):
                raise ValueError(
                    f"line {line_number}, packet {packet_number}: delta_ms must be finite and >= 0"
                )
            normalized_packets.append((direction, size, delay_value))

        seen_ids.add(trace_id)
        labels.add(label)
        traces.append({
            "trace_id": trace_id,
            "group_id": group_id,
            "label": label,
            "packets": normalized_packets,
        })
        if len(traces) > MAX_TRACES:
            raise ValueError(f"trace dataset exceeds {MAX_TRACES} records")

    if not traces:
        raise ValueError("trace dataset contains no records")
    if len(labels) < 2:
        raise ValueError("trace dataset must contain at least two label classes")

    return {
        "schema_version": 1,
        "source_name": dataset_path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw),
        "trace_count": len(traces),
        "class_count": len(labels),
        "traces": traces,
        "warning": (
            "validated normalized input only; no capture provenance, representativeness, "
            "privacy, or defense effectiveness is established"
        ),
    }



def grouped_train_test_split(
    traces: list[dict[str, Any]],
    *,
    seed: int = 20261016,
    train_fraction: float = 0.65,
    attempts: int = 2048,
) -> dict[str, Any]:
    """Split normalized traces by group, never placing one group in both sets.

    The randomized search prefers a split close to train_fraction while
    requiring every label to occur in both train and test. It fails closed when
    it cannot find such a split; it never silently falls back to trace-level
    splitting, which can leak capture/session-specific fingerprints.
    """
    import random

    if not 0.4 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.4 and 0.8")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 100_000:
        raise ValueError("attempts must be an integer in [1, 100000]")
    if not isinstance(traces, list) or len(traces) < 4:
        raise ValueError("at least 4 traces are required for a grouped split")

    group_indices: dict[str, list[int]] = {}
    group_labels: dict[str, set[int]] = {}
    all_labels: set[int] = set()
    for index, trace in enumerate(traces):
        if not isinstance(trace, dict):
            raise ValueError(f"trace {index} must be an object")
        group_id = trace.get("group_id")
        label = trace.get("label")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError(f"trace {index} has invalid group_id")
        if isinstance(label, bool) or not isinstance(label, int) or label < 0:
            raise ValueError(f"trace {index} has invalid label")
        group_indices.setdefault(group_id, []).append(index)
        group_labels.setdefault(group_id, set()).add(label)
        all_labels.add(label)

    if len(all_labels) < 2:
        raise ValueError("grouped split requires at least two label classes")
    if len(group_indices) < 2:
        raise ValueError("grouped split requires at least two distinct groups")

    groups = list(group_indices)
    rng = random.Random(seed)
    best: tuple[float, tuple[str, ...], tuple[str, ...]] | None = None
    target_train_count = len(traces) * train_fraction

    for _ in range(attempts):
        shuffled = groups[:]
        rng.shuffle(shuffled)
        test_groups = {group for group in shuffled if rng.random() >= train_fraction}
        if not test_groups or len(test_groups) == len(groups):
            continue
        train_groups = set(groups) - test_groups
        train_labels = set().union(*(group_labels[g] for g in train_groups))
        test_labels = set().union(*(group_labels[g] for g in test_groups))
        if train_labels != all_labels or test_labels != all_labels:
            continue

        train_indices = tuple(
            index for group in groups if group in train_groups
            for index in group_indices[group]
        )
        score = abs(len(train_indices) - target_train_count)
        candidate = (score, tuple(sorted(train_groups)), tuple(sorted(test_groups)))
        if best is None or candidate < best:
            best = candidate

    if best is None:
        raise ValueError(
            "could not create a group-disjoint split containing every label in "
            "both sets; collect more independent groups or revise the dataset"
        )

    _, train_group_ids, test_group_ids = best
    train_group_set = set(train_group_ids)
    test_group_set = set(test_group_ids)
    train_indices = tuple(
        index for group in groups if group in train_group_set
        for index in group_indices[group]
    )
    test_indices = tuple(
        index for group in groups if group in test_group_set
        for index in group_indices[group]
    )
    if set(train_indices) & set(test_indices) or len(train_indices) + len(test_indices) != len(traces):
        raise RuntimeError("internal error: grouped split indices are not a partition")

    return {
        "seed": seed,
        "train_fraction_target": train_fraction,
        "train_indices": train_indices,
        "test_indices": test_indices,
        "train_group_ids": train_group_ids,
        "test_group_ids": test_group_ids,
        "train_trace_count": len(train_indices),
        "test_trace_count": len(test_indices),
        "group_disjoint": True,
        "all_classes_in_both_sets": True,
        "warning": (
            "group-disjoint split only; dataset representativeness, provenance, "
            "independence of groups, and attacker validity remain unverified"
        ),
    }
