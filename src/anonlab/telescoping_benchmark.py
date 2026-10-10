"""Repeatable loopback benchmark for AEGIS telescoping circuits."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
except ImportError as exc:  # pragma: no cover - optional research dependency
    raise RuntimeError(
        "The telescoping benchmark requires: python -m pip install 'rea-anon-lab[onion-lab]'"
    ) from exc

from . import __version__
from .onion_protocol import MAX_FRAME_BYTES, frame
from .telescoping import RelayNode, TelescopingClient, read_frame, serve_node


def _raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


async def _echo_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            payload = await read_frame(reader)
            writer.write(frame(payload))
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def _direct_echo(host: str, port: int, payload: bytes) -> tuple[bytes, float]:
    started = time.perf_counter_ns()
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(frame(payload))
        await writer.drain()
        reply = await asyncio.wait_for(read_frame(reader), timeout=10)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
    return reply, (time.perf_counter_ns() - started) / 1_000_000


async def run_telescoping_benchmark(
    *, payload_bytes: int = 65_536, trials: int = 5, seed: int = 20261009
) -> dict[str, Any]:
    if not 1 <= payload_bytes <= 1_048_576:
        raise ValueError("payload_bytes must be within 1..1048576")
    if not 1 <= trials <= 100:
        raise ValueError("trials must be within 1..100")

    random = __import__("random").Random(seed)
    payload = bytes(random.randrange(256) for _ in range(payload_bytes))
    echo_server = await asyncio.start_server(_echo_handler, "127.0.0.1", 0)
    echo_port = int(echo_server.sockets[0].getsockname()[1])
    nodes: list[RelayNode] = []
    servers: list[asyncio.AbstractServer] = []
    direct_samples: list[float] = []
    build_samples: list[float] = []
    circuit_samples: list[float] = []
    goodputs: list[float] = []
    integrity = True
    direct_connections: list[int] = []

    try:
        for index in range(3):
            node = RelayNode(os.urandom(20), X25519PrivateKey.generate())
            if index == 2:
                node.allowed_destinations.add(("127.0.0.1", echo_port))
            server = await serve_node(node)
            nodes.append(node)
            servers.append(server)
        descriptors = [node.descriptor for node in nodes]

        for _ in range(trials):
            client = TelescopingClient()
            build_started = time.perf_counter_ns()
            try:
                await client.connect_guard(descriptors[0])
                await client.extend(descriptors[1])
                await client.extend(descriptors[2])
                build_samples.append((time.perf_counter_ns() - build_started) / 1_000_000)

                started = time.perf_counter_ns()
                reply = await client.request_echo("127.0.0.1", echo_port, payload)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                circuit_samples.append(elapsed_ms)
                integrity = integrity and reply == payload
                if elapsed_ms > 0:
                    goodputs.append((payload_bytes * 8) / (elapsed_ms / 1000) / 1_000_000)
                direct_reply, direct_ms = await _direct_echo("127.0.0.1", echo_port, payload)
                direct_samples.append(direct_ms)
                integrity = integrity and direct_reply == payload
                direct_connections.append(client.direct_connections_opened)
            finally:
                await client.close()

        # Count only commands the relay actually parsed, not encrypted inner bytes.
        entry_events = [(event.operation, event.target_port) for event in nodes[0].observations]
        middle_events = [(event.operation, event.target_port) for event in nodes[1].observations]
        exit_events = [(event.operation, event.target_port) for event in nodes[2].observations]
        expected_entry = [("extend", descriptors[1].port), ("forward", None), ("forward", None)] * trials
        expected_middle = [("extend", descriptors[2].port), ("forward", None)] * trials
        expected_exit = [("data", echo_port)] * trials
        route_privacy_assertion = (
            entry_events == expected_entry
            and middle_events == expected_middle
            and exit_events == expected_exit
            and echo_port not in [port for _operation, port in entry_events]
            and echo_port not in [port for _operation, port in middle_events]
        )
        return {
            "schema_version": 1,
            "metadata": {
                "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
                "version": __version__,
                "experiment": "three-hop telescoping echo path versus direct TCP echo",
                "is_loopback_only": True,
                "is_production_security_test": False,
                "seed": seed,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "warning": "Local microbenchmark only. It does not measure WAN performance or prove anonymity.",
            },
            "config": {
                "hop_count": 3,
                "payload_bytes": payload_bytes,
                "trials": trials,
                "echo_endpoint": "127.0.0.1",
                "application_destination_visible_only_to_exit_in_parsed_commands": True,
            },
            "results": {
                "integrity_verified": integrity,
                "direct_connections_from_client_per_circuit": direct_connections,
                "circuit_build_ms_p50": statistics.median(build_samples),
                "circuit_build_ms_p95": _percentile(build_samples, 0.95),
                "direct_echo_rtt_ms_p50": statistics.median(direct_samples),
                "direct_echo_rtt_ms_p95": _percentile(direct_samples, 0.95),
                "telescoping_echo_rtt_ms_p50": statistics.median(circuit_samples),
                "telescoping_echo_rtt_ms_p95": _percentile(circuit_samples, 0.95),
                "telescoping_response_goodput_mbps_median": statistics.median(goodputs),
                "parsed_command_observations": {
                    "entry": [{"operation": op, "target_port": port} for op, port in entry_events],
                    "middle": [{"operation": op, "target_port": port} for op, port in middle_events],
                    "exit": [{"operation": op, "target_port": port} for op, port in exit_events],
                },
                "route_knowledge_separation_check": route_privacy_assertion,
            },
            "limitations": [
                "All relay and echo sockets are on IPv4 loopback within one Python process.",
                "Relay-to-relay links are not mutually authenticated in this harness.",
                "The MALEBOLGE-specific KDF is experimental and unaudited.",
                "The echo endpoint is explicitly loopback-only; this is not a general-purpose proxy.",
                "Parsed-command separation does not evaluate timing, packet size, collusion, or global observation.",
                "Goodput is useful echo-response payload divided by round-trip elapsed time, not bidirectional wire throughput.",
            ],
        }
    finally:
        for server in servers:
            server.close()
        for server in servers:
            await server.wait_closed()
        echo_server.close()
        await echo_server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bytes", type=int, default=65_536, dest="payload_bytes")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_telescoping_benchmark(
        payload_bytes=args.payload_bytes, trials=args.trials, seed=args.seed
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
