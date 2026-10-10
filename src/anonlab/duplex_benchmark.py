"""Loopback benchmark for AEGIS's experimental full-duplex streams."""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from . import __version__
from .telescoping import (
    MAX_PIPELINE_DEPTH,
    MAX_PIPELINED_WRITE_PAYLOAD_BYTES,
    STREAM_CHUNK_BYTES,
    STREAM_WRITE_MAX_BYTES,
    RelayNode,
    TelescopingClient,
    WINDOW_UPDATE_BATCH_BYTES,
    MAX_STREAM_WINDOW_BYTES,
    serve_node,
)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * p + 0.999999)))]


async def run_duplex_benchmark(
    *, stream_count: int = 8, payload_bytes: int = 64 * 1024, seed: int = 20261009,
    write_chunk_bytes: int = STREAM_WRITE_MAX_BYTES, pipeline_depth: int = 1,
    window_update_batch_bytes: int = WINDOW_UPDATE_BATCH_BYTES,
) -> dict[str, Any]:
    if not isinstance(stream_count, int) or isinstance(stream_count, bool) or not 1 <= stream_count <= 64:
        raise ValueError("stream_count must be within 1..64")
    if (not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool)
            or not 1 <= payload_bytes <= MAX_PIPELINED_WRITE_PAYLOAD_BYTES):
        raise ValueError(f"payload_bytes must be within 1..{MAX_PIPELINED_WRITE_PAYLOAD_BYTES}")
    if not isinstance(write_chunk_bytes, int) or isinstance(write_chunk_bytes, bool) or not 1 <= write_chunk_bytes <= STREAM_WRITE_MAX_BYTES:
        raise ValueError(f"write_chunk_bytes must be within 1..{STREAM_WRITE_MAX_BYTES}")
    if not isinstance(pipeline_depth, int) or isinstance(pipeline_depth, bool) or not 1 <= pipeline_depth <= MAX_PIPELINE_DEPTH:
        raise ValueError(f"pipeline_depth must be within 1..{MAX_PIPELINE_DEPTH}")
    if (not isinstance(window_update_batch_bytes, int) or isinstance(window_update_batch_bytes, bool)
            or not 1 <= window_update_batch_bytes <= MAX_STREAM_WINDOW_BYTES):
        raise ValueError(f"window_update_batch_bytes must be within 1..{MAX_STREAM_WINDOW_BYTES}")

    nodes: list[RelayNode] = []
    relay_servers: list[asyncio.AbstractServer] = []
    destination_server: asyncio.AbstractServer | None = None
    client = TelescopingClient(
        max_active_streams=max(8, stream_count),
        window_update_batch_bytes=window_update_batch_bytes,
    )
    destination_connections = 0

    async def echo_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal destination_connections
        destination_connections += 1
        try:
            while True:
                data = await reader.read(STREAM_CHUNK_BYTES)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    try:
        destination_server = await asyncio.start_server(echo_handler, "127.0.0.1", 0)
        destination_port = int(destination_server.sockets[0].getsockname()[1])
        for _ in range(3):
            node = RelayNode(
                identity_digest=__import__("os").urandom(20),
                onion_private_key=X25519PrivateKey.generate(),
            )
            relay_servers.append(await serve_node(node))
            nodes.append(node)
        nodes[-1].allowed_destinations.add(("127.0.0.1", destination_port))
        descriptors = [node.descriptor for node in nodes]

        started = time.perf_counter_ns()
        await client.connect_guard(descriptors[0])
        await client.extend(descriptors[1])
        await client.extend(descriptors[2])
        circuit_build_ms = (time.perf_counter_ns() - started) / 1_000_000

        rng = random.Random(seed)
        payloads = [rng.randbytes(payload_bytes) for _ in range(stream_count)]
        open_started = time.perf_counter_ns()
        streams = await asyncio.gather(*(
            client.open_stream("127.0.0.1", destination_port) for _ in range(stream_count)
        ))
        stream_open_ms = (time.perf_counter_ns() - open_started) / 1_000_000

        async def duplex_exchange(stream, payload: bytes) -> tuple[float, bytes]:
            local_started = time.perf_counter_ns()
            await stream.write_pipelined(
                payload, chunk_bytes=write_chunk_bytes, max_in_flight=pipeline_depth
            )
            await stream.write_eof()
            received = bytearray()
            while True:
                chunk = await stream.read_chunk()
                if not chunk:
                    break
                received.extend(chunk)
            elapsed_ms = (time.perf_counter_ns() - local_started) / 1_000_000
            await stream.close()
            return elapsed_ms, bytes(received)

        duplex_started = time.perf_counter_ns()
        duplex_results = await asyncio.gather(*(
            duplex_exchange(stream, payload) for stream, payload in zip(streams, payloads, strict=True)
        ))
        duplex_wall_s = (time.perf_counter_ns() - duplex_started) / 1_000_000_000
        duplex_latency_ms = [latency for latency, _ in duplex_results]
        duplex_responses = [response for _, response in duplex_results]

        async def direct_exchange(payload: bytes) -> tuple[float, bytes]:
            local_started = time.perf_counter_ns()
            reader, writer = await asyncio.open_connection("127.0.0.1", destination_port)
            try:
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                response = bytearray()
                while True:
                    chunk = await reader.read(STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    response.extend(chunk)
                elapsed_ms = (time.perf_counter_ns() - local_started) / 1_000_000
                return elapsed_ms, bytes(response)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

        direct_started = time.perf_counter_ns()
        direct_results = await asyncio.gather(*(direct_exchange(payload) for payload in payloads))
        direct_wall_s = (time.perf_counter_ns() - direct_started) / 1_000_000_000
        direct_latency_ms = [latency for latency, _ in direct_results]
        direct_responses = [response for _, response in direct_results]

        await client.close()
        for _ in range(100):
            if all(node.active_connections == 0 for node in nodes) and len(client._active_duplex_streams) == 0:
                break
            await asyncio.sleep(0.01)
        active_connections_after_close = [node.active_connections for node in nodes]
        useful_bits = stream_count * payload_bytes * 8
        return {
            "schema_version": 1,
            "metadata": {
                "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
                "version": __version__,
                "experiment": "continuous duplex stream with bounded read credit, write batching, and bounded in-flight WRITE pipeline",
                "is_loopback_only": True,
                "is_production_security_test": False,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "seed": seed,
                "warning": "Single-host loopback measurements are not WAN results and do not prove anonymity or security. Compare write batching scenarios with identical stream and payload settings.",
            },
            "config": {
                "streams": stream_count,
                "payload_bytes_per_stream": payload_bytes,
                "total_useful_bytes": stream_count * payload_bytes,
                "hop_count": 3,
                "response_event_chunk_bytes": STREAM_CHUNK_BYTES,
                "write_chunk_bytes": write_chunk_bytes,
                "pipeline_depth": pipeline_depth,
                "window_update_batch_bytes": window_update_batch_bytes,
                "window_update_max_delay_ms": 2.0,
                "max_pipeline_payload_bytes": 4 * 1024 * 1024,
                "write_acknowledgements_per_full_64k_stream": (64 * 1024 + write_chunk_bytes - 1) // write_chunk_bytes,
                "initial_read_window_bytes": 64 * 1024,
                "destination": "127.0.0.1",
            },
            "results": {
                "integrity_verified": duplex_responses == payloads and direct_responses == payloads,
                "circuit_build_ms": circuit_build_ms,
                "stream_open_batch_ms": stream_open_ms,
                "duplex_wall_ms": duplex_wall_s * 1000,
                "duplex_goodput_mbps": useful_bits / duplex_wall_s / 1_000_000 if duplex_wall_s else 0.0,
                "duplex_stream_latency_p50_ms": statistics.median(duplex_latency_ms) if duplex_latency_ms else 0.0,
                "duplex_stream_latency_p95_ms": _percentile(duplex_latency_ms, 0.95),
                "direct_wall_ms": direct_wall_s * 1000,
                "direct_goodput_mbps": useful_bits / direct_wall_s / 1_000_000 if direct_wall_s else 0.0,
                "direct_stream_latency_p50_ms": statistics.median(direct_latency_ms) if direct_latency_ms else 0.0,
                "direct_stream_latency_p95_ms": _percentile(direct_latency_ms, 0.95),
                "destination_connections": destination_connections,
                "window_update_commands": sum(
                    event.operation == "window_update" for event in nodes[-1].observations
                ),
                "active_streams_after_completion": len(client._active_duplex_streams),
                "active_connections_after_close": active_connections_after_close,
                "relay_observability_check": all(
                    event.target_port != destination_port for node in nodes[:2] for event in node.observations
                ) and sum(event.operation == "stream_open" for event in nodes[2].observations) == stream_count,
            },
            "limitations": [
                "All relays and destination use one host and IPv4 loopback.",
                "This is a custom experimental protocol, not Tor-compatible, audited, or production-safe.",
                "The exit can observe the destination and cleartext application bytes; adjacent relays observe timings, sizes, and per-link stream identifiers.",
                "Flow control is a bounded per-stream read-credit window and bounded WRITE pipeline; no fairness proof or production congestion-control analysis exists.",
                "No conclusion about traffic-analysis resistance or Tor-relative performance can be inferred.",
            ],
        }
    finally:
        await client.close()
        if destination_server is not None:
            destination_server.close()
            await destination_server.wait_closed()
        for server in relay_servers:
            server.close()
        for server in relay_servers:
            await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure loopback-only AEGIS full-duplex streams")
    parser.add_argument("--streams", type=int, default=8)
    parser.add_argument("--payload-bytes", type=int, default=65_536)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--write-chunk-bytes", type=int, default=STREAM_WRITE_MAX_BYTES,
                        help=f"application data per WRITE command (1..{STREAM_WRITE_MAX_BYTES})")
    parser.add_argument("--pipeline-depth", type=int, default=1, choices=range(1, MAX_PIPELINE_DEPTH + 1),
                        help=f"maximum in-flight WRITE commands per stream (1..{MAX_PIPELINE_DEPTH})")
    parser.add_argument("--window-update-batch-bytes", type=int, default=WINDOW_UPDATE_BATCH_BYTES,
                        help=f"consumed bytes coalesced into a WINDOW_UPDATE (1..{MAX_STREAM_WINDOW_BYTES})")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_duplex_benchmark(
        stream_count=args.streams, payload_bytes=args.payload_bytes, seed=args.seed,
        write_chunk_bytes=args.write_chunk_bytes,
        pipeline_depth=args.pipeline_depth,
        window_update_batch_bytes=args.window_update_batch_bytes,
    ))
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
