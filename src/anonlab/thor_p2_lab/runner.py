"""One P2 trial: build a real 3-hop AEGIS telescope with explicit lab knobs.

The trial measures the production path (real handshakes, real AEAD, real
framing, real relays) with exactly one variant dimension changed. It never
disables authentication, ACKs, credit checks or backpressure.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import os
import statistics
import time
from dataclasses import dataclass
from typing import Any

from .. import __version__
from ..telescoping import (
    FORWARD_WINDOW_UPDATE,
    INITIAL_STREAM_WINDOW_BYTES,
    STREAM_WRITE_MAX_BYTES,
    RelayNode,
    TelescopingClient,
    _encode_window_update_body,
    serve_node,
)
from ..thor_lab.appproto import start_echo_server
from ..thor_lab.counting_proxy import CountingProxy
from ..thor_lab.dispatch_lab import count_aead_ops
from ..thor_lab.resources import delta as resource_delta
from ..thor_lab.resources import snapshot as resource_snapshot
from .variants import VariantSpec

__all__ = ["LabWorkload", "WORKLOADS", "TrialResult", "run_trial", "percentile"]

TRANSFER_TIMEOUT_S = 120.0


@dataclass(frozen=True, slots=True)
class LabWorkload:
    """One workload shape, defined so every arm runs the exact same bytes."""

    name: str
    streams: int
    payload_bytes_per_stream: int
    write_chunk_bytes: int
    max_in_flight: int

    def __post_init__(self) -> None:
        if not 1 <= self.streams <= 16:
            raise ValueError("streams must be within 1..16")
        if not 1 <= self.payload_bytes_per_stream <= 4 * 1024 * 1024:
            raise ValueError("payload_bytes_per_stream must be within 1..4 MiB")
        if not 1 <= self.write_chunk_bytes <= STREAM_WRITE_MAX_BYTES:
            raise ValueError("write_chunk_bytes must be within 1..STREAM_WRITE_MAX_BYTES")
        if not 1 <= self.max_in_flight <= 4:
            raise ValueError("max_in_flight must be within 1..4 (prototype admission limit)")

    @property
    def total_bytes(self) -> int:
        return self.streams * self.payload_bytes_per_stream

    @property
    def commands_per_stream(self) -> int:
        return -(-self.payload_bytes_per_stream // self.write_chunk_bytes)

    @property
    def command_count(self) -> int:
        return self.commands_per_stream * self.streams

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "streams": self.streams,
            "payload_bytes_per_stream": self.payload_bytes_per_stream,
            "total_bytes": self.total_bytes,
            "write_chunk_bytes": self.write_chunk_bytes,
            "max_in_flight": self.max_in_flight,
            "commands_per_stream": self.commands_per_stream,
            "command_count": self.command_count,
        }


WORKLOADS: dict[str, LabWorkload] = {
    "bulk_1mib_c16k": LabWorkload("bulk_1mib_c16k", streams=1, payload_bytes_per_stream=1024 * 1024,
                                  write_chunk_bytes=16 * 1024, max_in_flight=4),
    "bulk_256k_c16k": LabWorkload("bulk_256k_c16k", streams=1, payload_bytes_per_stream=256 * 1024,
                                  write_chunk_bytes=16 * 1024, max_in_flight=4),
    "bulk_256k_c256k": LabWorkload("bulk_256k_c256k", streams=1, payload_bytes_per_stream=256 * 1024,
                                   write_chunk_bytes=256 * 1024, max_in_flight=1),
    "parallel_8x64k": LabWorkload("parallel_8x64k", streams=8, payload_bytes_per_stream=64 * 1024,
                                  write_chunk_bytes=16 * 1024, max_in_flight=4),
    "duplex_4x128cmd": LabWorkload("duplex_4x128cmd", streams=4,
                                   payload_bytes_per_stream=128 * 4 * 1024,
                                   write_chunk_bytes=4 * 1024, max_in_flight=4),
}


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; ``None`` for an empty sample (never invents a number)."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


@dataclass(slots=True)
class TrialResult:
    payload: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.payload["integrity"]["verified"]) and not self.payload["integrity"]["errors"]


def _payload(seed: int, size: int) -> bytes:
    """Deterministic payload so paired trials transfer identical bytes."""
    material = hashlib.sha256(f"aegis-thor-p2:{seed}:{size}".encode()).digest()
    out = bytearray()
    counter = 0
    while len(out) < size:
        out.extend(hashlib.sha256(material + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:size])


async def _apply_credit_topup(client: TelescopingClient, stream: Any, target_bytes: int) -> float:
    """Grant extra read credit with a normal WINDOW_UPDATE; returns elapsed ms."""
    extra = target_bytes - INITIAL_STREAM_WINDOW_BYTES
    if extra <= 0:
        return 0.0
    started = time.perf_counter_ns()
    reply = await client._send_duplex_command(
        stream, "V", _encode_window_update_body(extra), FORWARD_WINDOW_UPDATE
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    if reply != b"WINDOW_UPDATED":
        raise ValueError("invalid credit top-up acknowledgement")
    return elapsed_ms


async def run_trial(
    variant: VariantSpec,
    workload: LabWorkload,
    *,
    seed: int,
    collect_events: bool = False,
) -> TrialResult:
    """Run one trial and return bounded, payload-free measurements."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    echo = await start_echo_server()
    servers: list[asyncio.AbstractServer] = []
    proxy: CountingProxy | None = None
    client: TelescopingClient | None = None
    errors: list[str] = []
    try:
        nodes: list[RelayNode] = []
        for index in range(3):
            node = RelayNode(
                identity_digest=os.urandom(20),
                onion_private_key=X25519PrivateKey.generate(),
                collect_relay_metrics=True,
                stream_read_chunk_bytes=variant.relay_read_chunk_bytes,
            )
            if index == 2:
                node.allowed_destinations.add((echo.host, echo.port))
            servers.append(await serve_node(node))
            nodes.append(node)

        guard = nodes[0].descriptor
        proxy = CountingProxy(guard.host, guard.port, name="thor-p2-edge")
        await proxy.start()
        edge = dataclasses.replace(guard, host="127.0.0.1", port=proxy.listen_port)
        proxy_before = dataclasses.replace(proxy.counters)

        client = TelescopingClient(
            max_active_streams=max(8, workload.streams),
            window_update_batch_bytes=variant.credit_batch_bytes,
            window_update_max_delay_seconds=variant.credit_delay_seconds,
            max_event_bytes=variant.max_event_bytes,
            window_credit_pipeline=variant.credit_pipeline,
            window_update_flush_floor_bytes=variant.flush_floor_bytes,
        )

        started = time.perf_counter_ns()
        await client.connect_guard(edge)
        await client.extend(nodes[1].descriptor)
        await client.extend(nodes[2].descriptor)
        streams = [
            await client.open_stream(echo.host, echo.port) for _ in range(workload.streams)
        ]
        topup_ms: list[float] = []
        for stream in streams:
            topup_ms.append(await _apply_credit_topup(client, stream, variant.credit_window_bytes))
        setup_ms = (time.perf_counter_ns() - started) / 1_000_000

        payloads = [_payload(seed + index, workload.payload_bytes_per_stream)
                    for index in range(workload.streams)]
        read_offsets: list[int] = []
        event_sizes: list[int] = []

        async def drive(stream: Any, payload: bytes) -> dict[str, Any]:
            sent = 0
            received = 0
            ttfb_ms: float | None = None
            read_stamps: list[int] = []
            digest = hashlib.sha256()
            transfer_start = time.perf_counter_ns()

            async def writer() -> None:
                nonlocal sent
                chunk = workload.write_chunk_bytes
                for start in range(0, len(payload), chunk):
                    piece = payload[start:start + chunk]
                    await stream.write_pipelined(
                        piece, chunk_bytes=chunk, max_in_flight=workload.max_in_flight
                    )
                    sent += len(piece)
                await stream.write_eof()

            async def reader() -> None:
                nonlocal received, ttfb_ms
                while received < len(payload):
                    chunk = await stream.read_chunk()
                    if not chunk:
                        break
                    now = time.perf_counter_ns()
                    if ttfb_ms is None:
                        ttfb_ms = (now - transfer_start) / 1_000_000
                    read_stamps.append(now)
                    read_offsets.append(received)
                    event_sizes.append(len(chunk))
                    digest.update(chunk)
                    received += len(chunk)

            await asyncio.gather(writer(), reader())
            elapsed_ms = (time.perf_counter_ns() - transfer_start) / 1_000_000
            intervals = [
                (read_stamps[i] - read_stamps[i - 1]) / 1_000_000
                for i in range(1, len(read_stamps))
            ]
            return {
                "sent": sent,
                "received": received,
                "elapsed_ms": elapsed_ms,
                "ttfb_ms": ttfb_ms,
                "sha256": digest.hexdigest(),
                "expected_sha256": hashlib.sha256(payload).hexdigest(),
                "read_intervals_ms": intervals,
                "read_count": len(read_stamps),
            }

        resources_before = resource_snapshot()
        aead_context = count_aead_ops()
        aead_stats = aead_context.__enter__()
        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(*(drive(stream, payload)
                                 for stream, payload in zip(streams, payloads, strict=True))),
                timeout=TRANSFER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            errors.append("transfer_timeout")
            outcomes = []
        finally:
            aead_context.__exit__(None, None, None)
            resources_after = resource_snapshot()

        wall_s = max(
            (outcome["elapsed_ms"] for outcome in outcomes), default=0.0
        ) / 1000.0
        total_received = sum(outcome["received"] for outcome in outcomes)
        total_sent = sum(outcome["sent"] for outcome in outcomes)
        integrity = bool(outcomes) and all(
            outcome["sha256"] == outcome["expected_sha256"] and outcome["received"] == outcome["sent"]
            for outcome in outcomes
        )
        intervals = [value for outcome in outcomes for value in outcome["read_intervals_ms"]]
        ttfb_values = [outcome["ttfb_ms"] for outcome in outcomes if outcome["ttfb_ms"] is not None]

        relay_stages: dict[str, dict[str, float]] = {}
        relay_event_counts: list[int] = []
        window_updates = 0
        for node in nodes:
            snapshot = node.relay_metrics_snapshot()
            for stage, row in snapshot["summary_by_stage"].items():
                agg = relay_stages.setdefault(
                    stage, {"samples": 0.0, "total_ms": 0.0, "max_p95_ms": 0.0}
                )
                agg["samples"] += row["samples"]
                agg["total_ms"] += row["total_ms"]
                agg["max_p95_ms"] = max(agg["max_p95_ms"], row["p95_ms"])
            relay_event_counts.append(
                int(snapshot["summary_by_stage"].get("relay_event_send", {}).get("samples", 0))
            )
        window_updates = sum(
            1 for observation in nodes[-1].observations if observation.operation == "window_update"
        )

        proxy_delta = proxy_before.delta(proxy.counters)
        resource_info = resource_delta(resources_before, resources_after)
        aead_ops = int(aead_stats["seal_calls"]) + int(aead_stats["open_calls"])
        goodput_mbps = (
            (total_received * 8) / (wall_s * 1_000_000) if wall_s > 0 and total_received else None
        )

        return TrialResult(
            payload={
                "variant": variant.name,
                "variant_config": variant.to_dict(),
                "workload": workload.name,
                "workload_config": workload.to_dict(),
                "seed": seed,
                "environment": {
                    "python": __import__("sys").version.split()[0],
                    "platform": __import__("platform").platform(),
                    "aegis_version": __version__,
                    "tier": "loopback",
                },
                "setup_ms": setup_ms,
                "credit_topup_ms": sum(topup_ms),
                "transfer": {
                    "wall_ms": wall_s * 1000,
                    "payload_bytes": total_received,
                    "sent_bytes": total_sent,
                    "goodput_mbps": goodput_mbps,
                    "ttfb_ms_median": statistics.median(ttfb_values) if ttfb_values else None,
                    "read_latency_ms_p50": percentile(intervals, 0.50),
                    "read_latency_ms_p95": percentile(intervals, 0.95),
                    "read_latency_ms_p99": percentile(intervals, 0.99),
                    "read_count": len(intervals) + len(ttfb_values),
                },
                "waits": {
                    "downstream_response_wait_ms": relay_stages.get(
                        "downstream_response_wait", {}
                    ).get("total_ms", 0.0),
                    "flow_credit_wait_ms": relay_stages.get("flow_credit_wait", {}).get(
                        "total_ms", 0.0
                    ),
                    "destination_read_wait_ms": relay_stages.get(
                        "destination_read_wait", {}
                    ).get("total_ms", 0.0),
                    "response_wait_ms": relay_stages.get("downstream_response_wait", {}).get(
                        "total_ms", 0.0
                    ),
                    "relay_stages": relay_stages,
                },
                "counts": {
                    "ack_count": workload.command_count,
                    "window_update_count": window_updates,
                    "client_visible_events": relay_event_counts[0],
                    "events_per_hop": relay_event_counts,
                    "avg_event_bytes": (
                        total_received / relay_event_counts[0] if relay_event_counts[0] else None
                    ),
                    "aead_ops": aead_ops,
                    "aead_ops_per_kib": (aead_ops / (total_received / 1024)) if total_received else None,
                },
                "resources": {
                    "cpu_process_s": resource_info.cpu_process_s,
                    "cpu_fraction_of_one_core": resource_info.cpu_fraction_of_one_core,
                    "rss_start_kb": resource_info.rss_start_kb,
                    "rss_end_kb": resource_info.rss_end_kb,
                    "peak_rss_kb": resource_info.peak_rss_kb,
                },
                "wire": proxy_delta,
                "integrity": {
                    "verified": integrity,
                    "errors": errors,
                    "streams_ok": sum(
                        1 for outcome in outcomes
                        if outcome["sha256"] == outcome["expected_sha256"]
                    ),
                    "streams_expected": workload.streams,
                },
                "privacy_note": (
                    "Loopback only. Contains counts, sizes and durations of synthetic payloads; "
                    "no payload bytes, keys, stream IDs or addresses."
                ),
                "collect_events": collect_events,
            }
        )
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()
        if proxy is not None:
            with contextlib.suppress(Exception):
                await proxy.close()
        for server in servers:
            server.close()
        for server in servers:
            with contextlib.suppress(Exception):
                await server.wait_closed()
        with contextlib.suppress(Exception):
            await echo.close()
