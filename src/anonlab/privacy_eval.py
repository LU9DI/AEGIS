"""Reproducible synthetic path and traffic-fingerprinting evaluation harness.

This is a research simulation, not a network measurement or an anonymity proof.
Reported numbers describe a synthetic model with a deliberately simple
classifier; they do not measure latency, throughput, or real Tor comparison
performance, and they are not evidence that a defense works on real traffic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from anonlab.trace_dataset import grouped_train_test_split, load_normalized_jsonl


@dataclass(frozen=True)
class CandidatePath:
    path_id: str
    detour_ms: float
    relay_asns: tuple[str, ...]
    hops: int
    capacity_mbps: float = 100.0


def repeated_as_observers(relay_asns: Sequence[str]) -> tuple[str, ...]:
    """Return autonomous systems occupying more than one position of the path.

    A single AS that hosts several relays of one circuit observes multiple
    points of that route. Comparing only the entry and exit ASes misses
    partial-route observers such as an AS hosting the entry hop and a middle
    hop. This helper names those observers so the selector can reject them.
    """
    counts: dict[str, int] = defaultdict(int)
    for asn in relay_asns:
        counts[asn] += 1
    return tuple(sorted(asn for asn, count in counts.items() if count > 1))


def select_path(
    candidates: list[CandidatePath],
    *,
    max_detour_ms: float,
    rng: random.Random,
    avoid_entry_exit_as: bool = True,
    require_distinct_as_observers: bool = True,
) -> CandidatePath:
    """Randomize among feasible paths; reject candidates that fail hard constraints.

    Threat-model notes (synthetic data, no BGP or geolocation inference):

    - ``avoid_entry_exit_as`` rejects a shared entry/exit AS, because an
      observer in that AS sees both ends of the circuit and can correlate
      them directly.
    - ``require_distinct_as_observers`` additionally rejects any AS that
      appears at more than one position of the path. That covers
      partial-route observers (for example, entry + middle, or middle +
      exit) that a first-vs-last comparison alone would accept, and it
      matches the ``max_same_asn=1`` diversity constraint used by the
      offline route scorer.

    These are necessary-but-not-sufficient constraints: they do not model
    route asymmetry, upstream transit sharing, or real AS topology, and they
    do not by themselves provide anonymity against a global observer.
    """

    def as_feasible(path: CandidatePath) -> bool:
        asns = path.relay_asns
        if require_distinct_as_observers and repeated_as_observers(asns):
            return False
        if avoid_entry_exit_as and len(asns) >= 2 and asns[0] == asns[-1]:
            return False
        return True

    feasible = [
        path for path in candidates
        if path.detour_ms >= 0
        and path.detour_ms <= max_detour_ms
        and path.hops >= 2
        and path.capacity_mbps > 0
        and as_feasible(path)
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


def stratified_split_indices(
    labels: Sequence[int], *, seed: int = 20261014, train_fraction: float = 0.65
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split trace indices per class into train/test sets.

    The split is derived once from the *undefended* traces and then reused for
    every defense configuration, so all attackers train and are tested on the
    exact same holdout (paired comparison) and no trace index appears in both
    sets. Each class keeps at least two training traces and at least one test
    trace, mirroring the previous inline split logic.
    """
    if not 0.4 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.4 and 0.8")
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        grouped[int(label)].append(index)
    rng = random.Random(seed)
    train: list[int] = []
    test: list[int] = []
    for label in sorted(grouped):
        group = grouped[label]
        if len(group) < 4:
            raise ValueError("each class needs at least 4 traces")
        rng.shuffle(group)
        split = max(2, min(len(group) - 1, int(len(group) * train_fraction)))
        train.extend(group[:split])
        test.extend(group[split:])
    return tuple(train), tuple(test)


def _split_digest(indices: tuple[int, ...]) -> str:
    joined = ",".join(str(index) for index in indices)
    return hashlib.sha256(joined.encode("ascii")).hexdigest()[:16]


def _validate_split(total: int, split: tuple[Sequence[int], Sequence[int]]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    train_indices, test_indices = (tuple(split[0]), tuple(split[1]))
    seen: set[int] = set()
    for index in train_indices + test_indices:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < total:
            raise ValueError("split indices must be integers within the trace range")
        if index in seen:
            raise ValueError("split reuses a trace index; train/test data would leak")
        seen.add(index)
    if not train_indices or not test_indices:
        raise ValueError("split must leave at least one training and one test trace")
    return train_indices, test_indices


def evaluate_nearest_centroid(
    traces: list[dict[str, Any]],
    *,
    seed: int = 20261014,
    train_fraction: float = 0.65,
    split: tuple[Sequence[int], Sequence[int]] | None = None,
) -> dict[str, Any]:
    """Evaluate a deterministic nearest-centroid fingerprinting attacker on a holdout set.

    Reports accuracy next to the chance baseline, a confusion matrix, and
    per-class precision/recall/F1. When ``split`` is provided it is reused
    verbatim (``train_fraction`` is then ignored) so several defense
    configurations can be compared on an identical holdout.
    """
    if not traces:
        raise ValueError("no traces to evaluate")
    labels = [int(trace["label"]) for trace in traces]
    if split is None:
        train_indices, test_indices = stratified_split_indices(
            labels, seed=seed, train_fraction=train_fraction
        )
    else:
        train_indices, test_indices = _validate_split(len(traces), split)
    train = [traces[index] for index in train_indices]
    test = [traces[index] for index in test_indices]

    vectors = [(int(t["label"]), features(t)) for t in train]
    centroid_labels = sorted({label for label, _ in vectors})
    centroids = {}
    for label in centroid_labels:
        rows = [vector for y, vector in vectors if y == label]
        centroids[label] = tuple(sum(row[i] for row in rows) / len(rows) for i in range(len(rows[0])))
    test_labels = sorted({int(t["label"]) for t in test})
    missing = [label for label in test_labels if label not in centroids]
    if missing:
        raise ValueError(f"split leaves classes without training traces: {missing}")

    predictions = {}
    for index, trace in zip(test_indices, test):
        vector = features(trace)
        predictions[index] = min(
            centroids,
            key=lambda label: sum((a - b) ** 2 for a, b in zip(vector, centroids[label])),
        )

    matrix_labels = sorted(set(centroid_labels) | set(test_labels))
    confusion: dict[int, dict[int, int]] = {
        actual: {predicted: 0 for predicted in matrix_labels} for actual in matrix_labels
    }
    correct = 0
    for index, trace in zip(test_indices, test):
        actual = int(trace["label"])
        predicted = predictions[index]
        confusion[actual][predicted] += 1
        correct += int(predicted == actual)

    per_class: dict[str, dict[str, float | int]] = {}
    for label in matrix_labels:
        support = sum(confusion[label].values())
        predicted_count = sum(confusion[actual][label] for actual in matrix_labels)
        true_positive = confusion[label][label]
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[str(label)] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    return {
        "classifier": "nearest-centroid synthetic baseline",
        "train_samples": len(train),
        "test_samples": len(test),
        "accuracy": correct / len(test),
        "chance_accuracy": 1 / len(centroids),
        "per_class_accuracy": {
            str(label): (confusion[label][label] / sum(confusion[label].values())) if sum(confusion[label].values()) else 0.0
            for label in matrix_labels
        },
        "per_class": per_class,
        "confusion_matrix": {
            str(actual): {str(predicted): count for predicted, count in row.items()}
            for actual, row in confusion.items()
        },
        "split": {
            "train_size": len(train_indices),
            "test_size": len(test_indices),
            "train_digest": _split_digest(train_indices),
            "test_digest": _split_digest(test_indices),
        },
    }


def run_evaluation(seed: int = 20261014) -> dict[str, Any]:
    rng = random.Random(seed)
    candidates = [
        CandidatePath("regional-a", 4.0, ("AS64501", "AS64502", "AS64503"), 3, 80),
        CandidatePath("regional-b", 6.0, ("AS64504", "AS64505", "AS64506"), 3, 60),
        CandidatePath("regional-c", 8.0, ("AS64507", "AS64508", "AS64509"), 3, 120),
        CandidatePath("bad-shared-as", 2.0, ("AS64510", "AS64511", "AS64510"), 3, 200),
        # Entry and exit differ, but AS64520 sits at the entry and at a middle
        # hop: it observes two positions and could anchor the circuit. The
        # previous entry-vs-exit-only check would have accepted this path.
        CandidatePath("bad-repeated-middle-as", 3.0, ("AS64520", "AS64521", "AS64520", "AS64522"), 4, 150),
        CandidatePath("too-slow", 45.0, ("AS64512", "AS64513", "AS64514"), 3, 40),
    ]
    selections = [select_path(candidates, max_detour_ms=12, rng=rng) for _ in range(500)]
    traces = make_synthetic_traces(seed=seed)
    padded = [
        pad_trace(t, bucket_bytes=256, cover_rate=0.25, seed=seed + index)
        for index, t in enumerate(traces)
    ]
    # One split for every attacker, derived from the undefended traces, so no
    # defense configuration sees a different holdout and no trace leaks across
    # the train/test boundary.
    split = stratified_split_indices([int(t["label"]) for t in traces], seed=seed)
    plain_attack = evaluate_nearest_centroid(traces, seed=seed, split=split)
    padded_attack = evaluate_nearest_centroid(padded, seed=seed, split=split)
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
            attack = evaluate_nearest_centroid(defended, seed=seed, split=split)
            defense_sweep.append({
                "bucket_bytes": bucket_bytes,
                "cover_rate": cover_rate,
                "fingerprinting_accuracy": attack["accuracy"],
                "chance_accuracy": attack["chance_accuracy"],
                "per_class_accuracy": attack["per_class_accuracy"],
                "test_samples": attack["test_samples"],
                "original_bytes": defended_original,
                "observed_bytes": defended_observed,
                "byte_overhead_ratio": (
                    defended_observed / defended_original - 1
                    if defended_original else 0
                ),
            })
    as_conflicts = {
        path.path_id: list(repeated_as_observers(path.relay_asns))
        for path in candidates
        if repeated_as_observers(path.relay_asns)
    }
    return {
        "schema_version": 2,
        "experiment": "synthetic_path_and_website_fingerprinting",
        "seed": seed,
        "is_live_network_test": False,
        "is_security_proof": False,
        "not_measured": {
            "latency": "synthetic delay values are model parameters, not measurements",
            "throughput": "no transport simulation is performed by this harness",
            "real_traffic": "no packet capture or external dataset is loaded",
        },
        "path_selection": {
            "candidate_count": len(candidates),
            "selection_count": len(selections),
            "max_detour_ms": 12,
            "as_policy": {
                "entry_exit_disjoint": True,
                "all_positions_distinct": True,
                "note": (
                    "rejects any autonomous system appearing at more than one path position; "
                    "synthetic AS labels, not BGP or geolocation inference"
                ),
            },
            "as_conflict_rejections": as_conflicts,
            "selected_paths_with_as_conflict": sum(
                bool(repeated_as_observers(selected.relay_asns)) for selected in selections
            ),
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


def run_external_trace_evaluation(
    dataset_path: str | Path,
    *,
    seed: int = 20261016,
    train_fraction: float = 0.65,
    bucket_bytes: int = 256,
    cover_rate: float = 0.25,
) -> dict[str, Any]:
    """Evaluate the baseline attacker on validated external traces with group isolation.

    Compare an undefended baseline with a toy size-bucketing/cover transform on
    the same group-disjoint holdout. This is not a production defense model and
    does not claim the dataset is representative or compare against Tor.
    """
    dataset = load_normalized_jsonl(dataset_path)
    traces = dataset["traces"]
    split_result = grouped_train_test_split(
        traces, seed=seed, train_fraction=train_fraction
    )
    split = (split_result["train_indices"], split_result["test_indices"])
    attack = evaluate_nearest_centroid(traces, seed=seed, split=split)
    defended = [
        pad_trace(trace, bucket_bytes=bucket_bytes, cover_rate=cover_rate, seed=seed + index)
        for index, trace in enumerate(traces)
    ]
    defended_attack = evaluate_nearest_centroid(defended, seed=seed, split=split)
    original_bytes = sum(item["original_bytes"] for item in defended)
    observed_bytes = sum(item["observed_bytes"] for item in defended)
    byte_overhead = observed_bytes / original_bytes - 1 if original_bytes else 0
    return {
        "schema_version": 1,
        "experiment": "external_trace_fingerprinting_baseline",
        "seed": seed,
        "is_live_network_test": False,
        "is_security_proof": False,
        "dataset_origin": "caller-provided file; provenance and authenticity are not independently verified",
        "dataset": {
            "sha256": dataset["sha256"],
            "byte_size": dataset["byte_size"],
            "trace_count": dataset["trace_count"],
            "class_count": dataset["class_count"],
            "schema_version": dataset["schema_version"],
        },
        "split": {
            "method": "group-disjoint randomized split",
            "target_train_fraction": train_fraction,
            "train_trace_count": split_result["train_trace_count"],
            "test_trace_count": split_result["test_trace_count"],
            "train_group_count": len(split_result["train_group_ids"]),
            "test_group_count": len(split_result["test_group_ids"]),
            "train_groups_sha256": hashlib.sha256(
                "\n".join(split_result["train_group_ids"]).encode("utf-8")
            ).hexdigest(),
            "test_groups_sha256": hashlib.sha256(
                "\n".join(split_result["test_group_ids"]).encode("utf-8")
            ).hexdigest(),
            "group_disjoint": split_result["group_disjoint"],
            "all_classes_in_both_sets": split_result["all_classes_in_both_sets"],
            "warning": split_result["warning"],
        },
        "attacker": attack,
        "toy_defense": {
            "model": "size bucketing plus probabilistic cover packets; abstract first-hop model only",
            "bucket_bytes": bucket_bytes,
            "cover_rate": cover_rate,
            "original_bytes": original_bytes,
            "observed_bytes": observed_bytes,
            "byte_overhead_ratio": byte_overhead,
            "attacker": defended_attack,
            "accuracy_delta_vs_undefended": defended_attack["accuracy"] - attack["accuracy"],
            "same_group_disjoint_holdout": attack["split"] == defended_attack["split"],
            "warning": (
                "toy transform and simple classifier only; packet timing, real protocol behavior, "
                "traffic adaptation, and stronger attackers are not modeled"
            ),
        },
        "not_measured": {
            "defense_effectiveness": "only this toy transform and this simple attacker were evaluated; no privacy guarantee",
            "tor_comparison": "no Tor or matched baseline comparison was performed",
            "dataset_representativeness": "not independently assessed",
            "capture_provenance": "dataset provenance and authenticity are not independently verified; only file digest and counts are recorded",
            "network_performance": "no live network latency or throughput was measured",
        },
        "warning": (
            "external input validated and evaluated with a simple nearest-centroid baseline; "
            "this is not Deep Fingerprinting, not a Tor comparison, and not a privacy guarantee"
        ),
    }


def _spread(values: Sequence[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "pstdev": statistics.pstdev(values),
    }


def run_seed_stability(seeds: Sequence[int]) -> dict[str, Any]:
    """Repeat the full evaluation across seeds and report the observed spread.

    Each seed regenerates synthetic traces (same class layout, different
    packet content), so the spread quantifies how sensitive the synthetic
    results are to trace sampling. It is not a substitute for independent
    replicated datasets, and a small spread here does not mean the defense is
    robust on real traffic.
    """
    cleaned: list[int] = []
    for value in seeds:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("stability seeds must be integers")
        cleaned.append(value)
    if len(cleaned) < 2:
        raise ValueError("at least two seeds are required for a stability report")
    runs = []
    sweep_accuracy: dict[tuple[int, float], list[float]] = defaultdict(list)
    sweep_overhead: dict[tuple[int, float], list[float]] = defaultdict(list)
    for seed in cleaned:
        result = run_evaluation(seed)
        fingerprinting = result["fingerprinting"]
        runs.append({
            "seed": seed,
            "plain_accuracy": fingerprinting["plain"]["accuracy"],
            "padded_accuracy": fingerprinting["padded"]["accuracy"],
            "padded_byte_overhead_ratio": fingerprinting["padding"]["byte_overhead_ratio"],
        })
        for row in fingerprinting["defense_sweep"]:
            key = (row["bucket_bytes"], row["cover_rate"])
            sweep_accuracy[key].append(row["fingerprinting_accuracy"])
            sweep_overhead[key].append(row["byte_overhead_ratio"])
    return {
        "seeds": cleaned,
        "runs": runs,
        "plain_accuracy_spread": _spread([run["plain_accuracy"] for run in runs]),
        "padded_accuracy_spread": _spread([run["padded_accuracy"] for run in runs]),
        "padded_byte_overhead_ratio_spread": _spread(
            [run["padded_byte_overhead_ratio"] for run in runs]
        ),
        "defense_sweep_spread": [
            {
                "bucket_bytes": bucket_bytes,
                "cover_rate": cover_rate,
                "accuracy_spread": _spread(sweep_accuracy[(bucket_bytes, cover_rate)]),
                "byte_overhead_ratio_spread": _spread(sweep_overhead[(bucket_bytes, cover_rate)]),
            }
            for bucket_bytes, cover_rate in sorted(sweep_accuracy)
        ],
        "warning": (
            "spread across synthetic sampling seeds only; not a confidence interval "
            "and not evidence of behavior on real traffic"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--trace-dataset",
        type=Path,
        help="evaluate a normalized external JSONL dataset using a group-disjoint holdout (baseline attacker only)",
    )
    parser.add_argument(
        "--train-fraction",
        type=float,
        default=0.65,
        help="target training fraction for --trace-dataset (0.4..0.8; groups remain intact)",
    )
    parser.add_argument(
        "--trace-bucket-bytes",
        type=int,
        default=256,
        help="toy external-trace defense packet-size bucket (minimum 64 bytes)",
    )
    parser.add_argument(
        "--trace-cover-rate",
        type=float,
        default=0.25,
        help="toy external-trace cover packet probability per observed packet (0..1)",
    )
    parser.add_argument("--max-padding-overhead", type=float, help="optional acceptance threshold, e.g. 0.50 for <=50%% byte overhead")
    parser.add_argument("--max-fingerprinting-accuracy", type=float, help="optional acceptance threshold in [0,1] for the padded synthetic attack")
    parser.add_argument(
        "--stability-seeds",
        help="optional comma-separated integer seeds (at least two) to repeat the full evaluation and report the observed spread, e.g. 20261014,20261015",
    )
    args = parser.parse_args()
    if args.trace_dataset is not None:
        if args.stability_seeds is not None or args.max_padding_overhead is not None or args.max_fingerprinting_accuracy is not None:
            parser.error("--trace-dataset cannot be combined with synthetic-only stability or acceptance options")
        try:
            external_result = run_external_trace_evaluation(
                args.trace_dataset,
                seed=args.seed,
                train_fraction=args.train_fraction,
                bucket_bytes=args.trace_bucket_bytes,
                cover_rate=args.trace_cover_rate,
            )
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        rendered = json.dumps(external_result, indent=2, sort_keys=True) + "\n"
        if args.output:
            if args.output.exists():
                parser.error(f"refusing to overwrite existing artifact: {args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return
    if args.max_padding_overhead is not None and args.max_padding_overhead < 0:
        parser.error("--max-padding-overhead must be >= 0")
    if args.max_fingerprinting_accuracy is not None and not 0 <= args.max_fingerprinting_accuracy <= 1:
        parser.error("--max-fingerprinting-accuracy must be in [0,1]")
    stability_seeds: list[int] | None = None
    if args.stability_seeds is not None:
        parts = [part.strip() for part in args.stability_seeds.split(",")]
        if len(parts) < 2 or any(not part for part in parts):
            parser.error("--stability-seeds needs at least two comma-separated integer seeds")
        try:
            stability_seeds = [int(part) for part in parts]
        except ValueError:
            parser.error("--stability-seeds values must be integers")
    result = run_evaluation(args.seed)
    if stability_seeds is not None:
        result["seed_stability"] = run_seed_stability(stability_seeds)
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
