"""CLI for the THOR P2 lab.

Examples
--------
Run the full campaign (9 arms x 5 workloads, 1 warmup + 7 trials each)::

    python -m anonlab.thor_p2_lab run --output experiments/thor-p2-lab/campaign-01

Single trial, useful for debugging::

    python -m anonlab.thor_p2_lab trial --variant control --workload bulk_256k_c16k
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .. import __version__
from .campaign import DEFAULT_TRIALS, DEFAULT_WARMUPS, CampaignConfig, run_campaign
from .runner import WORKLOADS, run_trial
from .variants import VARIANTS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(output: Path, command: list[str]) -> Path:
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    manifest = {
        "schema_version": 1,
        "created_unix": __import__("time").time(),
        "command": command,
        "aegis_version": __version__,
        "python": sys.version.split()[0],
        "files": files,
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anonlab.thor_p2_lab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the interleaved paired campaign")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    run.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    run.add_argument("--seed", type=int, default=20261118)
    run.add_argument("--arms", default=",".join(VARIANTS))
    run.add_argument("--workloads", default=",".join(WORKLOADS))

    trial = sub.add_parser("trial", help="run one trial and print its JSON")
    trial.add_argument("--variant", default="control", choices=sorted(VARIANTS))
    trial.add_argument("--workload", default="bulk_256k_c16k", choices=sorted(WORKLOADS))
    trial.add_argument("--seed", type=int, default=20261118)
    trial.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    if args.command == "trial":
        result = asyncio.run(run_trial(VARIANTS[args.variant], WORKLOADS[args.workload], seed=args.seed))
        rendered = json.dumps(result.payload, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 0 if result.ok else 1

    arms = tuple(name.strip() for name in args.arms.split(",") if name.strip())
    workloads = tuple(name.strip() for name in args.workloads.split(",") if name.strip())
    config = CampaignConfig(
        arms=arms, workloads=workloads, trials=args.trials, warmups=args.warmups,
        base_seed=args.seed,
    )
    result = asyncio.run(run_campaign(config, args.output))
    manifest = _write_manifest(args.output, [sys.executable, "-m", "anonlab.thor_p2_lab", *sys.argv[1:]])
    accepted = [arm for arm, decision in result["decisions"].items() if decision["accepted"]]
    print(json.dumps({
        "output": str(args.output),
        "manifest": str(manifest),
        "duration_s": result["metadata"]["duration_s"],
        "failures": len(result["failures"]),
        "accepted": accepted,
        "decisions": result["decisions"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
