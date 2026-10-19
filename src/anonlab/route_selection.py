"""Experimental route scoring using measured RTTs, geometry bounds, and diversity.

This selector is an offline planner. It does not obtain trustworthy relay data,
prove a route's anonymity, or send coordinates to relays. Endpoint coordinates
are input to the local process only and are deliberately omitted from output.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import itertools
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import __version__

_ROLES = frozenset({"guard", "middle", "exit"})
_FIBRE_KM_PER_MS = 200.0  # approximate propagation speed in fibre, not a route prediction


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True, slots=True)
class Endpoint:
    endpoint_id: str
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not self.endpoint_id or not isinstance(self.endpoint_id, str):
            raise ValueError("endpoint_id must be a non-empty string")
        lat = _finite_number(self.latitude, "latitude")
        lon = _finite_number(self.longitude, "longitude")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("endpoint coordinates are out of range")
        object.__setattr__(self, "latitude", lat)
        object.__setattr__(self, "longitude", lon)


@dataclass(frozen=True, slots=True)
class RelayCandidate:
    relay_id: str
    roles: frozenset[str]
    latitude: float
    longitude: float
    bandwidth_mbps: float
    asn_group: str
    family_id: str
    subnet_group: str
    country_code: str
    utilization: float = 0.0
    failure_rate: float = 0.0
    running: bool = True
    confirmed_guard: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.relay_id, str) or not self.relay_id.strip():
            raise ValueError("relay_id must be non-empty")
        roles = frozenset(self.roles)
        if not roles or not roles <= _ROLES:
            raise ValueError("roles must contain only guard, middle, and/or exit")
        object.__setattr__(self, "roles", roles)
        lat = _finite_number(self.latitude, "latitude")
        lon = _finite_number(self.longitude, "longitude")
        bw = _finite_number(self.bandwidth_mbps, "bandwidth_mbps")
        util = _finite_number(self.utilization, "utilization")
        fail = _finite_number(self.failure_rate, "failure_rate")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("relay coordinates are out of range")
        if bw <= 0:
            raise ValueError("bandwidth_mbps must be > 0")
        if not 0 <= util <= 1 or not 0 <= fail <= 1:
            raise ValueError("utilization and failure_rate must be within [0, 1]")
        for name in ("asn_group", "family_id", "subnet_group", "country_code"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        object.__setattr__(self, "latitude", lat)
        object.__setattr__(self, "longitude", lon)
        object.__setattr__(self, "bandwidth_mbps", bw)
        object.__setattr__(self, "utilization", util)
        object.__setattr__(self, "failure_rate", fail)


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    pinned_guard_id: str
    min_bandwidth_mbps: float = 1.0
    max_same_asn: int = 1
    max_same_family: int = 1
    max_same_subnet: int = 1
    max_same_country: int = 3
    unknown_link_penalty_ms: float = 12.0
    geometry_multiplier: float = 2.5
    load_penalty_ms: float = 10.0
    bandwidth_penalty_ms_mbps: float = 15.0
    failure_penalty_ms: float = 20.0
    max_score_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.pinned_guard_id:
            raise ValueError("pinned_guard_id is required; do not rotate entry guards per circuit")
        for name in ("min_bandwidth_mbps", "unknown_link_penalty_ms", "geometry_multiplier", "load_penalty_ms", "bandwidth_penalty_ms_mbps", "failure_penalty_ms"):
            val = _finite_number(getattr(self, name), name)
            if val < 0 or (name == "min_bandwidth_mbps" and val == 0):
                raise ValueError(f"{name} is outside its valid range")
            object.__setattr__(self, name, val)
        for name in ("max_same_asn", "max_same_family", "max_same_subnet", "max_same_country"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        if self.max_score_ms is not None:
            cap = _finite_number(self.max_score_ms, "max_score_ms")
            if cap <= 0:
                raise ValueError("max_score_ms must be > 0")
            object.__setattr__(self, "max_score_ms", cap)


@dataclass(frozen=True, slots=True)
class RoutePlan:
    relay_ids: tuple[str, str, str]
    score_ms: float
    estimated_rtt_ms: float
    geometric_rtt_floor_ms: float
    bottleneck_mbps: float
    measured_link_count: int
    estimated_link_count: int
    warning: str = (
        "Offline heuristic only; geometry is a propagation lower bound, not a ping guarantee. "
        "No zero-knowledge proof or anonymity guarantee is provided."
    )

    def to_dict(self) -> dict[str, Any]:
        # Intentionally omit endpoint coordinates, destination identity, and raw link records.
        return {
            "relays": list(self.relay_ids),
            "score_ms": round(self.score_ms, 3),
            "estimated_rtt_ms": round(self.estimated_rtt_ms, 3),
            "geometric_rtt_floor_ms": round(self.geometric_rtt_floor_ms, 3),
            "bottleneck_mbps": round(self.bottleneck_mbps, 3),
            "measured_link_count": self.measured_link_count,
            "estimated_link_count": self.estimated_link_count,
            "uses_zero_knowledge_proofs": False,
            "is_live_network_test": False,
            "warning": self.warning,
        }


def great_circle_km(a: Endpoint | RelayCandidate, b: Endpoint | RelayCandidate) -> float:
    """Haversine distance in km; used only for an optimistic physical bound."""
    lat1, lon1 = math.radians(a.latitude), math.radians(a.longitude)
    lat2, lon2 = math.radians(b.latitude), math.radians(b.longitude)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def geometric_rtt_floor_ms(a: Endpoint | RelayCandidate, b: Endpoint | RelayCandidate) -> float:
    """Theoretical RTT floor assuming propagation in fibre near 200 km/ms."""
    return (great_circle_km(a, b) / _FIBRE_KM_PER_MS) * 2


def _link_metric(
    source: Endpoint | RelayCandidate,
    target: Endpoint | RelayCandidate,
    measurements: Mapping[tuple[str, str], float],
    policy: RoutePolicy,
) -> tuple[float, float, bool]:
    direct = measurements.get((source.endpoint_id if isinstance(source, Endpoint) else source.relay_id,
                              target.endpoint_id if isinstance(target, Endpoint) else target.relay_id))
    reverse = measurements.get((target.endpoint_id if isinstance(target, Endpoint) else target.relay_id,
                                source.endpoint_id if isinstance(source, Endpoint) else source.relay_id))
    if direct is not None or reverse is not None:
        measured = _finite_number(direct if direct is not None else reverse, "link RTT")
        if measured < 0:
            raise ValueError("link RTT must be >= 0")
        return measured, geometric_rtt_floor_ms(source, target), True
    floor = geometric_rtt_floor_ms(source, target)
    estimate = floor * policy.geometry_multiplier + policy.unknown_link_penalty_ms
    return estimate, floor, False


def _counts_within(items: Sequence[RelayCandidate], field: str, limit: int) -> bool:
    counts: dict[str, int] = {}
    for node in items:
        key = getattr(node, field)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > limit:
            return False
    return True


def select_route(
    *,
    candidates: Sequence[RelayCandidate],
    client: Endpoint,
    destination: Endpoint,
    link_rtts_ms: Mapping[tuple[str, str], float] | None,
    policy: RoutePolicy,
) -> RoutePlan:
    """Select a three-hop guard/middle/exit path while preserving a pinned guard.

    Measured per-link RTT is preferred. Geometry only fills missing measurements
    with a conservative penalty. ASN/family/subnet diversity are hard constraints.
    The result is local planning metadata, not a zero-knowledge route proof.
    """
    ids = [node.relay_id for node in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("relay IDs must be unique")
    if client.endpoint_id == destination.endpoint_id or any(n.relay_id in {client.endpoint_id, destination.endpoint_id} for n in candidates):
        raise ValueError("endpoint IDs must be distinct from relay IDs")
    links = link_rtts_ms or {}
    for key, value in links.items():
        if not isinstance(key, tuple) or len(key) != 2 or not all(isinstance(part, str) and part for part in key):
            raise ValueError("link measurement keys must be (source_id, target_id) tuples")
        number = _finite_number(value, "link RTT")
        if number < 0:
            raise ValueError("link RTT must be >= 0")
    usable = [n for n in candidates if n.running and n.bandwidth_mbps >= policy.min_bandwidth_mbps]
    guard_matches = [n for n in usable if n.relay_id == policy.pinned_guard_id and "guard" in n.roles and n.confirmed_guard]
    if not guard_matches:
        raise ValueError("pinned confirmed guard is missing or unusable; no automatic guard rotation is performed")
    guard = guard_matches[0]
    middles = [n for n in usable if n.relay_id != guard.relay_id and "middle" in n.roles]
    exits = [n for n in usable if n.relay_id not in {guard.relay_id} and "exit" in n.roles]
    plans: list[RoutePlan] = []
    for middle, exit_node in itertools.product(middles, exits):
        path = (guard, middle, exit_node)
        if len({n.relay_id for n in path}) != 3:
            continue
        if not _counts_within(path, "asn_group", policy.max_same_asn):
            continue
        if not _counts_within(path, "family_id", policy.max_same_family):
            continue
        if not _counts_within(path, "subnet_group", policy.max_same_subnet):
            continue
        if not _counts_within(path, "country_code", policy.max_same_country):
            continue
        sequence: tuple[Endpoint | RelayCandidate, ...] = (client, guard, middle, exit_node, destination)
        estimated = floor = 0.0
        measured_n = estimated_n = 0
        for a, b in zip(sequence, sequence[1:]):
            link_estimate, geo_floor, is_measured = _link_metric(a, b, links, policy)
            estimated += link_estimate
            floor += geo_floor
            if is_measured:
                measured_n += 1
            else:
                estimated_n += 1
        bottleneck = min(n.bandwidth_mbps for n in path)
        load = sum(n.utilization * n.utilization * policy.load_penalty_ms for n in path)
        reliability = sum(n.failure_rate * policy.failure_penalty_ms for n in path)
        bandwidth_penalty = policy.bandwidth_penalty_ms_mbps / bottleneck
        score = estimated + load + reliability + bandwidth_penalty
        if policy.max_score_ms is not None and score > policy.max_score_ms:
            continue
        plans.append(RoutePlan(
            relay_ids=(guard.relay_id, middle.relay_id, exit_node.relay_id),
            score_ms=score,
            estimated_rtt_ms=estimated,
            geometric_rtt_floor_ms=floor,
            bottleneck_mbps=bottleneck,
            measured_link_count=measured_n,
            estimated_link_count=estimated_n,
        ))
    if not plans:
        raise ValueError("no route satisfies the pinned-guard, capacity, and diversity constraints")
    plans.sort(key=lambda p: (p.score_ms, p.relay_ids))
    return plans[0]


def _node_from_json(raw: Mapping[str, Any]) -> RelayCandidate:
    return RelayCandidate(
        relay_id=str(raw["relay_id"]), roles=frozenset(raw["roles"]),
        latitude=raw["latitude"], longitude=raw["longitude"],
        bandwidth_mbps=raw["bandwidth_mbps"], asn_group=str(raw["asn_group"]),
        family_id=str(raw["family_id"]), subnet_group=str(raw["subnet_group"]),
        country_code=str(raw["country_code"]), utilization=raw.get("utilization", 0.0),
        failure_rate=raw.get("failure_rate", 0.0), running=raw.get("running", True),
        confirmed_guard=raw.get("confirmed_guard", False),
    )


def plan_from_json(raw: Mapping[str, Any]) -> RoutePlan:
    try:
        client_raw, dest_raw = raw["client"], raw["destination"]
        client = Endpoint(str(client_raw["id"]), client_raw["latitude"], client_raw["longitude"])
        destination = Endpoint(str(dest_raw["id"]), dest_raw["latitude"], dest_raw["longitude"])
        candidates = [_node_from_json(item) for item in raw["relays"]]
        links = {
            (str(item["source"]), str(item["target"])): item["rtt_ms"]
            for item in raw.get("link_rtts_ms", [])
        }
        policy_fields = raw.get("policy", {})
        policy = RoutePolicy(pinned_guard_id=str(raw["pinned_guard_id"]), **policy_fields)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid route topology schema: missing or invalid {exc}") from exc
    return select_route(candidates=candidates, client=client, destination=destination, link_rtts_ms=links, policy=policy)


def demo_topology() -> dict[str, Any]:
    """Synthetic topology for a quick, explicitly non-live smoke test."""
    return {
        "client": {"id": "client-local", "latitude": -23.5505, "longitude": -46.6333},
        "destination": {"id": "destination-local", "latitude": -23.5617, "longitude": -46.6559},
        "pinned_guard_id": "guard-pinned-sp",
        "relays": [
            {"relay_id": "guard-pinned-sp", "roles": ["guard"], "latitude": -23.55, "longitude": -46.63, "bandwidth_mbps": 50, "asn_group": "asn-1", "family_id": "family-1", "subnet_group": "subnet-1", "country_code": "BR", "utilization": 0.25, "confirmed_guard": True},
            {"relay_id": "middle-sp", "roles": ["middle"], "latitude": -23.56, "longitude": -46.64, "bandwidth_mbps": 80, "asn_group": "asn-2", "family_id": "family-2", "subnet_group": "subnet-2", "country_code": "BR", "utilization": 0.15},
            {"relay_id": "middle-rj", "roles": ["middle"], "latitude": -22.90, "longitude": -43.20, "bandwidth_mbps": 150, "asn_group": "asn-3", "family_id": "family-3", "subnet_group": "subnet-3", "country_code": "BR", "utilization": 0.1},
            {"relay_id": "middle-eu", "roles": ["middle"], "latitude": 50.11, "longitude": 8.68, "bandwidth_mbps": 250, "asn_group": "asn-4", "family_id": "family-4", "subnet_group": "subnet-4", "country_code": "DE", "utilization": 0.45},
            {"relay_id": "exit-sp", "roles": ["exit"], "latitude": -23.55, "longitude": -46.64, "bandwidth_mbps": 40, "asn_group": "asn-5", "family_id": "family-5", "subnet_group": "subnet-5", "country_code": "BR", "utilization": 0.2},
            {"relay_id": "exit-usa", "roles": ["exit"], "latitude": 40.71, "longitude": -74.00, "bandwidth_mbps": 300, "asn_group": "asn-6", "family_id": "family-6", "subnet_group": "subnet-6", "country_code": "US", "utilization": 0.05},
        ],
        "link_rtts_ms": [
            {"source": "client-local", "target": "guard-pinned-sp", "rtt_ms": 4.2},
            {"source": "guard-pinned-sp", "target": "middle-sp", "rtt_ms": 1.5},
            {"source": "middle-sp", "target": "exit-sp", "rtt_ms": 1.7},
            {"source": "exit-sp", "target": "destination-local", "rtt_ms": 3.1},
            {"source": "guard-pinned-sp", "target": "middle-rj", "rtt_ms": 18.0},
            {"source": "middle-rj", "target": "exit-sp", "rtt_ms": 17.0},
            {"source": "middle-sp", "target": "exit-usa", "rtt_ms": 135.0},
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS offline route scoring (not a live anonymity route)")
    parser.add_argument("--input", type=Path, help="JSON topology file; omitting it runs a synthetic demo")
    parser.add_argument("--output", type=Path, help="write plan JSON to this path instead of stdout")
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8")) if args.input else demo_topology()
        result = plan_from_json(raw).to_dict()
        result["metadata"] = {"component": "AEGIS route scoring", "version": __version__, "input_source": "json" if args.input else "synthetic_demo"}
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
