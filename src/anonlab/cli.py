"""CLI for the AEGIS anonymous-network research simulator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .model import ExperimentConfig
from .profiles import DEFAULT_PROFILES
from .simulator import run_suite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis",
        description="AEGIS research simulator: explore anonymous-network latency, traffic overhead, and simple timing correlation.",
    )
    parser.add_argument("--duration", type=float, default=180.0, help="workload duration in seconds (default: 180)")
    parser.add_argument("--request-rate", type=float, default=1.4, help="mean requests per second (default: 1.4)")
    parser.add_argument("--seed", type=int, default=20261009, help="deterministic random seed")
    parser.add_argument("--bin-ms", type=int, default=100, help="observation time-series bin width in ms")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = ExperimentConfig(
        duration_s=args.duration,
        request_rate_per_s=args.request_rate,
        seed=args.seed,
        bin_ms=args.bin_ms,
    )
    results = run_suite(config, DEFAULT_PROFILES)
    payload = {
        "metadata": {
            "simulator": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "is_live_network_test": False,
            "is_security_proof": False,
            "config": {
                "duration_s": config.duration_s,
                "request_rate_per_s": config.request_rate_per_s,
                "seed": config.seed,
                "bin_ms": config.bin_ms,
                "max_correlation_lag_ms": config.max_correlation_lag_ms,
            },
            "warning": "Illustrative model outputs are not measurements of Tor, a live network, or a production protocol.",
        },
        "results": [result.to_dict() for result in results],
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
