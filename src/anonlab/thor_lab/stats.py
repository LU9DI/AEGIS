"""Small, dependency-free statistics used by the THOR lab summaries.

The repository cannot take a numpy/scipy dependency for its core, so the few
statistics needed by the benchmark summary live here and are unit-tested
explicitly. Percentiles use linear interpolation between closest ranks
(Hyndman & Fan type 7, the default of ``R``'s ``quantile``); bootstrap
confidence intervals are seeded and therefore reproducible.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

__all__ = [
    "bootstrap_ci",
    "mean",
    "paired_ratio",
    "percentile",
    "ratio_ci",
    "stdev",
    "summarize",
]

_MIN_SAMPLES = 1


def _validate_samples(values: Sequence[float], *, name: str = "values") -> list[float]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of numbers, not {type(values).__name__}")
    materialized = [float(value) for value in values]
    if not materialized:
        raise ValueError(f"{name} must contain at least one sample")
    for value in materialized:
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain only finite numbers")
    return materialized


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return the interpolated percentile for ``fraction`` in ``[0, 1]``."""
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be within 0..1")
    samples = sorted(_validate_samples(values))
    if len(samples) == 1:
        return samples[0]
    position = fraction * (len(samples) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return samples[lower]
    weight = position - lower
    return samples[lower] * (1.0 - weight) + samples[upper] * weight


def mean(values: Sequence[float]) -> float:
    samples = _validate_samples(values)
    return math.fsum(samples) / len(samples)


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (n-1). Returns 0.0 for a single sample."""
    samples = _validate_samples(values)
    if len(samples) < 2:
        return 0.0
    average = mean(samples)
    return math.sqrt(math.fsum((value - average) ** 2 for value in samples) / (len(samples) - 1))


def summarize(values: Sequence[float]) -> dict[str, float | int]:
    """Full distribution summary used for every reported metric."""
    samples = _validate_samples(values)
    return {
        "n": len(samples),
        "mean": mean(samples),
        "stdev": stdev(samples),
        "min": min(samples),
        "max": max(samples),
        "p50": percentile(samples, 0.50),
        "p95": percentile(samples, 0.95),
        "p99": percentile(samples, 0.99),
    }


def bootstrap_ci(
    values: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float] = lambda sample: percentile(sample, 0.50),
    resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 20261118,
) -> dict[str, float]:
    """Seeded percentile-bootstrap interval for ``statistic``.

    With fewer than five samples the interval collapses onto the point estimate
    and ``reliable`` is False, so a two-trial run cannot masquerade as evidence.
    """
    samples = _validate_samples(values)
    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly within 0 and 1")
    point = float(statistic(samples))
    reliable = len(samples) >= 5
    if not reliable:
        return {
            "point": point,
            "low": point,
            "high": point,
            "confidence": confidence,
            "resamples": 0,
            "reliable": 0.0,
        }
    rng = random.Random(seed)
    size = len(samples)
    estimates: list[float] = []
    for _ in range(resamples):
        draw = [samples[rng.randrange(size)] for _ in range(size)]
        estimates.append(float(statistic(draw)))
    alpha = (1.0 - confidence) / 2.0
    return {
        "point": point,
        "low": percentile(estimates, alpha),
        "high": percentile(estimates, 1.0 - alpha),
        "confidence": confidence,
        "resamples": resamples,
        "reliable": 1.0,
    }


def paired_ratio(
    numerator: Sequence[float], denominator: Sequence[float]
) -> list[float]:
    """Per-trial ratios for two arms measured in the same trial slots.

    Pairing is positional: trial *i* of both arms must have been executed with
    the same workload and, in the interleaved runner, adjacent in time. A zero
    or negative denominator is a hard error rather than a dropped sample.
    """
    left = _validate_samples(numerator, name="numerator")
    right = _validate_samples(denominator, name="denominator")
    if len(left) != len(right):
        raise ValueError("paired samples must have the same length")
    ratios: list[float] = []
    for index, (top, bottom) in enumerate(zip(left, right, strict=True)):
        if bottom <= 0.0:
            raise ValueError(f"denominator must be positive; trial {index} has {bottom!r}")
        ratios.append(top / bottom)
    return ratios


def ratio_ci(
    numerator: Sequence[float],
    denominator: Sequence[float],
    *,
    resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 20261118,
) -> dict[str, object]:
    """Median of the paired per-trial ratios with a bootstrap interval."""
    ratios = paired_ratio(numerator, denominator)
    interval = bootstrap_ci(
        ratios,
        statistic=lambda sample: percentile(sample, 0.5),
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    return {
        "paired_trials": len(ratios),
        "ratios": ratios,
        **interval,
    }
