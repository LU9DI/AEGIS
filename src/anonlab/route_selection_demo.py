"""Run the synthetic AEGIS latency-aware route-selection demonstration."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random

from . import __version__
from .route_selection import GeoPoint, RelayCandidate, RoutePolicy, select_route


def build_demo_inputs():
    relays = [
        RelayCandidate("guard-br", is_guard=True, is_middle=True, bandwidth_mbps=80, operator_id="op-a", asn="AS64501", subnet_group="net-a", family_ids=frozenset({"family-a"}), geo=GeoPoint(-23.55, -46.63)),
        RelayCandidate("guard-uy", is_guard=True, is_middle=True, bandwidth_mbps=65, operator_id="op-d", asn="AS64504", subnet_group="net-d", geo=GeoPoint(-34.90, -56.16)),
        RelayCandidate("middle-br", is_middle=True, bandwidth_mbps=90, operator_id="op-b", asn="AS64502", subnet_group="net-b", family_ids=frozenset({"family-b"}), geo=GeoPoint(-22.91, -43.20)),
        RelayCandidate("middle-us", is_middle=True, bandwidth_mbps=100, operator_id="op-e", asn="AS64505", subnet_group="net-e", geo=GeoPoint(25.76, -80.19)),
        RelayCandidate("exit-br", is_exit=True, is_middle=True, bandwidth_mbps=70, operator_id="op-c", asn="AS64503", subnet_group="net-c", family_ids=frozenset({"family-c"}), geo=GeoPoint(-23.55, -46.63)),
        RelayCandidate("exit-us", is_exit=True, is_middle=True, bandwidth_mbps=110, operator_id="op-f", asn="AS64506", subnet_group="net-f", geo=GeoPoint(40.71, -74.01)),
    ]
    # Synthetic measurements, not measurements of public relays or actual routes.
    rtt = {
        ("client", "guard-br"): 8.0, ("client", "guard-uy"): 35.0,
        ("guard-br", "middle-br"): 9.0, ("guard-br", "middle-us"): 115.0,
        ("guard-uy", "middle-br"): 31.0, ("guard-uy", "middle-us"): 165.0,
        ("middle-br", "exit-br"): 8.0, ("middle-br", "exit-us"): 130.0,
        ("middle-us", "exit-br"): 125.0, ("middle-us", "exit-us"): 24.0,
        ("exit-br", "destination"): 7.0, ("exit-us", "destination"): 95.0,
    }
    return relays, rtt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-route-demo", description="Synthetic AEGIS latency-aware route planner demo")
    parser.add_argument("--seed", type=int, default=None, help="optional reproducible demo seed; not for security decisions")
    parser.add_argument("--latency-slack-ms", type=float, default=20.0, help="randomization budget above the lowest-RTT eligible route")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    relays, edge_rtt = build_demo_inputs()
    rng = random.Random(args.seed) if args.seed is not None else None
    selection = select_route(
        relays, edge_rtt,
        policy=RoutePolicy(latency_slack_ms=args.latency_slack_ms),
        rng=rng,
    )
    payload = {
        "metadata": {
            "project": "AEGIS",
            "version": __version__,
            "is_synthetic_demo": True,
            "is_live_network_test": False,
            "is_security_proof": False,
            "warning": "All relay IDs and RTTs are synthetic. This is not a live network path or a claim of anonymity.",
        },
        "selection": {
            "roles": ["guard", "middle", "exit"],
            "relay_ids": list(selection.relay_ids),
            "estimated_path_rtt_ms": selection.estimated_path_rtt_ms,
            "fastest_eligible_rtt_ms": selection.fastest_eligible_rtt_ms,
            "eligible_path_count": selection.eligible_path_count,
            "near_optimal_path_count": selection.near_optimal_path_count,
            "measurement_coverage": selection.measurement_coverage,
            "latency_source": selection.latency_source,
            "destination_anchor_disclosed_to_relays": False,
        },
    }
    rendered = json.dumps(payload, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
