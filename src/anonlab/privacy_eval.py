"""Reproducible synthetic path and traffic-fingerprinting evaluation harness.

This is a research simulation, not a network measurement or an anonymity proof.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CandidatePath:
    path_id: str
    detour_ms: float
    relay_asns: tuple[str, ...]
    hops: int
    capacity_mbps: float = 100.0


def select_path(
    candidates: list[CandidatePath],
    *,
    max_detour_ms: float,
    rng: random.Random,
    avoid_entry_exit_as: bool = True,
) -> CandidatePath:
    """Randomize among feasible paths; reject candidates that fail hard constraints."""
    feasible = [
        path for path in candidates
        if path.detour_ms >= 0
        and path.detour_ms <= max_detour_ms
        and path.hops >= 2
        and path.capacity_mbps > 0
        and (not avoid_entry_exit_as or len(path.relay_asns) < 2
             or path.relay_asns[0] != path.relay_asns[-1])
    ]
    if not feasible:
        raise ValueError("no path satisfies the configured latency and AS constraints")
    return rng.choice(feasible)


def make_synthetic_traces(
    *, classes: int = 6, samples_per_class: int = 80, seed: int = 20261014
) -> list[dict[str, Any]]:
    """Generate deliberately synthetic traces with class-specific burst patterns."""
    if classes < 2 or samples_per_class < 4:
        raise ValueError("need at least 2 classes and 4 samples per class")
    rng = random.Random(seed)
    traces = []
    for label in range(classes):
        for _ in range(samples_per_class):
            packets = []
            # Class-specific pattern is intentionally learnable so defense effects can be tested.
            burst_count = 3 + (label % 4)
            for burst in range(burst_count):
                base = 350 + label * 95 + burst * 23
                count = 2 + ((label + burst) % 5)
                for packet_index in range(count):
                    direction = 1 if (burst + label) % 2 == 0 else -1
                    size = max(40, min(1500, int(rng.gauss(base + packet_index * 17, 45))))
                    delay = max(1.0, rng.gauss(18 + label * 2 + burst * 3, 4))
                    packets.append((direction, size, delay))
            rng.shuffle(packets)
            traces.append({"label": label, "packets": packets})
    rng.shuffle(traces)
    return traces


def pad_trace(trace: dict[str, Any], *, bucket_bytes: int, cover_rate: float, seed: int) -> dict[str, Any]:
    """Apply a toy first-hop size-bucketing/cover model, recording overhead transparently."""
    if bucket_bytes < 64 or not 0 <= cover_rate <= 1:
        raise ValueError("bucket_bytes must be >=64 and cover_rate must be in [0,1]")
    rng = random.Random(seed)
    packets = []
    original_bytes = sum(packet[1] for packet in trace["packets"])
    for direction, size, delay in trace["packets"]:
        padded_size = int(math.ceil(size / bucket_bytes) * bucket_bytes)
        packets.append((direction, padded_size, delay))
        # Cover packets are modeled at the client-to-entry link only.
        if rng.random() < cover_rate:
            packets.append((1, bucket_bytes, max(1.0, delay + rng.uniform(1, 12))))
    return {
        "label": trace["label"],
        "packets": packets,
        "original_bytes": original_bytes,
        "observed_bytes": sum(packet[1] for packet in packets),
    }


def features(trace: dict[str, Any], *, bins: int = 24) -> tuple[float, ...]:
    """Compact directional size/time histogram suitable for a tiny baseline classifier."""
    packets = trace["packets"]
    if not packets:
        return (0.0,) * (bins * 2 + 4)
    size_hist = [0.0] * bins
    delay_hist = [0.0] * bins
    up = down = total_bytes = 0
    for direction, size, delay in packets:
        size_hist[min(bins - 1, int(size / 1500 * bins))] += 1
        delay_hist[min(bins - 1, int(min(delay, 120) / 120 * bins))] += 1
        if direction > 0:
            up += 1
        else:
            down += 1
        total_bytes += size
    n = len(packets)
    return tuple(
        [value / n for value in size_hist]
        + [value / n for value in delay_hist]
        + [up / n, down / n, math.log1p(total_bytes), math.log1p(n)]
    )


def evaluate_nearest_centroid(
    traces: list[dict[str, Any]], *, seed: int = 20261014, train_fraction: float = 0.65
) -> dict[str, Any]:
    """Evaluate a deterministic nearest-centroid fingerprinting attacker on a holdout set."""
    if not 0.4 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.4 and 0.8")
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        grouped[int(trace["label"])].append(trace)
    rng = random.Random(seed)
    train, test = [], []
    for label, group in sorted(grouped.items()):
        if len(group) < 4:
            raise ValueError("each class needs at least 4 traces")
        group = list(group)
        rng.shuffle(group)
        split = max(2, min(len(group) - 1, int(len(group) * train_fraction)))
        train.extend(group[:split])
        test.extend(group[split:])
    vectors = [(int(t["label"]), features(t)) for t in train]
    centroids = {}
    for label in grouped:
        rows = [vector for y, vector in vectors if y == label]
        centroids[label] = tuple(sum(row[i] for row in rows) / len(rows) for i in range(len(rows[0])))
    correct = 0
    per_class = defaultdict(lambda: [0, 0])
    for trace in test:
        vector = features(trace)
        prediction = min(
            centroids,
            key=lambda label: sum((a - b) ** 2 for a, b in zip(vector, centroids[label])),
        )
        label = int(trace["label"])
        per_class[label][1] += 1
        per_class[label][0] += int(prediction == label)
        correct += int(prediction == label)
    return {
        "classifier": "nearest-centroid synthetic baseline",
        "train_samples": len(train),
        "test_samples": len(test),
        "accuracy": correct / len(test),
        "chance_accuracy": 1 / len(grouped),
        "per_class_accuracy": {str(k): v[0] / v[1] for k, v in sorted(per_class.items())},
    }


def run_evaluation(seed: int = 20261014) -> dict[str, Any]:
    rng = random.Random(seed)
    candidates = [
        CandidatePath("regional-a", 4.0, ("AS64501", "AS64502", "AS64503"), 3, 80),
        CandidatePath("regional-b", 6.0, ("AS64504", "AS64505", "AS64506"), 3, 60),
        CandidatePath("regional-c", 8.0, ("AS64507", "AS64508", "AS64509"), 3, 120),
        CandidatePath("bad-shared-as", 2.0, ("AS64510", "AS64511", "AS64510"), 3, 200),
        CandidatePath("too-slow", 45.0, ("AS64512", "AS64513", "AS64514"), 3, 40),
    ]
    selections = [select_path(candidates, max_detour_ms=12, rng=rng) for _ in range(500)]
    traces = make_synthetic_traces(seed=seed)
    padded = [
        pad_trace(t, bucket_bytes=256, cover_rate=0.25, seed=seed + index)
        for index, t in enumerate(traces)
    ]
    plain_attack = evaluate_nearest_centroid(traces, seed=seed)
    padded_attack = evaluate_nearest_centroid(padded, seed=seed)
    original_bytes = sum(t["original_bytes"] for t in padded)
    observed_bytes = sum(t["observed_bytes"] for t in padded)

    # A small parameter sweep prevents a single arbitrary padding setting from
    # being mistaken for evidence that the defense works.
    defense_sweep = []
    for bucket_bytes in (128, 256, 512, 1024):
        for cover_rate in (0.0, 0.25, 0.5, 0.75, 1.0):
            defended = [
                pad_trace(
                    trace,
                    bucket_bytes=bucket_bytes,
                    cover_rate=cover_rate,
                    seed=seed + index,
                )
                for index, trace in enumerate(traces)
            ]
            defended_original = sum(item["original_bytes"] for item in defended)
            defended_observed = sum(item["observed_bytes"] for item in defended)
            attack = evaluate_nearest_centroid(defended, seed=seed)
            defense_sweep.append({
                "bucket_bytes": bucket_bytes,
                "cover_rate": cover_rate,
                "fingerprinting_accuracy": attack["accuracy"],
                "chance_accuracy": attack["chance_accuracy"],
                "original_bytes": defended_original,
                "observed_bytes": defended_observed,
                "byte_overhead_ratio": (
                    defended_observed / defended_original - 1
                    if defended_original else 0
                ),
            })
    return {
        "schema_version": 1,
        "experiment": "synthetic_path_and_website_fingerprinting",
        "seed": seed,
        "is_live_network_test": False,
        "is_security_proof": False,
        "path_selection": {
            "candidate_count": len(candidates),
            "selection_count": len(selections),
            "max_detour_ms": 12,
            "as_entry_exit_constraint": "entry ASN must differ from exit ASN",
            "selected_path_counts": {
                path.path_id: sum(selected.path_id == path.path_id for selected in selections)
                for path in candidates
            },
            "warning": "synthetic detour/ASN data; not geolocation or BGP inference",
        },
        "fingerprinting": {
            "plain": plain_attack,
            "padded": padded_attack,
            "padding": {
                "placement": "client-to-entry only (synthetic model)",
                "bucket_bytes": 256,
                "cover_rate": 0.25,
                "original_bytes": original_bytes,
                "observed_bytes": observed_bytes,
                "byte_overhead_ratio": (observed_bytes / original_bytes - 1) if original_bytes else 0,
            },
            "warning": "synthetic labels and a simple classifier; not Deep Fingerprinting or Tor comparison",
            "defense_sweep": defense_sweep,
            "defense_sweep_interpretation": (
                "Synthetic parameter exploration only; choose settings using held-out "
                "realistic traces and a declared privacy/overhead objective."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-padding-overhead", type=float, help="optional acceptance threshold, e.g. 0.50 for <=50%% byte overhead")
    parser.add_argument("--max-fingerprinting-accuracy", type=float, help="optional acceptance threshold in [0,1] for the padded synthetic attack")
    args = parser.parse_args()
    if args.max_padding_overhead is not None and args.max_padding_overhead < 0:
        parser.error("--max-padding-overhead must be >= 0")
    if args.max_fingerprinting_accuracy is not None and not 0 <= args.max_fingerprinting_accuracy <= 1:
        parser.error("--max-fingerprinting-accuracy must be in [0,1]")
    result = run_evaluation(args.seed)
    checks = []
    overhead = result["fingerprinting"]["padding"]["byte_overhead_ratio"]
    accuracy = result["fingerprinting"]["padded"]["accuracy"]
    if args.max_padding_overhead is not None:
        checks.append({"metric": "padding_byte_overhead_ratio", "limit": args.max_padding_overhead, "observed": overhead, "passed": overhead <= args.max_padding_overhead})
    if args.max_fingerprinting_accuracy is not None:
        checks.append({"metric": "padded_fingerprinting_accuracy", "limit": args.max_fingerprinting_accuracy, "observed": accuracy, "passed": accuracy <= args.max_fingerprinting_accuracy})
    result["acceptance_checks"] = {"checks": checks, "passed": all(check["passed"] for check in checks)}
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            parser.error(f"refusing to overwrite existing artifact: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if checks and not result["acceptance_checks"]["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
