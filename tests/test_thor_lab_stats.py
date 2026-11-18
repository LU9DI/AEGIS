"""Unit tests for the THOR lab statistics helpers."""
from __future__ import annotations

import math

import pytest

from anonlab.thor_lab.stats import (
    bootstrap_ci,
    mean,
    paired_ratio,
    percentile,
    ratio_ci,
    stdev,
    summarize,
)


def test_percentile_matches_linear_interpolation() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.0) == pytest.approx(1.0)
    assert percentile(values, 0.5) == pytest.approx(2.5)
    assert percentile(values, 1.0) == pytest.approx(4.0)
    assert percentile(values, 0.25) == pytest.approx(1.75)


def test_percentile_single_sample_and_validation() -> None:
    assert percentile([5.0], 0.99) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        percentile([], 0.5)
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)
    with pytest.raises(ValueError):
        percentile([1.0, math.nan], 0.5)
    with pytest.raises(ValueError):
        percentile("not-a-sequence", 0.5)  # type: ignore[arg-type]


def test_summarize_reports_every_requested_percentile() -> None:
    summary = summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert summary["n"] == 5
    assert summary["p50"] == pytest.approx(3.0)
    assert summary["p99"] >= summary["p95"] >= summary["p50"]
    assert summary["min"] == pytest.approx(1.0)
    assert summary["max"] == pytest.approx(5.0)
    assert mean([1.0, 3.0]) == pytest.approx(2.0)
    assert stdev([2.0]) == 0.0
    assert stdev([1.0, 3.0]) == pytest.approx(math.sqrt(2.0))


def test_bootstrap_ci_is_seeded_and_marks_small_samples_unreliable() -> None:
    values = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    first = bootstrap_ci(values, seed=7)
    second = bootstrap_ci(values, seed=7)
    assert first == second
    assert first["reliable"] == 1.0
    assert first["low"] <= first["point"] <= first["high"]

    small = bootstrap_ci(values[:3])
    assert small["reliable"] == 0.0
    assert small["low"] == small["point"] == small["high"]
    assert small["resamples"] == 0


def test_bootstrap_ci_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError):
        bootstrap_ci([1.0, 2.0], resamples=10)
    with pytest.raises(ValueError):
        bootstrap_ci([1.0, 2.0], confidence=1.0)


def test_paired_ratio_pairs_positionally_and_rejects_bad_denominators() -> None:
    ratios = paired_ratio([2.0, 4.0], [1.0, 2.0])
    assert ratios == [2.0, 2.0]
    with pytest.raises(ValueError):
        paired_ratio([2.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        paired_ratio([2.0], [0.0])


def test_ratio_ci_reports_paired_trials() -> None:
    result = ratio_ci([50.0, 55.0, 60.0, 52.0, 58.0], [100.0] * 5)
    assert result["paired_trials"] == 5
    assert 0.4 < float(result["point"]) < 0.7
    assert result["ratios"] == [0.5, 0.55, 0.6, 0.52, 0.58]
