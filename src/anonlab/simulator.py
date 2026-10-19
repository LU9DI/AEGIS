"""Flow-level simulation for latency, overhead, and timing-correlation studies.

Important: this is a model, not packet-accurate emulation and not a
cryptographic or anonymity proof. Assumptions are documented in README.md.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Iterable

from .model import ExperimentConfig, ExperimentResult, NetworkProfile


@dataclass(frozen=True, slots=True)
class Flow:
    start_ms: float
    payload_bytes: int


def generate_workload(config: ExperimentConfig) -> list[Flow]:
    """Generate a deterministic, bursty workload from a Poisson arrival model."""
    rng = random.Random(config.seed)
    flows: list[Flow] = []
    t_s = rng.expovariate(config.request_rate_per_s)
    while t_s < config.duration_s:
        # Log-normal page sizes create a long-tailed workload. Clamp extremes to
        # keep a single event from dominating every run.
        payload = int(rng.lognormvariate(math.log(160_000), 0.9))
        payload = max(8_000, min(payload, 3_000_000))
        flows.append(Flow(start_ms=t_s * 1000.0, payload_bytes=payload))
        t_s += rng.expovariate(config.request_rate_per_s)
    return flows


def _add_burst(series: list[float], start_ms: float, payload_bytes: float,
               rate_mbps: float, bin_ms: int) -> None:
    """Spread a flow's bytes over bins at a modeled link rate."""
    if payload_bytes <= 0 or not series:
        return
    duration_ms = max(float(bin_ms), payload_bytes * 8.0 / (rate_mbps * 1000.0))
    chunks = max(1, math.ceil(duration_ms / bin_ms))
    per_chunk = payload_bytes / chunks
    for chunk in range(chunks):
        idx = int((start_ms + chunk * bin_ms) // bin_ms)
        if idx >= len(series):
            break
        if idx >= 0:
            series[idx] += per_chunk


def _sample_hop_delay(rng: random.Random, mean_ms: float, jitter_ms: float) -> float:
    return max(0.0, rng.gauss(mean_ms, jitter_ms))


def _flow_timings(
    flows: list[Flow], profile: NetworkProfile, seed: int
) -> list[tuple[Flow, float, float]]:
    """Return (flow, exit_start_ms, completion_ms) using a fluid/flow approximation.

    Link serialization is modeled as a shared FIFO server at each hop, while the
    payload is treated as a flow rather than millions of packets. The model is
    suitable for comparative experiments, not accurate production forecasts.
    """
    rng = random.Random(seed)
    available_ms = [0.0] * len(profile.hops)
    results: list[tuple[Flow, float, float]] = []
    min_rate = profile.bottleneck_mbps

    for flow in flows:
        cumulative_propagation = 0.0
        cumulative_queue_wait = 0.0
        for idx, hop in enumerate(profile.hops):
            cumulative_propagation += _sample_hop_delay(rng, hop.latency_ms, hop.jitter_ms)
            arrival_ms = flow.start_ms + cumulative_propagation + cumulative_queue_wait
            wait_ms = max(0.0, available_ms[idx] - arrival_ms)
            cumulative_queue_wait += wait_ms
            service_ms = flow.payload_bytes * 8.0 / (hop.bandwidth_mbps * 1000.0)
            service_start_ms = arrival_ms + wait_ms
            available_ms[idx] = service_start_ms + service_ms

        serialization_ms = flow.payload_bytes * 8.0 / (min_rate * 1000.0)
        exit_start_ms = flow.start_ms + cumulative_propagation + cumulative_queue_wait
        completion_ms = exit_start_ms + serialization_ms
        results.append((flow, exit_start_ms, completion_ms))
    return results


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = min(len(x), len(y))
    if n < 3:
        return None
    x = x[:n]
    y = y[:n]
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    dx = [v - mean_x for v in x]
    dy = [v - mean_y for v in y]
    ss_x = sum(v * v for v in dx)
    ss_y = sum(v * v for v in dy)
    if ss_x <= 1e-12 or ss_y <= 1e-12:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / math.sqrt(ss_x * ss_y)


def _max_lag_correlation(
    ingress: list[float], egress: list[float], bin_ms: int, max_lag_ms: int
) -> tuple[float | None, int | None]:
    """Find the largest Pearson correlation over a lag window.

    This is intentionally a simple timing/volume attacker. It does not implement
    packet fingerprints, direction sequences, website fingerprints, or ML attacks.
    """
    max_bins = max_lag_ms // bin_ms
    best: tuple[float, int] | None = None
    n = min(len(ingress), len(egress))
    for lag in range(-max_bins, max_bins + 1):
        if lag < 0:
            x = ingress[-lag:n]
            y = egress[: n + lag]
        elif lag > 0:
            x = ingress[: n - lag]
            y = egress[lag:n]
        else:
            x, y = ingress[:n], egress[:n]
        corr = _pearson(x, y)
        if corr is not None and (best is None or corr > best[0]):
            best = (corr, lag * bin_ms)
    return (None, None) if best is None else best


def _add_independent_noise(
    ingress: list[float], egress: list[float], target_bytes_per_edge: float,
    config: ExperimentConfig, seed: int, rate_mbps: float
) -> float:
    """Add independent, flow-shaped synthetic traffic to both observations.

    This intentionally represents an optimistic *independent-noise ceiling*.
    Noise bursts are page-flow-sized, not tiny random packets, so the experiment
    asks whether independent background demand can obscure flow-scale timing.
    It is not automatically achievable by adding dummy packets to one circuit.
    """
    rng = random.Random(seed)
    total_added = 0.0
    n_bins = min(len(ingress), len(egress))
    active_ms = config.duration_s * 1000.0
    for series in (ingress, egress):
        added = 0.0
        while added < target_bytes_per_edge:
            size = int(rng.lognormvariate(math.log(160_000), 0.9))
            size = max(8_000, min(size, 3_000_000))
            size = min(float(size), target_bytes_per_edge - added)
            if size <= 0:
                break
            start_ms = rng.uniform(0.0, active_ms)
            _add_burst(series, start_ms, size, rate_mbps, config.bin_ms)
            added += size
        total_added += added
    return total_added


def _fixed_rate_observations(
    ingress: list[float], egress: list[float], fixed_rate_mbps: float,
    bin_ms: int, seed: int
) -> None:
    """Replace observable volume with a constant-rate padded stream plus tiny noise.

    This is a deliberately idealized abstraction. Real implementations can leak
    through direction, packet sizes, connection lifecycle, congestion, and drops.
    """
    rng = random.Random(seed)
    bytes_per_bin = fixed_rate_mbps * 1_000_000.0 * (bin_ms / 1000.0) / 8.0
    # The padded stream stays established for the whole observation window,
    # including the modeled tail. Otherwise synchronized tunnel startup/shutdown
    # would dominate the score and make the experiment misleading.
    active_bins = min(len(ingress), len(egress))
    for i in range(active_bins):
        # Tiny independent perturbations avoid zero-variance series while retaining
        # the idealized constant-rate observation assumption.
        ingress[i] = bytes_per_bin * (1.0 + rng.uniform(-0.005, 0.005))
        egress[i] = bytes_per_bin * (1.0 + rng.uniform(-0.005, 0.005))


def simulate_profile(
    profile: NetworkProfile,
    config: ExperimentConfig,
    flows: list[Flow] | None = None,
) -> ExperimentResult:
    flows = generate_workload(config) if flows is None else flows
    if not flows:
        raise ValueError("workload is empty; increase duration or request_rate_per_s")

    # Separate, deterministic streams prevent the profile's hop jitter from
    # changing the actual user workload between comparisons.
    timing = _flow_timings(flows, profile, config.seed + 17)
    real_payload = sum(flow.payload_bytes for flow in flows)
    horizon_ms = config.duration_s * 1000.0 + 10_000.0
    n_bins = math.ceil(horizon_ms / config.bin_ms)
    ingress = [0.0] * n_bins
    egress = [0.0] * n_bins
    flow_rate = profile.bottleneck_mbps
    latencies: list[float] = []

    for flow, exit_start_ms, completion_ms in timing:
        _add_burst(ingress, flow.start_ms, flow.payload_bytes, flow_rate, config.bin_ms)
        _add_burst(egress, exit_start_ms, flow.payload_bytes, flow_rate, config.bin_ms)
        latencies.append(max(0.0, completion_ms - flow.start_ms))

    cover_bytes = 0.0
    fixed_rate: float | None = None
    if profile.cover_mode == "independent_noise":
        # Phase 0 isolates the effect on the attacker's observations. The noise
        # byte budget is reported, but it is not charged to hop queues yet. See
        # README limitations; phase 1 must model shared congestion explicitly.
        target_per_edge = real_payload * profile.cover_ratio_per_edge
        cover_bytes = _add_independent_noise(
            ingress, egress, target_per_edge, config, config.seed + 1009, flow_rate
        )
    elif profile.cover_mode == "fixed_rate":
        fixed_rate = profile.fixed_rate_mbps
        if fixed_rate > profile.bottleneck_mbps:
            raise ValueError(
                f"fixed rate {fixed_rate} Mbps exceeds profile bottleneck "
                f"{profile.bottleneck_mbps} Mbps"
            )
        _fixed_rate_observations(
            ingress, egress, fixed_rate, config.bin_ms, config.seed + 2017
        )
        observation_duration_s = min(len(ingress), len(egress)) * config.bin_ms / 1000.0
        total_fixed_wire_bytes = fixed_rate * 1_000_000 * observation_duration_s / 8.0
        cover_bytes = max(0.0, total_fixed_wire_bytes - real_payload)
        # In the padded-stream abstraction, a flow waits for a transmission slot
        # and is serialized at the configured fixed rate. We retain path delay and
        # use one shared FIFO to expose the performance cost of a low fixed rate.
        rng = random.Random(config.seed + 3023)
        next_available_ms = 0.0
        fixed_latencies: list[float] = []
        for flow, _, _ in timing:
            slot_wait_ms = rng.uniform(0.0, config.bin_ms)
            start_ms = max(flow.start_ms + slot_wait_ms, next_available_ms)
            service_ms = flow.payload_bytes * 8.0 / (fixed_rate * 1000.0)
            finish_ms = start_ms + service_ms
            next_available_ms = finish_ms
            path_delay_ms = max(0.0, timing[len(fixed_latencies)][1] - flow.start_ms)
            fixed_latencies.append(path_delay_ms + (finish_ms - flow.start_ms))
        latencies = fixed_latencies

    corr, lag = _max_lag_correlation(
        ingress, egress, config.bin_ms, config.max_correlation_lag_ms
    )
    offered_load_mbps = real_payload * 8.0 / (config.duration_s * 1_000_000.0)
    overhead_ratio = cover_bytes / real_payload if real_payload else 0.0

    if profile.cover_mode == "independent_noise":
        interpretation = (
            "Optimistic noise-only result; independent edge noise is an assumption, not a protocol guarantee."
        )
    elif profile.cover_mode == "fixed_rate":
        interpretation = (
            "Idealized constant-rate tunnel; correlation result excludes several real-world side channels."
        )
    elif profile.name == "direct_reference":
        interpretation = "Direct path baseline; useful for speed comparison, not an anonymity solution."
    elif profile.name == "onion_reference":
        interpretation = "Illustrative three-hop baseline; parameters are not measurements of live Tor."
    else:
        interpretation = "Hypothetical candidate; performance follows assumed link capacities and delays."

    return ExperimentResult(
        profile=profile.name,
        event_count=len(flows),
        payload_mb=real_payload / 1_000_000.0,
        offered_load_mbps=offered_load_mbps,
        bottleneck_mbps=profile.bottleneck_mbps,
        p50_latency_ms=statistics.median(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        max_lag_pearson=corr,
        correlation_lag_ms=lag,
        cover_mb=cover_bytes / 1_000_000.0,
        traffic_overhead_ratio=overhead_ratio,
        fixed_rate_mbps=fixed_rate,
        interpretation=interpretation,
    )


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[lower]
    fraction = pos - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def run_suite(
    config: ExperimentConfig,
    profiles: Iterable[NetworkProfile],
) -> list[ExperimentResult]:
    """Run profiles over the same deterministic workload for fair comparison."""
    flows = generate_workload(config)
    return [simulate_profile(profile, config, flows) for profile in profiles]
