"""Local-only concurrent circuit benchmark for AEGIS."""
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
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
except ImportError as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "The concurrency benchmark requires: python -m pip install 'rea-anon-lab[onion-lab]'"
    ) from exc

from . import __version__
from .onion_protocol import frame
from .telescoping import (
    DEFAULT_MAX_ACTIVE_CONNECTIONS,
    RelayNode,
    TelescopingClient,
    read_frame,
    serve_node,
)
from .telescoping_benchmark import _percentile


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


async def _request_direct(host: str, port: int, payload: bytes) -> float:
    started = time.perf_counter_ns()
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(frame(payload))
        await writer.drain()
        response = await asyncio.wait_for(read_frame(reader), timeout=10)
        if response != payload:
            raise AssertionError("direct echo integrity mismatch")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
    return (time.perf_counter_ns() - started) / 1_000_000


async def run_concurrency_benchmark(
    *, clients_count: int = 8, payload_bytes: int = 65_536, seed: int = 20261009
) -> dict[str, Any]:
    """Run independent circuits concurrently; all sockets remain IPv4 loopback."""
    if not isinstance(clients_count, int) or isinstance(clients_count, bool) or not 1 <= clients_count <= DEFAULT_MAX_ACTIVE_CONNECTIONS:
        raise ValueError(f"clients_count must be within 1..{DEFAULT_MAX_ACTIVE_CONNECTIONS}")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1 <= payload_bytes <= 1_048_576:
        raise ValueError("payload_bytes must be within 1..1048576")

    prng = __import__("random").Random(seed)
    payloads = [bytes(prng.randrange(256) for _ in range(payload_bytes)) for _ in range(clients_count)]
    echo_server = await asyncio.start_server(_echo_handler, "127.0.0.1", 0)
    echo_port = int(echo_server.sockets[0].getsockname()[1])
    nodes: list[RelayNode] = []
    servers: list[asyncio.AbstractServer] = []
    clients = [TelescopingClient() for _ in range(clients_count)]
    try:
        for index in range(3):
            node = RelayNode(os.urandom(20), X25519PrivateKey.generate())
            if index == 2:
                node.allowed_destinations.add(("127.0.0.1", echo_port))
            server = await serve_node(node)
            nodes.append(node)
            servers.append(server)
        descriptors = [node.descriptor for node in nodes]

        async def build(client: TelescopingClient) -> float:
            started = time.perf_counter_ns()
            await client.connect_guard(descriptors[0])
            await client.extend(descriptors[1])
            await client.extend(descriptors[2])
            return (time.perf_counter_ns() - started) / 1_000_000

        build_started = time.perf_counter_ns()
        build_latencies = await asyncio.gather(*(build(client) for client in clients))
        build_wall_ms = (time.perf_counter_ns() - build_started) / 1_000_000

        async def through_circuit(client: TelescopingClient, payload: bytes) -> tuple[float, bytes]:
            started = time.perf_counter_ns()
            response = await client.request_echo("127.0.0.1", echo_port, payload)
            return (time.perf_counter_ns() - started) / 1_000_000, response

        circuit_wall_started = time.perf_counter_ns()
        circuit_results = await asyncio.gather(*(
            through_circuit(client, payload)
            for client, payload in zip(clients, payloads, strict=True)
        ))
        circuit_wall_s = (time.perf_counter_ns() - circuit_wall_started) / 1_000_000_000
        circuit_latencies = [latency for latency, _ in circuit_results]
        integrity = all(response == payload for (_, response), payload in zip(circuit_results, payloads, strict=True))

        direct_wall_started = time.perf_counter_ns()
        direct_latencies = await asyncio.gather(*(
            _request_direct("127.0.0.1", echo_port, payload) for payload in payloads
        ))
        direct_wall_s = (time.perf_counter_ns() - direct_wall_started) / 1_000_000_000

        # Explicitly tear down circuits before returning and measure cleanup.
        for client in clients:
            await client.close()
        for _ in range(50):
            if all(node.active_connections == 0 for node in nodes):
                break
            await asyncio.sleep(0.01)
        active_after_close = [node.active_connections for node in nodes]

        bytes_total = payload_bytes * clients_count
        route_check = (
            all(event.target_port != echo_port for node in nodes[:2] for event in node.observations)
            and sum(event.operation == "data" for event in nodes[2].observations) == clients_count
        )
        return {
            "schema_version": 1,
            "metadata": {
                "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
                "version": __version__,
                "experiment": "concurrent independent three-hop telescoping circuits vs direct loopback TCP",
                "is_loopback_only": True,
                "is_production_security_test": False,
                "seed": seed,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "warning": "Single-host concurrent microbenchmark. It does not measure WAN performance or prove anonymity.",
            },
            "config": {
                "clients": clients_count,
                "payload_bytes_per_client": payload_bytes,
                "total_useful_payload_bytes": bytes_total,
                "hop_count": 3,
                "relay_connection_limit": DEFAULT_MAX_ACTIVE_CONNECTIONS,
                "echo_endpoint": "127.0.0.1",
            },
            "results": {
                "integrity_verified": integrity,
                "route_knowledge_separation_check": route_check,
                "client_direct_connections_per_circuit": [client.direct_connections_opened for client in clients],
                "circuit_build_ms_p50": statistics.median(build_latencies),
                "circuit_build_ms_p95": _percentile(build_latencies, 0.95),
                "concurrent_circuit_build_wall_ms": build_wall_ms,
                "circuit_echo_rtt_ms_p50": statistics.median(circuit_latencies),
                "circuit_echo_rtt_ms_p95": _percentile(circuit_latencies, 0.95),
                "circuit_aggregate_response_goodput_mbps": (bytes_total * 8) / circuit_wall_s / 1_000_000 if circuit_wall_s else 0,
                "direct_echo_rtt_ms_p50": statistics.median(direct_latencies),
                "direct_echo_rtt_ms_p95": _percentile(direct_latencies, 0.95),
                "direct_aggregate_response_goodput_mbps": (bytes_total * 8) / direct_wall_s / 1_000_000 if direct_wall_s else 0,
                "active_connections_after_client_close": active_after_close,
                "relay_handlers_returned_to_zero": all(count == 0 for count in active_after_close),
            },
            "limitations": [
                "All relay and destination sockets use IPv4 loopback on a single host.",
                "All circuits share one process, CPU, kernel and failure domain.",
                "Relay descriptors are caller-pinned in memory, not signed or revocable.",
                "The MALEBOLGE-specific KDF is experimental and unaudited.",
                "The experiment measures framed echo response payload, not bidirectional application streams.",
                "It does not test traffic correlation, malicious relays, internet routing or censorship resilience.",
            ],
        }
    finally:
        for client in clients:
            await client.close()
        for server in servers:
            server.close()
        for server in servers:
            await server.wait_closed()
        echo_server.close()
        await echo_server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--bytes", type=int, default=65_536, dest="payload_bytes")
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_concurrency_benchmark(
        clients_count=args.clients, payload_bytes=args.payload_bytes, seed=args.seed
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
