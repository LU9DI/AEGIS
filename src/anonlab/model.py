"""Typed models used by the REA anonymous-network simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CoverMode = Literal["none", "independent_noise", "fixed_rate"]


@dataclass(frozen=True, slots=True)
class Hop:
    """A simplified network hop.

    `latency_ms` is one-way propagation/forwarding delay. `bandwidth_mbps` is
    the modeled service capacity for the flow-level approximation.
    """

    latency_ms: float
    jitter_ms: float
    bandwidth_mbps: float

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("hop latency must be >= 0")
        if self.jitter_ms < 0:
            raise ValueError("hop jitter must be >= 0")
        if self.bandwidth_mbps <= 0:
            raise ValueError("hop bandwidth must be > 0")


@dataclass(frozen=True, slots=True)
class NetworkProfile:
    """Hypothetical network profile for comparative experiments."""

    name: str
    hops: tuple[Hop, ...]
    cover_mode: CoverMode = "none"
    cover_ratio_per_edge: float = 0.0
    fixed_rate_mbps: float = 0.0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must not be empty")
        if not self.hops:
            raise ValueError("profile must contain at least one hop")
        if self.cover_mode not in ("none", "independent_noise", "fixed_rate"):
            raise ValueError(f"unsupported cover mode: {self.cover_mode}")
        if self.cover_ratio_per_edge < 0:
            raise ValueError("cover ratio must be >= 0")
        if self.cover_mode == "fixed_rate" and self.fixed_rate_mbps <= 0:
            raise ValueError("fixed_rate mode requires fixed_rate_mbps > 0")

    @property
    def bottleneck_mbps(self) -> float:
        return min(hop.bandwidth_mbps for hop in self.hops)

    @property
    def propagation_ms(self) -> float:
        return sum(hop.latency_ms for hop in self.hops)


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    duration_s: float = 180.0
    bin_ms: int = 100
    request_rate_per_s: float = 1.4
    seed: int = 20261009
    max_correlation_lag_ms: int = 3000

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if self.bin_ms <= 0:
            raise ValueError("bin_ms must be > 0")
        if self.request_rate_per_s <= 0:
            raise ValueError("request_rate_per_s must be > 0")
        if self.max_correlation_lag_ms < 0:
            raise ValueError("max_correlation_lag_ms must be >= 0")


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    profile: str
    event_count: int
    payload_mb: float
    offered_load_mbps: float
    bottleneck_mbps: float
    p50_latency_ms: float
    p95_latency_ms: float
    max_lag_pearson: float | None
    correlation_lag_ms: int | None
    cover_mb: float
    traffic_overhead_ratio: float
    fixed_rate_mbps: float | None
    interpretation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "event_count": self.event_count,
            "payload_mb": round(self.payload_mb, 3),
            "offered_load_mbps": round(self.offered_load_mbps, 3),
            "bottleneck_mbps": round(self.bottleneck_mbps, 3),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "max_lag_pearson": None if self.max_lag_pearson is None else round(self.max_lag_pearson, 4),
            "correlation_lag_ms": self.correlation_lag_ms,
            "cover_mb": round(self.cover_mb, 3),
            "traffic_overhead_ratio": round(self.traffic_overhead_ratio, 4),
            "fixed_rate_mbps": self.fixed_rate_mbps,
            "interpretation": self.interpretation,
        }
