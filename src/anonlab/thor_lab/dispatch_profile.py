"""Dispatch profiler for the AEGIS telescoping data path (THOR phase P1, Fase 1).

It answers, with measurements taken on this host, the questions the phase brief
asks for:

* how much does one command cost, in wall time and in CPU time, per byte and per
  stream;
* how many asyncio primitives (Futures, timers, locks, gathers, loop iterations)
  the real path creates per command, and what that costs at measured per-primitive
  prices;
* how much of the per-command time is cryptography and copies, and how much is
  dispatch/scheduling (the residual);
* where relay-side time goes, using the prototype's own bounded stage metrics.

It is a laboratory instrument: it builds the same loopback testbed the benchmark
uses, with three real RelayNode hops, and it never touches the network or any
production path. It also never records payloads, keys or addresses.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..onion_protocol import open_sealed, seal
from ..telescoping import RelayNode, TelescopingClient, serve_node
from .appproto import start_echo_server
from .dispatch_lab import (
    DISPATCH_VARIANTS,
    build_lab_client_class,
    count_aead_ops,
    count_primitives,
    measure_primitive_costs,
)

__all__ = ["profile_dispatch", "profile_variants", "main"]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one sample")
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _stage_summary(events: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = {}
    for event in events:
        grouped.setdefault(str(event.get("stage")), []).append(float(event.get("elapsed_ms", 0.0)))
    summary: dict[str, dict[str, float]] = {}
    for stage, values in grouped.items():
        summary[stage] = {
            "samples": len(values),
            "median_ms": statistics.median(values),
            "p95_ms": _percentile(values, 0.95),
            "total_ms": sum(values),
        }
    return summary


def _crypto_per_command_ns(chunk_bytes: int, *, repeats: int = 200) -> dict[str, float]:
    """Measure the crypto+seal work of one 3-hop command with the real primitives.

    One command in the path does, for a 3-hop circuit: 3 client-side seals, 3
    relay-side opens, 3 relay-side reply seals and 3 client-side reply opens.
    The real ``seal``/``open_sealed`` helpers are used, including their per-call
    AEAD object construction and random nonce, because that is what the path does.
    """
    payload = os.urandom(chunk_bytes)
    aad = b"MALEBOLGETHOR/request/"
    key = os.urandom(32)
    seal_samples: list[float] = []
    open_samples: list[float] = []
    envelope = seal(key, payload, aad)
    for _ in range(repeats):
        started = time.perf_counter_ns()
        seal(key, payload, aad)
        seal_samples.append(time.perf_counter_ns() - started)
    for _ in range(repeats):
        started = time.perf_counter_ns()
        open_sealed(key, envelope, aad)
        open_samples.append(time.perf_counter_ns() - started)
    seal_ns = statistics.median(seal_samples)
    open_ns = statistics.median(open_samples)
    return {
        "seal_ns": seal_ns,
        "open_ns": open_ns,
        "command_crypto_ns": 6 * seal_ns + 6 * open_ns,
        "payload_bytes": chunk_bytes,
    }


@dataclass(slots=True)
class _Testbed:
    echo: Any
    nodes: list[RelayNode]
    servers: list[asyncio.AbstractServer]

    async def close(self) -> None:
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        await self.echo.close()


async def build_testbed(*, collect_relay_metrics: bool) -> _Testbed:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey  # noqa: PLC0415

    echo = await start_echo_server()
    nodes: list[RelayNode] = []
    servers: list[asyncio.AbstractServer] = []
    for _ in range(3):
        node = RelayNode(
            identity_digest=os.urandom(20),
            onion_private_key=X25519PrivateKey.generate(),
            collect_relay_metrics=collect_relay_metrics,
        )
        servers.append(await serve_node(node))
        nodes.append(node)
    nodes[-1].allowed_destinations.add((echo.host, echo.port))
    return _Testbed(echo=echo, nodes=nodes, servers=servers)


def _client_class() -> type:
    return build_lab_client_class(TelescopingClient)


async def profile_dispatch(
    *,
    variant: str = "control",
    chunk_bytes: int = 64 * 1024,
    commands: int = 128,
    streams: int = 1,
    batch_size: int = 4,
    collect_relay_metrics: bool = True,
    with_counters: bool = True,
    transfer_timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Run one instrumented transfer and return a per-command cost breakdown.

    Commands are issued through ``write_pipelined`` with ``batch_size`` commands
    per call, which is how the benchmark drives bulk transfers. A batch of one
    would make the ``io_batch`` variant a no-op by construction.
    """
    if variant not in DISPATCH_VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    if not 4 * 1024 <= chunk_bytes <= 256 * 1024:
        raise ValueError("chunk_bytes must be within 4 KiB..256 KiB")
    if not 1 <= commands <= 4096:
        raise ValueError("commands must be within 1..4096")
    if not 1 <= streams <= 32:
        raise ValueError("streams must be within 1..32")
    if not 1 <= batch_size <= 4:
        raise ValueError("batch_size must be within 1..4 (prototype admission limit)")

    testbed = await build_testbed(collect_relay_metrics=collect_relay_metrics)
    client_class = _client_class()
    client = client_class(
        dispatch_variant=variant,
        max_active_streams=max(8, streams),
        collect_write_metrics=True,
    )
    counters_holder: Any = None
    try:
        descriptors = [node.descriptor for node in testbed.nodes]
        await client.connect_guard(descriptors[0])
        await client.extend(descriptors[1])
        await client.extend(descriptors[2])
        duplex_streams = [
            await client.open_stream(testbed.echo.host, testbed.echo.port) for _ in range(streams)
        ]
        per_stream_commands = max(1, commands // streams)
        payload = os.urandom(chunk_bytes)

        async def one_stream(stream: Any) -> dict[str, float]:
            batches = max(1, per_stream_commands // batch_size)
            block = payload * batch_size
            block_bytes = len(block)
            sent = batches * block_bytes
            received = 0
            started = time.perf_counter_ns()

            async def writer() -> None:
                for _ in range(batches):
                    await stream.write_pipelined(
                        block, chunk_bytes=chunk_bytes, max_in_flight=batch_size
                    )
                await stream.write_eof()

            async def reader() -> None:
                nonlocal received
                while received < sent:
                    chunk = await stream.read_chunk()
                    if not chunk:
                        return
                    received += len(chunk)

            # Duplex streams are bounded by a read-credit window: writing the whole
            # payload before reading can deadlock once the exit stalls on exhausted
            # credit. The benchmark workloads do the same thing, which is why this
            # profiler drives writer and reader concurrently.
            await asyncio.gather(writer(), reader())
            elapsed_ns = time.perf_counter_ns() - started
            return {"elapsed_ns": elapsed_ns, "received": received, "sent": sent}

        context = count_primitives() if with_counters else None
        if context is not None:
            counters = context.__enter__()
            counters_holder = counters
        aead_context = count_aead_ops()
        aead_stats = aead_context.__enter__()
        try:
            wall_started = time.perf_counter_ns()
            cpu_started = time.process_time_ns()
            results = await asyncio.wait_for(
                asyncio.gather(*(one_stream(stream) for stream in duplex_streams)),
                timeout=transfer_timeout_s,
            )
            wall_ns = time.perf_counter_ns() - wall_started
            cpu_ns = time.process_time_ns() - cpu_started
        finally:
            aead_context.__exit__(None, None, None)
            if context is not None:
                context.__exit__(None, None, None)

        for stream in duplex_streams:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(stream.close(), timeout=10)

        batches_per_stream = max(1, per_stream_commands // batch_size)
        total_commands = batches_per_stream * batch_size * streams
        payload_bytes = received_total = sum(int(result["received"]) for result in results)
        relay_events: list[dict[str, Any]] = []
        if collect_relay_metrics:
            for node in testbed.nodes:
                relay_events.extend(node.relay_metrics_snapshot().get("events", []))
        client_metrics = client.write_metrics_snapshot()
        primitive_costs = await measure_primitive_costs(repeats=500)
        crypto = _crypto_per_command_ns(chunk_bytes, repeats=200)

        counters_dict = counters_holder.to_dict() if counters_holder is not None else {}
        per_command = {
            name: (value / total_commands if total_commands else None)
            for name, value in counters_dict.items()
        }
        counters_ns = 0.0
        if counters_dict:
            counters_ns = (
                counters_dict.get("futures_created", 0) * primitive_costs.future_create_ns
                + counters_dict.get("wait_for_calls", 0) * primitive_costs.wait_for_arm_disarm_ns
                + counters_dict.get("gather_calls", 0) * primitive_costs.gather_two_futures_ns
                + counters_dict.get("lock_acquires", 0) * primitive_costs.lock_acquire_ns
            )
        wall_per_command_ns = wall_ns / total_commands
        residual_ns = wall_per_command_ns - crypto["command_crypto_ns"] - counters_ns / max(1, total_commands)
        return {
            "schema_version": 1,
            "kind": "thor_dispatch_profile",
            "variant": DISPATCH_VARIANTS[variant].to_dict(),
            "config": {
                "chunk_bytes": chunk_bytes,
                "commands": total_commands,
                "commands_per_stream": per_stream_commands,
                "batch_size": batch_size,
                "streams": streams,
                "collect_relay_metrics": collect_relay_metrics,
                "with_counters": with_counters,
            },
            "result": {
                "wall_ms": wall_ns / 1e6,
                "cpu_ms": cpu_ns / 1e6,
                "goodput_mbps": (payload_bytes * 8) / (wall_ns / 1e9) / 1e6 if wall_ns else None,
                "payload_bytes": payload_bytes,
                "received_bytes": received_total,
                "integrity": received_total == payload_bytes,
                "wall_per_command_us": wall_per_command_ns / 1000,
                "cpu_per_command_us": (cpu_ns / total_commands) / 1000,
                "wall_per_byte_ns": wall_ns / payload_bytes if payload_bytes else None,
                "cpu_fraction_of_one_core": cpu_ns / wall_ns if wall_ns else None,
            },
            "primitive_counters": counters_dict,
            "primitive_counters_per_command": per_command,
            "primitive_costs": primitive_costs.to_dict(),
            "crypto": crypto,
            "aead_measured": {
                "seal_calls_per_command": aead_stats["seal_calls"] / total_commands,
                "open_calls_per_command": aead_stats["open_calls"] / total_commands,
                "ns_per_command": (aead_stats["seal_ns"] + aead_stats["open_ns"]) / total_commands,
                "share_of_wall": (
                    (aead_stats["seal_ns"] + aead_stats["open_ns"]) / wall_ns if wall_ns else None
                ),
                "share_of_cpu": (
                    (aead_stats["seal_ns"] + aead_stats["open_ns"]) / cpu_ns if cpu_ns else None
                ),
            },
            "attribution_ns_per_command": {
                "crypto_estimate": crypto["command_crypto_ns"],
                "aead_measured": (aead_stats["seal_ns"] + aead_stats["open_ns"]) / total_commands,
                "asyncio_primitives": counters_ns / max(1, total_commands),
                "residual_after_measured_aead": (
                    wall_per_command_ns
                    - (aead_stats["seal_ns"] + aead_stats["open_ns"]) / total_commands
                    - counters_ns / max(1, total_commands)
                ),
                "residual_dispatch_and_io": residual_ns,
            },
            "client_write_metrics": client_metrics.get("summary_by_event", {}),
            "relay_stage_summary": _stage_summary(relay_events),
            "relay_event_count": len(relay_events),
            "notes": (
                "Loopback testbed with three real relay hops in one process. CPU is process-wide and "
                "includes the relays. The crypto estimate uses the real seal/open helpers. The "
                "residual is dispatch, event-loop scheduling, socket I/O and relay-side bookkeeping "
                "that is not represented by the measured primitives."
            ),
        }
    finally:
        try:
            await asyncio.wait_for(client.close(), timeout=15)
        except Exception:  # noqa: BLE001 - teardown must not hide the profile
            pass
        with contextlib.suppress(Exception):
            await asyncio.wait_for(testbed.close(), timeout=15)


async def profile_variants(
    *,
    variants: list[str],
    chunk_bytes: int,
    commands: int,
    streams: int,
    repeats: int,
    batch_size: int = 4,
    transfer_timeout_s: float = 180.0,
) -> dict[str, Any]:
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be within 1..20")
    runs: list[dict[str, Any]] = []
    for variant in variants:
        for _ in range(repeats):
            runs.append(
                await profile_dispatch(
                    variant=variant,
                    chunk_bytes=chunk_bytes,
                    commands=commands,
                    streams=streams,
                    batch_size=batch_size,
                    transfer_timeout_s=transfer_timeout_s,
                )
            )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(str(run["variant"]["variant"]), []).append(run)
    summary: dict[str, Any] = {}
    for variant, entries in grouped.items():
        summary[variant] = {
            "runs": len(entries),
            "goodput_mbps_median": statistics.median(
                float(entry["result"]["goodput_mbps"]) for entry in entries
            ),
            "wall_per_command_us_median": statistics.median(
                float(entry["result"]["wall_per_command_us"]) for entry in entries
            ),
            "cpu_per_command_us_median": statistics.median(
                float(entry["result"]["cpu_per_command_us"]) for entry in entries
            ),
            "crypto_ns_per_command": entries[0]["attribution_ns_per_command"]["crypto_estimate"],
            "aead_measured_ns_per_command_median": statistics.median(
                float(entry["aead_measured"]["ns_per_command"]) for entry in entries
            ),
            "aead_share_of_wall_median": statistics.median(
                float(entry["aead_measured"]["share_of_wall"] or 0.0) for entry in entries
            ),
            "residual_ns_per_command_median": statistics.median(
                float(entry["attribution_ns_per_command"]["residual_dispatch_and_io"])
                for entry in entries
            ),
            "integrity": all(bool(entry["result"]["integrity"]) for entry in entries),
            "counters_per_command": entries[0]["primitive_counters_per_command"],
        }
    return {
        "schema_version": 1,
        "kind": "thor_dispatch_profile_suite",
        "config": {
            "variants": variants,
            "chunk_bytes": chunk_bytes,
            "commands": commands,
            "streams": streams,
            "batch_size": batch_size,
            "repeats": repeats,
        },
        "summary": summary,
        "runs": runs,
        "notes": "Loopback only; see per-run notes for the attribution caveats.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS dispatch profiler (lab only)")
    parser.add_argument("--variants", default="control,io_batch,lean_dispatch,combined")
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024)
    parser.add_argument("--commands", type=int, default=128)
    parser.add_argument("--streams", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=4, help="commands per write_pipelined call (1..4)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    result = asyncio.run(
        profile_variants(
            variants=[item.strip() for item in args.variants.split(",") if item.strip()],
            chunk_bytes=args.chunk_bytes,
            commands=args.commands,
            streams=args.streams,
            repeats=args.repeats,
            batch_size=args.batch_size,
        )
    )
    rendered = json.dumps(result, indent=2)
    print(rendered if args.output is None else json.dumps(result["summary"], indent=2))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
