"""Loopback-only same-circuit stream multiplexing benchmark for AEGIS."""
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
except ImportError as exc:  # pragma: no cover - optional research dependency
    raise RuntimeError(
        "The stream benchmark requires: python -m pip install 'rea-anon-lab[onion-lab]'"
    ) from exc

from . import __version__
from .onion_protocol import frame
from .telescoping import RelayNode, TelescopingClient, read_frame, serve_node
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


async def run_stream_multiplex_benchmark(
    *, streams_count: int = 32, payload_bytes: int = 16_384, seed: int = 20261009
) -> dict[str, Any]:
    """Compare concurrent one-shot streams and serial requests on one three-hop circuit.

    Every socket is restricted to 127.0.0.1. This measures only this host and
    does not establish traffic-analysis resistance, WAN performance or security.
    """
    if not isinstance(streams_count, int) or isinstance(streams_count, bool) or not 1 <= streams_count <= 128:
        raise ValueError("streams_count must be within 1..128")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1 <= payload_bytes <= 1_048_576:
        raise ValueError("payload_bytes must be within 1..1048576")

    prng = __import__("random").Random(seed)
    payloads = [bytes(prng.randrange(256) for _ in range(payload_bytes)) for _ in range(streams_count)]
    echo_server = await asyncio.start_server(_echo_handler, "127.0.0.1", 0)
    echo_port = int(echo_server.sockets[0].getsockname()[1])
    nodes: list[RelayNode] = []
    servers: list[asyncio.AbstractServer] = []
    client = TelescopingClient(max_active_streams=streams_count)
    try:
        for index in range(3):
            node = RelayNode(os.urandom(20), X25519PrivateKey.generate())
            if index == 2:
                node.allowed_destinations.add(("127.0.0.1", echo_port))
            server = await serve_node(node)
            nodes.append(node)
            servers.append(server)
        descriptors = [node.descriptor for node in nodes]
        build_started = time.perf_counter_ns()
        await client.connect_guard(descriptors[0])
        await client.extend(descriptors[1])
        await client.extend(descriptors[2])
        build_ms = (time.perf_counter_ns() - build_started) / 1_000_000

        concurrent_started = time.perf_counter_ns()
        pending_results: list[asyncio.Task[tuple[float, bytes]]] = []
        for payload in payloads:
            started_ns = time.perf_counter_ns()
            stream = await client.start_echo("127.0.0.1", echo_port, payload)

            async def collect(s=stream, original=payload, started=started_ns) -> tuple[float, bytes]:
                response = await s.result()
                return (time.perf_counter_ns() - started) / 1_000_000, response

            pending_results.append(asyncio.create_task(collect()))
        concurrent_results = await asyncio.gather(*pending_results)
        concurrent_wall_s = (time.perf_counter_ns() - concurrent_started) / 1_000_000_000
        concurrent_latencies = [latency for latency, _ in concurrent_results]
        concurrent_responses = [response for _, response in concurrent_results]
        integrity_concurrent = concurrent_responses == payloads

        serial_latencies: list[float] = []
        serial_responses: list[bytes] = []
        serial_started = time.perf_counter_ns()
        for payload in payloads:
            started_ns = time.perf_counter_ns()
            serial_responses.append(await client.request_echo("127.0.0.1", echo_port, payload))
            serial_latencies.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        serial_wall_s = (time.perf_counter_ns() - serial_started) / 1_000_000_000

        active_streams_after_completion = len(client._active_streams)
        direct_connections_opened = client.direct_connections_opened
        await client.close()
        for _ in range(100):
            if all(node.active_connections == 0 for node in nodes):
                break
            await asyncio.sleep(0.01)
        active_after_close = [node.active_connections for node in nodes]
        route_check = (
            all(event.target_port != echo_port for node in nodes[:2] for event in node.observations)
            and sum(event.operation == "data" for event in nodes[2].observations) == streams_count * 2
        )
        return {
            "schema_version": 1,
            "metadata": {
                "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
                "version": __version__,
                "experiment": "same-circuit multiplexing vs serial request-response baseline",
                "is_loopback_only": True,
                "is_production_security_test": False,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "seed": seed,
                "warning": "One host, three loopback relays. Multiplexing results are not WAN or anonymity claims.",
            },
            "config": {
                "streams": streams_count,
                "payload_bytes_per_stream": payload_bytes,
                "hop_count": 3,
                "total_useful_bytes_per_round": streams_count * payload_bytes,
                "echo_endpoint": "127.0.0.1",
            },
            "results": {
                "integrity_verified": integrity_concurrent and serial_responses == payloads,
                "route_knowledge_separation_check": route_check,
                "direct_client_connections": direct_connections_opened,
                "circuit_build_ms": build_ms,
                "multiplexed_rtt_ms_p50": statistics.median(concurrent_latencies),
                "multiplexed_rtt_ms_p95": _percentile(concurrent_latencies, 0.95),
                "multiplexed_wall_ms": concurrent_wall_s * 1000,
                "multiplexed_goodput_mbps": (streams_count * payload_bytes * 8 / concurrent_wall_s / 1_000_000) if concurrent_wall_s else 0,
                "serial_rtt_ms_p50": statistics.median(serial_latencies),
                "serial_rtt_ms_p95": _percentile(serial_latencies, 0.95),
                "serial_wall_ms": serial_wall_s * 1000,
                "serial_goodput_mbps": (streams_count * payload_bytes * 8 / serial_wall_s / 1_000_000) if serial_wall_s else 0,
                "active_streams_after_completion": active_streams_after_completion,
                "active_connections_after_close": active_after_close,
            },
            "limitations": [
                "A stream is one bounded request plus one response, not arbitrary full-duplex TCP byte streams.",
                "All relay and destination sockets run on one host over IPv4 loopback.",
                "Response correlation metadata is visible to the immediate peer on each hop.",
                "The protocol, key derivation and cancellation semantics have not had an independent security audit.",
                "No conclusion about traffic-analysis resistance or Tor-relative performance can be inferred.",
            ],
        }
    finally:
        await client.close()
        echo_server.close()
        await echo_server.wait_closed()
        for server in servers:
            server.close()
        for server in servers:
            await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure loopback-only same-circuit AEGIS stream multiplexing")
    parser.add_argument("--streams", type=int, default=32)
    parser.add_argument("--payload-bytes", type=int, default=16_384)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_stream_multiplex_benchmark(
        streams_count=args.streams, payload_bytes=args.payload_bytes, seed=args.seed
    ))
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
