#!/usr/bin/env python3
"""Capture an auditable, non-overwriting AEGIS loopback transport baseline.

This runner measures only the existing raw TCP relay benchmark. It does not
measure anonymity, encrypted transport, Internet/WAN performance, or browser
page-load performance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _run(args: argparse.Namespace) -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain")
    command = [
        sys.executable, "-m", "anonlab.local_benchmark",
        "--hops", str(args.hops),
        "--bytes", str(args.payload_bytes),
        "--trials", str(args.trials),
        "--latency-samples", str(args.latency_samples),
        "--seed", str(args.seed),
    ]
    env = os.environ.copy()
    source = str(ROOT / "src")
    env["PYTHONPATH"] = source + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    started = datetime.now(timezone.utc)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=args.timeout,
        check=False,
    )
    finished = datetime.now(timezone.utc)
    stdout_bytes = completed.stdout.encode("utf-8")
    result: dict[str, Any] = {
        "schema_version": 1,
        "runner": "scripts/run_transport_baseline.py",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "elapsed_wall_seconds": (finished - started).total_seconds(),
        "source": {
            "git_commit": commit,
            "working_tree_dirty": None if dirty is None else bool(dirty),
            "working_tree_status": dirty,
        },
        "host": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
        "stderr": completed.stderr,
        "raw_stdout": completed.stdout,
        "benchmark": None,
    }
    if completed.returncode == 0:
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            result["parse_error"] = str(exc)
            result["exit_code"] = 2
        else:
            result["benchmark"] = parsed
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hops", type=int, default=3)
    parser.add_argument("--bytes", type=int, default=4_000_000, dest="payload_bytes")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--latency-samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--timeout", type=int, default=180, help="whole benchmark timeout in seconds")
    parser.add_argument(
        "--output",
        type=Path,
        help="output JSON path; defaults to a timestamped file under experiments/baselines",
    )
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")

    result = _run(args)
    output = args.output
    if output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = (result["source"]["git_commit"] or "unknown")[:7]
        output = ROOT / "experiments" / "baselines" / f"transport-{stamp}-{suffix}.json"
    elif not output.is_absolute():
        output = ROOT / output

    # Exclusive creation prevents silently overwriting evidence from a prior run.
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError:
        print(f"Refusing to overwrite existing baseline artifact: {output}", file=sys.stderr)
        return 3

    print(json.dumps({
        "artifact": str(output),
        "exit_code": result["exit_code"],
        "git_commit": result["source"]["git_commit"],
        "working_tree_dirty": result["source"]["working_tree_dirty"],
        "stdout_sha256": result["stdout_sha256"],
        "benchmark_integrity_verified": (
            result.get("benchmark", {}).get("results", {}).get("integrity_verified")
            if result.get("benchmark") else None
        ),
        "note": "Loopback raw TCP transport only; not an anonymity, WAN, or browser benchmark.",
    }, indent=2))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
