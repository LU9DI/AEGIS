"""Mixed-workload scheduler benchmark for the AEGIS loopback lab.

Runs one bulk transfer alongside early and staggered request/response flows.
The benchmark measures responsiveness and integrity; it is not a WAN simulator.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
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
    MAX_STREAM_WINDOW_BYTES,
    WINDOW_UPDATE_BATCH_BYTES,
    WINDOW_UPDATE_MAX_DELAY_SECONDS,
    RelayDescriptor,
    RelayNode,
    TelescopingClient,
    _raw_public_key,
    serve_node,
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile + 0.999999)))
    return float(ordered[index])


async def run_mixed_workload_benchmark(
    *,
    profile: LinkImpairmentProfile,
    bulk_bytes: int = 512 * 1024,
    interactive_requests: int = 8,
    request_bytes: int = 128,
    request_gap_ms: float = 15.0,
    stagger_after_ms: float = 60.0,
    write_chunk_bytes: int = 16 * 1024,
    pipeline_depth: int = 4,
    fair_write_scheduling: bool = False,
    window_update_batch_bytes: int = WINDOW_UPDATE_BATCH_BYTES,
    window_update_max_delay_seconds: float = WINDOW_UPDATE_MAX_DELAY_SECONDS,
    seed: int = 20261023,
) -> dict[str, Any]:
    """Run bulk + early-interactive + staggered-interactive flows over 3 hops."""
    if not isinstance(bulk_bytes, int) or isinstance(bulk_bytes, bool) or not 1024 <= bulk_bytes <= 1024 * 1024:
        raise ValueError("bulk_bytes must be within 1024..1048576")
    if not isinstance(interactive_requests, int) or isinstance(interactive_requests, bool) or not 1 <= interactive_requests <= 100:
        raise ValueError("interactive_requests must be within 1..100")
    if not isinstance(request_bytes, int) or isinstance(request_bytes, bool) or not 16 <= request_bytes <= 4096:
        raise ValueError("request_bytes must be within 16..4096")
    if not isinstance(request_gap_ms, (int, float)) or isinstance(request_gap_ms, bool) or not 0 <= request_gap_ms <= 1000:
        raise ValueError("request_gap_ms must be within 0..1000")
    if not isinstance(stagger_after_ms, (int, float)) or isinstance(stagger_after_ms, bool) or not 0 <= stagger_after_ms <= 5000:
        raise ValueError("stagger_after_ms must be within 0..5000")
    if not isinstance(write_chunk_bytes, int) or isinstance(write_chunk_bytes, bool) or not 1 <= write_chunk_bytes <= STREAM_WRITE_MAX_BYTES:
        raise ValueError(f"write_chunk_bytes must be within 1..{STREAM_WRITE_MAX_BYTES}")
    if not isinstance(pipeline_depth, int) or isinstance(pipeline_depth, bool) or not 1 <= pipeline_depth <= 4:
        raise ValueError("pipeline_depth must be within 1..4")
    if not isinstance(fair_write_scheduling, bool):
        raise ValueError("fair_write_scheduling must be a boolean")
    if (
        not isinstance(window_update_batch_bytes, int)
        or isinstance(window_update_batch_bytes, bool)
        or not 1 <= window_update_batch_bytes <= MAX_STREAM_WINDOW_BYTES
    ):
        raise ValueError(f"window_update_batch_bytes must be within 1..{MAX_STREAM_WINDOW_BYTES}")
    if (
        not isinstance(window_update_max_delay_seconds, (int, float))
        or isinstance(window_update_max_delay_seconds, bool)
        or not math.isfinite(window_update_max_delay_seconds)
        or not 0 < window_update_max_delay_seconds <= 1.0
    ):
        raise ValueError("window_update_max_delay_seconds must be finite and within (0, 1.0]")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    nodes: list[RelayNode] = []
    relay_servers: list[asyncio.AbstractServer] = []
    proxies: list[TcpImpairmentProxy] = []
    destination_server: asyncio.AbstractServer | None = None
    # Keep detailed instrumentation opt-in for general clients, but enable it
    # in this research benchmark so the A/B comparison can explain latency.
    client = TelescopingClient(
        max_active_streams=8,
        fair_write_scheduling=fair_write_scheduling,
        window_update_batch_bytes=window_update_batch_bytes,
        window_update_max_delay_seconds=window_update_max_delay_seconds,
        collect_write_metrics=True,
    )
    destination_port = 0
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
        shaped = replace(profile, seed=profile.seed + seed + offset * 1_000_033)
        proxy = TcpImpairmentProxy("127.0.0.1", target_port, shaped)
        await proxy.start()
        proxies.append(proxy)
        return proxy

    async def close_stream_quietly(stream: Any) -> None:
        try:
            await stream.close()
        except (ConnectionError, OSError, RuntimeError, ValueError):
            pass

    try:
        destination_server = await asyncio.start_server(echo_handler, "127.0.0.1", 0)
        echo_port = int(destination_server.sockets[0].getsockname()[1])
        for _ in range(3):
            node = RelayNode(
                identity_digest=__import__("os").urandom(20),
                onion_private_key=X25519PrivateKey.generate(),
                collect_relay_metrics=True,
            )
            relay_servers.append(await serve_node(node))
            nodes.append(node)

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
        circuit_start_ns = time.perf_counter_ns()
        await client.connect_guard(descriptors[0])
        await client.extend(descriptors[1])
        await client.extend(descriptors[2])
        circuit_build_ms = (time.perf_counter_ns() - circuit_start_ns) / 1_000_000

        # Give each stream a deterministic but distinct payload so the echo path
        # can be checked without adding any assumptions about packet boundaries.
        bulk_payload = bytes(((i * 37 + seed) & 0xFF) for i in range(bulk_bytes))
        request_payloads = [
            bytes((((i + 1) * 19 + j * 13 + seed) & 0xFF) for j in range(request_bytes))
            for i in range(interactive_requests)
        ]
        early_stream, bulk_stream = await asyncio.gather(
            client.open_stream("127.0.0.1", destination_port),
            client.open_stream("127.0.0.1", destination_port),
        )
        bulk_done = asyncio.Event()
        bulk_started_at: float | None = None
        bulk_first_byte_ms: float | None = None
        bulk_elapsed_ms = 0.0
        bulk_returned = bytearray()

        async def bulk_flow() -> dict[str, Any]:
            nonlocal bulk_started_at, bulk_first_byte_ms, bulk_elapsed_ms
            bulk_started_at = time.perf_counter()
            async def sender() -> None:
                await bulk_stream.write_pipelined(
                    bulk_payload,
                    chunk_bytes=write_chunk_bytes,
                    max_in_flight=pipeline_depth,
                )
                await bulk_stream.write_eof()

            async def receiver() -> None:
                nonlocal bulk_first_byte_ms
                while True:
                    block = await bulk_stream.read_chunk()
                    if not block:
                        break
                    if bulk_first_byte_ms is None:
                        bulk_first_byte_ms = (time.perf_counter() - (bulk_started_at or time.perf_counter())) * 1000
                    bulk_returned.extend(block)

            try:
                await asyncio.gather(sender(), receiver())
                bulk_elapsed_ms = (time.perf_counter() - (bulk_started_at or time.perf_counter())) * 1000
                return {
                    "bytes_sent": len(bulk_payload),
                    "bytes_returned": len(bulk_returned),
                    "integrity_verified": bytes(bulk_returned) == bulk_payload,
                    "time_to_first_byte_ms": bulk_first_byte_ms,
                    "completion_ms": bulk_elapsed_ms,
                    "goodput_mbps": (len(bulk_payload) * 8 / (bulk_elapsed_ms / 1000) / 1_000_000) if bulk_elapsed_ms else 0.0,
                }
            finally:
                bulk_done.set()
                await close_stream_quietly(bulk_stream)

        async def interactive_flow(stream: Any, payloads: list[bytes]) -> dict[str, Any]:
            started = time.perf_counter()
            rtts: list[float] = []
            returned = bytearray()
            expected = bytearray()
            try:
                for request_index, request in enumerate(payloads):
                    request_started = time.perf_counter()
                    await stream.write(request)
                    response = await stream.read_chunk()
                    latency_ms = (time.perf_counter() - request_started) * 1000
                    if not response:
                        raise ConnectionError("interactive stream reached EOF before echo response")
                    rtts.append(latency_ms)
                    returned.extend(response)
                    expected.extend(request)
                    if request_gap_ms and request_index + 1 < len(payloads):
                        await asyncio.sleep(request_gap_ms / 1000)
                await stream.write_eof()
                while True:
                    extra = await stream.read_chunk()
                    if not extra:
                        break
                    returned.extend(extra)
                elapsed_ms = (time.perf_counter() - started) * 1000
                return {
                    "requests": len(payloads),
                    "request_bytes": len(payloads[0]) if payloads else 0,
                    "bytes_expected": len(expected),
                    "bytes_returned": len(returned),
                    "integrity_verified": bytes(returned) == bytes(expected),
                    "first_response_rtt_ms": rtts[0] if rtts else None,
                    "request_rtt_p50_ms": statistics.median(rtts) if rtts else 0.0,
                    "request_rtt_p95_ms": _percentile(rtts, 0.95),
                    "completion_ms": elapsed_ms,
                }
            finally:
                await close_stream_quietly(stream)

        overall_started = time.perf_counter()
        bulk_task = asyncio.create_task(bulk_flow(), name="aegis-bulk-flow")
        early_task = asyncio.create_task(interactive_flow(early_stream, request_payloads), name="aegis-early-interactive")

        async def staggered_flow() -> dict[str, Any]:
            await asyncio.sleep(stagger_after_ms / 1000)
            start_offset_ms = (time.perf_counter() - overall_started) * 1000
            bulk_was_active_at_open = not bulk_done.is_set()
            open_started = time.perf_counter()
            stream = await client.open_stream("127.0.0.1", destination_port)
            open_ms = (time.perf_counter() - open_started) * 1000
            result = await interactive_flow(stream, request_payloads)
            result["stream_open_ms"] = open_ms
            result["bulk_active_when_open_started"] = bulk_was_active_at_open
            result["start_offset_ms"] = start_offset_ms
            return result

        late_task = asyncio.create_task(staggered_flow(), name="aegis-staggered-interactive")
        try:
            bulk_result, early_result, late_result = await asyncio.wait_for(
                asyncio.gather(bulk_task, early_task, late_task), timeout=60.0
            )
        except Exception:
            for task in (bulk_task, early_task, late_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(bulk_task, early_task, late_task, return_exceptions=True)
            raise
        overall_ms = (time.perf_counter() - overall_started) * 1000

        await client.close()
        # Wait for server-side teardown before looking at counters or allowing
        # the asyncio loop to close. Failures remain visible in result checks.
        for _ in range(300):
            if (
                all(node.active_connections == 0 for node in nodes)
                and len(client._active_duplex_streams) == 0
                and all(proxy.metrics.active_connections == 0 for proxy in proxies)
            ):
                break
            await asyncio.sleep(0.01)

        integrity_verified = bool(
            bulk_result["integrity_verified"]
            and early_result["integrity_verified"]
            and late_result["integrity_verified"]
        )
        relay_observability_check = (
            sum(event.operation == "stream_open" for event in nodes[-1].observations) >= 3
            and all(event.target_port != destination_port for node in nodes[:2] for event in node.observations)
        )
        resources_closed = (
            all(node.active_connections == 0 for node in nodes)
            and len(client._active_duplex_streams) == 0
            and all(proxy.metrics.active_connections == 0 for proxy in proxies)
        )
        benchmark_result = {
            "schema_version": 2,
            "metadata": {
                "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
                "version": __version__,
                "experiment": "mixed bulk and interactive traffic with a staggered stream and relay-stage diagnostics",
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "loopback_only": True,
                "real_wan_measurement": False,
                "packet_loss_simulation": False,
                "production_congestion_test": False,
                "warning": "Results characterize only this local implementation and shaped TCP byte streams; they do not prove real-WAN performance or anonymity.",
            },
            "config": {
                "profile": profile.name,
                "hop_count": 3,
                "bulk_bytes": bulk_bytes,
                "interactive_requests_per_flow": interactive_requests,
                "request_bytes": request_bytes,
                "request_gap_ms": request_gap_ms,
                "stagger_after_ms": stagger_after_ms,
                "write_chunk_bytes": write_chunk_bytes,
                "pipeline_depth": pipeline_depth,
                "fair_write_scheduling": fair_write_scheduling,
                "window_update_batch_bytes": window_update_batch_bytes,
                "window_update_max_delay_ms": window_update_max_delay_seconds * 1000.0,
                "seed": seed,
            },
            "results": {
                "circuit_build_ms": circuit_build_ms,
                "overall_elapsed_ms": overall_ms,
                "bulk": bulk_result,
                "early_interactive": early_result,
                "staggered_interactive": late_result,
                "staggered_flow_started_while_bulk_active": late_result["bulk_active_when_open_started"],
                "integrity_verified": integrity_verified,
                "relay_observability_check": relay_observability_check,
                "all_relay_connections_closed": all(node.active_connections == 0 for node in nodes),
                "active_proxy_connections_after_close": [proxy.metrics.active_connections for proxy in proxies],
                "resources_closed": resources_closed,
                "destination_connections": destination_connections,
                "proxy_rejected_connections": sum(proxy.metrics.rejected_connections for proxy in proxies),
                "write_diagnostics": client.write_metrics_snapshot(),
                "relay_stage_diagnostics": [
                    {"hop": index + 1, **node.relay_metrics_snapshot()}
                    for index, node in enumerate(nodes)
                ],
            },
            "interpretation": [
                "Interactive first-response RTT is measured from immediately before a request write until the corresponding echo bytes are read; it is not measured from circuit creation.",
                "Bulk time-to-first-byte begins when the bulk flow starts, after the circuit and streams are opened.",
                "A late-flow start only represents contention during bulk transfer when staggered_flow_started_while_bulk_active is true.",
                "Relay diagnostics measure command dispatch, downstream-response waits, event/reply sends, destination reads/writes, and flow-credit waits; they are opt-in and add some instrumentation overhead.",
                "All flows are finite; this is not a long-lived congestion-control or steady-state fairness proof.",
            ],
            "limitations": [
                "Relays, proxies and echo destination run on one host via IPv4 loopback.",
                "The proxy shapes TCP byte-stream chunks and does not emulate IP packet loss or retransmissions.",
                "The circuit protocol is custom, experimental and not independently cryptographically audited.",
            ],
        }
        if not (integrity_verified and relay_observability_check and resources_closed):
            raise RuntimeError("mixed-workload integrity, relay observability, or resource cleanup check failed")
        return benchmark_result
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


async def run_mixed_scheduler_comparison(
    *,
    profile_name: str = "metro",
    trials: int = 3,
    bulk_bytes: int = 512 * 1024,
    interactive_requests: int = 8,
    request_bytes: int = 128,
    request_gap_ms: float = 15.0,
    stagger_after_ms: float = 60.0,
    write_chunk_bytes: int = 16 * 1024,
    pipeline_depth: int = 4,
    window_update_batch_bytes: int = WINDOW_UPDATE_BATCH_BYTES,
    window_update_max_delay_seconds: float = WINDOW_UPDATE_MAX_DELAY_SECONDS,
    seed: int = 20261023,
) -> dict[str, Any]:
    if profile_name not in DEFAULT_PROFILES:
        raise ValueError("profile_name must identify a named impairment profile")
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 10:
        raise ValueError("trials must be within 1..10")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if (
        not isinstance(window_update_batch_bytes, int)
        or isinstance(window_update_batch_bytes, bool)
        or not 1 <= window_update_batch_bytes <= MAX_STREAM_WINDOW_BYTES
    ):
        raise ValueError(f"window_update_batch_bytes must be within 1..{MAX_STREAM_WINDOW_BYTES}")
    if (
        not isinstance(window_update_max_delay_seconds, (int, float))
        or isinstance(window_update_max_delay_seconds, bool)
        or not math.isfinite(window_update_max_delay_seconds)
        or not 0 < window_update_max_delay_seconds <= 1.0
    ):
        raise ValueError("window_update_max_delay_seconds must be finite and within (0, 1.0]")
    rows: list[dict[str, Any]] = []
    order_by_trial: list[list[str]] = []
    base_profile = DEFAULT_PROFILES[profile_name]
    for trial in range(trials):
        order = ["baseline", "round_robin"] if trial % 2 == 0 else ["round_robin", "baseline"]
        order_by_trial.append(order)
        # Use the same per-trial seed for both modes so the configured shaper
        # randomness is matched; alternate execution order to reduce drift.
        run_seed = seed + trial * 1_000_003
        for scheduler in order:
            profile = replace(base_profile, seed=base_profile.seed + run_seed % 1_000_000_007)
            run = await run_mixed_workload_benchmark(
                profile=profile,
                bulk_bytes=bulk_bytes,
                interactive_requests=interactive_requests,
                request_bytes=request_bytes,
                request_gap_ms=request_gap_ms,
                stagger_after_ms=stagger_after_ms,
                write_chunk_bytes=write_chunk_bytes,
                pipeline_depth=pipeline_depth,
                fair_write_scheduling=scheduler == "round_robin",
                window_update_batch_bytes=window_update_batch_bytes,
                window_update_max_delay_seconds=window_update_max_delay_seconds,
                seed=run_seed,
            )
            r = run["results"]
            rows.append({
                "trial": trial + 1,
                "scheduler": scheduler,
                "seed": run_seed,
                "bulk_goodput_mbps": r["bulk"]["goodput_mbps"],
                "bulk_time_to_first_byte_ms": r["bulk"]["time_to_first_byte_ms"],
                "bulk_completion_ms": r["bulk"]["completion_ms"],
                "early_interactive_first_response_rtt_ms": r["early_interactive"]["first_response_rtt_ms"],
                "early_interactive_rtt_p50_ms": r["early_interactive"]["request_rtt_p50_ms"],
                "early_interactive_rtt_p95_ms": r["early_interactive"]["request_rtt_p95_ms"],
                "early_interactive_completion_ms": r["early_interactive"]["completion_ms"],
                "late_interactive_first_response_rtt_ms": r["staggered_interactive"]["first_response_rtt_ms"],
                "late_interactive_rtt_p50_ms": r["staggered_interactive"]["request_rtt_p50_ms"],
                "late_interactive_rtt_p95_ms": r["staggered_interactive"]["request_rtt_p95_ms"],
                "late_interactive_completion_ms": r["staggered_interactive"]["completion_ms"],
                "late_flow_started_while_bulk_active": r["staggered_flow_started_while_bulk_active"],
                "integrity_verified": r["integrity_verified"],
                "relay_observability_check": r["relay_observability_check"],
                "resources_closed": r["resources_closed"],
                "write_diagnostics": r["write_diagnostics"],
                "relay_stage_diagnostics": r["relay_stage_diagnostics"],
            })

    def median_for(scheduler: str, key: str) -> float:
        values = [float(row[key]) for row in rows if row["scheduler"] == scheduler and row[key] is not None]
        return float(statistics.median(values)) if values else 0.0

    keys = [
        "bulk_goodput_mbps", "bulk_time_to_first_byte_ms", "bulk_completion_ms",
        "early_interactive_first_response_rtt_ms", "early_interactive_rtt_p50_ms",
        "early_interactive_rtt_p95_ms", "early_interactive_completion_ms",
        "late_interactive_first_response_rtt_ms", "late_interactive_rtt_p50_ms",
        "late_interactive_rtt_p95_ms", "late_interactive_completion_ms",
    ]
    summary: dict[str, Any] = {}
    for key in keys:
        baseline = median_for("baseline", key)
        round_robin = median_for("round_robin", key)
        summary[key] = {
            "baseline_median": baseline,
            "round_robin_median": round_robin,
            "round_robin_delta_percent": ((round_robin / baseline) - 1) * 100 if baseline else None,
        }
    return {
        "schema_version": 2,
        "metadata": {
            "project": "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab",
            "version": __version__,
            "experiment": "mixed-workload A/B comparison with per-hop relay-stage diagnostics",
            "loopback_only": True,
            "real_wan_measurement": False,
            "production_congestion_test": False,
            "note": "Positive deltas mean higher values. For latency/completion metrics, negative deltas are generally better. Medians across small finite-flow samples are exploratory only.",
        },
        "config": {
            "profile": profile_name,
            "trials_per_scheduler": trials,
            "bulk_bytes": bulk_bytes,
            "interactive_requests": interactive_requests,
            "request_bytes": request_bytes,
            "request_gap_ms": request_gap_ms,
            "stagger_after_ms": stagger_after_ms,
            "write_chunk_bytes": write_chunk_bytes,
            "pipeline_depth": pipeline_depth,
            "window_update_batch_bytes": window_update_batch_bytes,
            "window_update_max_delay_ms": window_update_max_delay_seconds * 1000.0,
            "seed": seed,
            "paired_seed_policy": "same seed for baseline and round-robin within each trial; condition order alternates",
            "order_by_trial": order_by_trial,
        },
        "summary": summary,
        "runs": rows,
        "all_integrity_and_cleanup_checks_passed": all(
            row["integrity_verified"] and row["relay_observability_check"] and row["resources_closed"]
            for row in rows
        ),
        "all_late_flows_started_during_bulk": all(row["late_flow_started_while_bulk_active"] for row in rows),
        "limitations": [
            "Single-host IPv4 loopback; not a real WAN or packet-loss simulator.",
            "No global observer, anonymity or production security claim is tested.",
            "Finite flows; results do not prove steady-state scheduler fairness.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare AEGIS schedulers under mixed bulk and interactive load")
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="metro")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--bulk-bytes", type=int, default=512 * 1024)
    parser.add_argument("--interactive-requests", type=int, default=8)
    parser.add_argument("--request-bytes", type=int, default=128)
    parser.add_argument("--request-gap-ms", type=float, default=15.0)
    parser.add_argument("--stagger-after-ms", type=float, default=60.0)
    parser.add_argument("--write-chunk-bytes", type=int, default=16 * 1024)
    parser.add_argument("--pipeline-depth", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--window-update-batch-bytes", type=int, default=WINDOW_UPDATE_BATCH_BYTES)
    parser.add_argument("--window-update-max-delay-ms", type=float, default=WINDOW_UPDATE_MAX_DELAY_SECONDS * 1000.0)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_mixed_scheduler_comparison(
        profile_name=args.profile,
        trials=args.trials,
        bulk_bytes=args.bulk_bytes,
        interactive_requests=args.interactive_requests,
        request_bytes=args.request_bytes,
        request_gap_ms=args.request_gap_ms,
        stagger_after_ms=args.stagger_after_ms,
        write_chunk_bytes=args.write_chunk_bytes,
        pipeline_depth=args.pipeline_depth,
        window_update_batch_bytes=args.window_update_batch_bytes,
        window_update_max_delay_seconds=args.window_update_max_delay_ms / 1000.0,
        seed=args.seed,
    ))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
