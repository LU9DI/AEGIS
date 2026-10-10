"""Reproducible loopback benchmark under user-space link shaping.

The profiles approximate latency, jitter and bandwidth using bounded queues in
a transparent TCP proxy. They do not emulate packet loss, radio behavior,
real TCP congestion, or a geographically distributed WAN.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import random
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from . import __version__
from .network_impairment import DEFAULT_PROFILES, LinkImpairmentProfile, TcpImpairmentProxy
from .telescoping import (
    STREAM_CHUNK_BYTES,
    STREAM_WRITE_MAX_BYTES,
    RelayDescriptor,
    RelayNode,
    TelescopingClient,
    _raw_public_key,
    serve_node,
)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * p + 0.999999)))]


def _jain_index(values: list[float]) -> float:
    """Return Jain's fairness index for non-negative per-flow service rates.

    This is only a completion-rate proxy for finite equal-sized transfers, not
    a proof of long-lived flow fairness or a congestion-control guarantee.
    """
    if not values:
        return 1.0
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("fairness rates must be finite and non-negative")
    total = sum(values)
    squared = sum(value * value for value in values)
    if squared == 0.0:
        return 1.0
    return (total * total) / (len(values) * squared)


async def run_network_impairment_benchmark(
    *,
    profile: LinkImpairmentProfile,
    stream_count: int = 4,
    payload_bytes: int = 64 * 1024,
    seed: int = 20261020,
    sparse_gap_ms: float = 0.0,
    sparse_chunk_bytes: int = 4096,
    write_chunk_bytes: int = STREAM_WRITE_MAX_BYTES,
    pipeline_depth: int = 1,
    fair_write_scheduling: bool = False,
) -> dict[str, Any]:
    if not isinstance(stream_count, int) or isinstance(stream_count, bool) or not 1 <= stream_count <= 32:
        raise ValueError("stream_count must be within 1..32")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or not 1 <= payload_bytes <= 1 * 1024 * 1024:
        raise ValueError("payload_bytes must be within 1..1048576")
    if not isinstance(sparse_gap_ms, (int, float)) or isinstance(sparse_gap_ms, bool) or sparse_gap_ms < 0 or sparse_gap_ms > 1000:
        raise ValueError("sparse_gap_ms must be within 0..1000")
    if not isinstance(sparse_chunk_bytes, int) or isinstance(sparse_chunk_bytes, bool) or not 1 <= sparse_chunk_bytes <= STREAM_WRITE_MAX_BYTES:
        raise ValueError(f"sparse_chunk_bytes must be within 1..{STREAM_WRITE_MAX_BYTES}")
    if not isinstance(write_chunk_bytes, int) or isinstance(write_chunk_bytes, bool) or not 1 <= write_chunk_bytes <= STREAM_WRITE_MAX_BYTES:
        raise ValueError(f"write_chunk_bytes must be within 1..{STREAM_WRITE_MAX_BYTES}")
    if not isinstance(pipeline_depth, int) or isinstance(pipeline_depth, bool) or not 1 <= pipeline_depth <= 4:
        raise ValueError("pipeline_depth must be within 1..4")
    if not isinstance(fair_write_scheduling, bool):
        raise ValueError("fair_write_scheduling must be a boolean")

    nodes: list[RelayNode] = []
    relay_servers: list[asyncio.AbstractServer] = []
    proxies: list[TcpImpairmentProxy] = []
    destination_server: asyncio.AbstractServer | None = None
    client = TelescopingClient(max_active_streams=max(8, stream_count), fair_write_scheduling=fair_write_scheduling)
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
            if writer.can_write_eof():
                writer.write_eof()
                await writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def start_proxy(target_port: int, offset: int) -> TcpImpairmentProxy:
        shaped_profile = replace(profile, seed=profile.seed + offset * 1_000_033)
        proxy = TcpImpairmentProxy("127.0.0.1", target_port, shaped_profile)
        await proxy.start()
        proxies.append(proxy)
        return proxy

    try:
        destination_server = await asyncio.start_server(echo_handler, "127.0.0.1", 0)
        echo_port = int(destination_server.sockets[0].getsockname()[1])
        for _ in range(3):
            node = RelayNode(identity_digest=__import__("os").urandom(20), onion_private_key=X25519PrivateKey.generate())
            relay_servers.append(await serve_node(node))
            nodes.append(node)

        # Each circuit link passes through a bounded queue with latency/jitter/rate shaping.
        relay_proxies: list[TcpImpairmentProxy] = []
        for index, node in enumerate(nodes):
            assert node.port is not None
            relay_proxies.append(await start_proxy(node.port, index + 1))
        destination_proxy = await start_proxy(echo_port, 4)
        destination_port = destination_proxy.listen_port
        nodes[-1].allowed_destinations.add(("127.0.0.1", destination_port))

        descriptors = [
            RelayDescriptor(
                host="127.0.0.1",
                port=proxy.listen_port,
                identity_digest=node.identity_digest,
                onion_public_key=_raw_public_key(node.onion_private_key.public_key()),
            )
            for node, proxy in zip(nodes, relay_proxies, strict=True)
        ]

        build_started = time.perf_counter_ns()
        await client.connect_guard(descriptors[0])
        await client.extend(descriptors[1])
        await client.extend(descriptors[2])
        circuit_build_ms = (time.perf_counter_ns() - build_started) / 1_000_000

        rng = random.Random(seed)
        payloads = [rng.randbytes(payload_bytes) for _ in range(stream_count)]
        stream_open_started = time.perf_counter_ns()
        streams = await asyncio.gather(*(
            client.open_stream("127.0.0.1", destination_port) for _ in range(stream_count)
        ))
        stream_open_ms = (time.perf_counter_ns() - stream_open_started) / 1_000_000

        async def send_on_stream(stream: Any, payload: bytes) -> tuple[float, bytes]:
            started = time.perf_counter_ns()
            if sparse_gap_ms > 0:
                block_size = min(sparse_chunk_bytes, write_chunk_bytes)
                for offset in range(0, len(payload), block_size):
                    await stream.write_pipelined(
                        payload[offset:offset + block_size],
                        chunk_bytes=write_chunk_bytes,
                        max_in_flight=pipeline_depth,
                    )
                    if offset + block_size < len(payload):
                        await asyncio.sleep(sparse_gap_ms / 1000)
            else:
                await stream.write_pipelined(
                    payload, chunk_bytes=write_chunk_bytes, max_in_flight=pipeline_depth
                )
            await stream.write_eof()
            received = bytearray()
            while True:
                data = await stream.read_chunk()
                if not data:
                    break
                received.extend(data)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            await stream.close()
            return elapsed_ms, bytes(received)

        circuit_started = time.perf_counter_ns()
        circuit_results = await asyncio.gather(*(
            send_on_stream(stream, payload)
            for stream, payload in zip(streams, payloads, strict=True)
        ))
        circuit_wall_s = (time.perf_counter_ns() - circuit_started) / 1_000_000_000

        async def direct_exchange(payload: bytes) -> tuple[float, bytes]:
            started = time.perf_counter_ns()
            reader, writer = await asyncio.open_connection("127.0.0.1", destination_port)
            received = bytearray()
            try:
                if sparse_gap_ms > 0:
                    block_size = min(sparse_chunk_bytes, write_chunk_bytes)
                    for offset in range(0, len(payload), block_size):
                        writer.write(payload[offset:offset + block_size])
                        await writer.drain()
                        if offset + block_size < len(payload):
                            await asyncio.sleep(sparse_gap_ms / 1000)
                else:
                    writer.write(payload)
                    await writer.drain()
                writer.write_eof()
                await writer.drain()
                while True:
                    data = await reader.read(STREAM_CHUNK_BYTES)
                    if not data:
                        break
                    received.extend(data)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                return elapsed_ms, bytes(received)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

        direct_started = time.perf_counter_ns()
        direct_results = await asyncio.gather(*(direct_exchange(payload) for payload in payloads))
        direct_wall_s = (time.perf_counter_ns() - direct_started) / 1_000_000_000
        await client.close()
        # Circuit teardown is asynchronous across relay and shaper tasks. Wait
        # for every observable layer to drain before recording cleanup metrics;
        # otherwise the benchmark can report a transient active proxy and leak
        # a StreamWriter when the event loop closes immediately afterward.
        for _ in range(200):
            if (
                all(node.active_connections == 0 for node in nodes)
                and len(client._active_duplex_streams) == 0
                and all(proxy.metrics.active_connections == 0 for proxy in proxies)
            ):
                break
            await asyncio.sleep(0.01)

        circuit_latencies = [latency for latency, _ in circuit_results]
        direct_latencies = [latency for latency, _ in direct_results]
        circuit_stream_goodput = [
            payload_bytes * 8 / (latency_ms / 1000) / 1_000_000 if latency_ms > 0 else 0.0
            for latency_ms, _ in circuit_results
        ]
        direct_stream_goodput = [
            payload_bytes * 8 / (latency_ms / 1000) / 1_000_000 if latency_ms > 0 else 0.0
            for latency_ms, _ in direct_results
        ]
        useful_bits = stream_count * payload_bytes * 8
        return {
            "schema_version": 1,
            "metadata": {
                "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
                "version": __version__,
                "experiment": "loopback circuit benchmark with deterministic user-space latency/jitter/bandwidth shaping",
                "is_loopback_only": True,
                "is_real_wan_measurement": False,
                "is_packet_loss_simulation": False,
                "is_production_security_test": False,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "seed": seed,
                "warning": "Shaper profiles approximate byte-stream timing and rate only. TCP remains reliable. Results are not WAN measurements and do not prove anonymity.",
            },
            "profile": {
                "name": profile.name,
                "one_way_latency_ms": profile.latency_ms,
                "jitter_uniform_plus_minus_ms": profile.jitter_ms,
                "bandwidth_mbps_per_direction": profile.bandwidth_mbps,
                "shaper_chunk_bytes": profile.chunk_bytes,
                "queue_chunks_per_direction": profile.queue_chunks,
            },
            "config": {
                "streams": stream_count,
                "payload_bytes_per_stream": payload_bytes,
                "total_useful_bytes": stream_count * payload_bytes,
                "hop_count": 3,
                "sparse_gap_ms": sparse_gap_ms,
                "sparse_chunk_bytes": sparse_chunk_bytes if sparse_gap_ms > 0 else None,
                "write_chunk_bytes": write_chunk_bytes,
                "pipeline_depth": pipeline_depth,
                "fair_write_scheduling": fair_write_scheduling,
                "window_update_batch_bytes": 64 * 1024,
                "queue_bound_per_direction_per_connection": profile.queue_chunks,
                "max_proxy_connections_per_shaper": 64,
            },
            "results": {
                "integrity_verified": all(response == payload for (_, response), payload in zip(circuit_results, payloads, strict=True))
                and all(response == payload for (_, response), payload in zip(direct_results, payloads, strict=True)),
                "circuit_build_ms": circuit_build_ms,
                "stream_open_batch_ms": stream_open_ms,
                "circuit_wall_ms": circuit_wall_s * 1000,
                "circuit_goodput_mbps": useful_bits / circuit_wall_s / 1_000_000 if circuit_wall_s else 0.0,
                "circuit_stream_latency_p50_ms": statistics.median(circuit_latencies) if circuit_latencies else 0.0,
                "circuit_stream_latency_p95_ms": _percentile(circuit_latencies, 0.95),
                "direct_wall_ms": direct_wall_s * 1000,
                "direct_goodput_mbps": useful_bits / direct_wall_s / 1_000_000 if direct_wall_s else 0.0,
                "direct_stream_latency_p50_ms": statistics.median(direct_latencies) if direct_latencies else 0.0,
                "direct_stream_latency_p95_ms": _percentile(direct_latencies, 0.95),
                "circuit_completion_rate_jain_index": _jain_index(circuit_stream_goodput),
                "direct_completion_rate_jain_index": _jain_index(direct_stream_goodput),
                "circuit_per_stream": [
                    {
                        "stream_index": index,
                        "elapsed_ms": elapsed_ms,
                        "goodput_mbps": circuit_stream_goodput[index],
                        "bytes_returned": len(response),
                    }
                    for index, (elapsed_ms, response) in enumerate(circuit_results)
                ],
                "direct_per_stream": [
                    {
                        "stream_index": index,
                        "elapsed_ms": elapsed_ms,
                        "goodput_mbps": direct_stream_goodput[index],
                        "bytes_returned": len(response),
                    }
                    for index, (elapsed_ms, response) in enumerate(direct_results)
                ],
                "relay_observability_check": sum(event.operation == "stream_open" for event in nodes[-1].observations) == stream_count
                and all(event.target_port != destination_port for node in nodes[:2] for event in node.observations),
                "all_relay_connections_closed": all(node.active_connections == 0 for node in nodes),
                "active_proxy_connections_after_close": [proxy.metrics.active_connections for proxy in proxies],
                "proxy_rejected_connections": sum(proxy.metrics.rejected_connections for proxy in proxies),
                "proxy_accepted_connections": [proxy.metrics.accepted_connections for proxy in proxies],
                "max_shaper_queue_chunks_observed": max(proxy.metrics.max_queue_chunks_observed for proxy in proxies),
                "shaper_queue_chunks_configured": profile.queue_chunks,
                "proxy_bytes_client_to_upstream": sum(proxy.metrics.bytes_client_to_upstream for proxy in proxies),
                "proxy_bytes_upstream_to_client": sum(proxy.metrics.bytes_upstream_to_client for proxy in proxies),
                "destination_connections": destination_connections,
            },
            "limitations": [
                "All real relays, shaping proxies and destination run on one host with IPv4 loopback.",
                "User-space shaping adds one-way delay, jitter and serialization rates to stream chunks; those chunks are not IP packets.",
                "No packet loss, TCP retransmission behavior, routing changes, radio interference or real WAN congestion is modeled.",
                "Direct comparison uses one shaped link; the circuit uses client-to-guard, guard-to-middle, middle-to-exit and exit-to-destination links.",
                "The protocol remains a custom experimental implementation and has not been independently audited or proven anonymous.",
            ],
        }
    finally:
        await client.close()
        if destination_server is not None:
            destination_server.close()
            await destination_server.wait_closed()
        for proxy in reversed(proxies):
            await proxy.close()
        for server in reversed(relay_servers):
            server.close()
        for server in reversed(relay_servers):
            await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure AEGIS circuits under loopback user-space link shaping")
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="metro")
    parser.add_argument("--streams", type=int, default=4)
    parser.add_argument("--payload-bytes", type=int, default=64 * 1024)
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--sparse-gap-ms", type=float, default=0.0)
    parser.add_argument("--sparse-chunk-bytes", type=int, default=4096)
    parser.add_argument("--write-chunk-bytes", type=int, default=STREAM_WRITE_MAX_BYTES)
    parser.add_argument("--pipeline-depth", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--fair-write-scheduling", action="store_true", help="enable experimental round-robin circuit write scheduler")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_network_impairment_benchmark(
        profile=DEFAULT_PROFILES[args.profile],
        stream_count=args.streams,
        payload_bytes=args.payload_bytes,
        seed=args.seed,
        sparse_gap_ms=args.sparse_gap_ms,
        sparse_chunk_bytes=args.sparse_chunk_bytes,
        write_chunk_bytes=args.write_chunk_bytes,
        pipeline_depth=args.pipeline_depth,
        fair_write_scheduling=args.fair_write_scheduling,
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
