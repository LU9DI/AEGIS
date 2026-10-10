"""Profile the loopback duplex circuit hot path with cProfile.

Profiler timings include instrumentation overhead and are not throughput claims.
The benchmark sends synthetic bytes only and records aggregate function timings,
not application payloads.
"""
from __future__ import annotations

import argparse
import asyncio
import cProfile
import json
import pstats
import platform
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from . import __version__
from .duplex_benchmark import run_duplex_benchmark

_PROFILE_FUNCTIONS = {
    "descriptor",
    "__post_init__",
    "_ensure_loopback",
    "ip_address",
    "seal",
    "open_sealed",
    "handle",
    "forward_duplex_command",
    "downstream_response_dispatcher",
    "_send_duplex_command",
    "_send_duplex_write_batch",
    "read_frame",
    "_accept_event",
    "_grant_credit",
    "drain",
    "_drain_helper",
}


def _profiled_functions(profile: cProfile.Profile) -> list[dict[str, Any]]:
    stats = pstats.Stats(profile)
    functions: list[dict[str, Any]] = []
    for (filename, line, function), (primitive_calls, calls, self_s, cumulative_s, _callers) in stats.stats.items():
        if function not in _PROFILE_FUNCTIONS:
            continue
        functions.append({
            "file": filename,
            "line": line,
            "function": function,
            "primitive_calls": primitive_calls,
            "calls": calls,
            "self_seconds": self_s,
            "cumulative_seconds": cumulative_s,
        })
    return sorted(functions, key=lambda item: (item["function"], item["file"], item["line"]))


async def _run_profiled(args: argparse.Namespace) -> dict[str, Any]:
    profile = cProfile.Profile()
    profile.enable()
    result = await run_duplex_benchmark(
        stream_count=args.streams,
        payload_bytes=args.payload_bytes,
        seed=args.seed,
        write_chunk_bytes=args.write_chunk_bytes,
        pipeline_depth=args.pipeline_depth,
    )
    profile.disable()

    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    profile.dump_stats(str(prefix) + ".prof")
    text_buffer = StringIO()
    pstats.Stats(profile, stream=text_buffer).sort_stats("cumulative").print_stats(80)
    Path(str(prefix) + ".txt").write_text(text_buffer.getvalue(), encoding="utf-8")

    payload = {
        "schema_version": 1,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "cProfile of loopback-only full-duplex circuit workload",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "is_loopback_only": True,
            "is_security_proof": False,
            "warning": "cProfile adds overhead; profiled wall-time and throughput values are not comparable with unprofiled benchmark results. Use function call/time summaries to locate hot paths.",
        },
        "config": {
            "streams": args.streams,
            "payload_bytes_per_stream": args.payload_bytes,
            "write_chunk_bytes": args.write_chunk_bytes,
            "pipeline_depth": args.pipeline_depth,
            "seed": args.seed,
        },
        "benchmarked_results_with_profiler_overhead": result["results"],
        "profiled_functions": _profiled_functions(profile),
    }
    Path(str(prefix) + ".json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile AEGIS's loopback relay hot path with cProfile")
    parser.add_argument("--streams", type=int, default=8)
    parser.add_argument("--payload-bytes", type=int, default=256 * 1024)
    parser.add_argument("--write-chunk-bytes", type=int, default=256 * 1024)
    parser.add_argument("--pipeline-depth", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--output-prefix", type=Path, default=Path("experiments/hotpath-profile"))
    args = parser.parse_args()
    payload = asyncio.run(_run_profiled(args))
    print(json.dumps({
        "version": payload["metadata"]["version"],
        "profiled_functions": len(payload["profiled_functions"]),
        "profile_files": [str(args.output_prefix) + suffix for suffix in (".prof", ".txt", ".json")],
        "warning": payload["metadata"]["warning"],
    }, indent=2))


if __name__ == "__main__":
    main()
