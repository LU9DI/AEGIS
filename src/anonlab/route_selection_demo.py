"""Runnable offline route-selection demo on the synthetic topology.

This module was written against the pre-0.23 ``GeoPoint``/``is_guard`` API and
stopped importing when route selection moved to role sets with explicit client
and destination endpoints. It now renders ``demo_topology()`` through the
current planner and is exercised by ``tests/test_route_selection_demo.py`` so it
cannot silently rot again.

Nothing here contacts a relay: the topology is synthetic and the output is
planning metadata, not an anonymity, latency, or security claim.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .route_selection import demo_topology, plan_from_json

DISCLAIMER = (
    "All relay IDs and RTTs are synthetic. This is not a live network path or a "
    "claim of anonymity."
)


def run_demo() -> dict[str, Any]:
    """Return the documented JSON payload for the synthetic demo topology."""
    return {
        "metadata": {
            "project": "AEGIS",
            "version": __version__,
            "is_synthetic_demo": True,
            "is_live_network_test": False,
            "is_security_proof": False,
            "warning": DISCLAIMER,
        },
        "selection": plan_from_json(demo_topology()).to_dict(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis-route-demo",
        description="Synthetic AEGIS latency-aware route planner demo",
    )
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rendered = json.dumps(run_demo(), indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
