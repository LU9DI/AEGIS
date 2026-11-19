"""Security and isolation tests for the THOR P2 lab variants.

Every test drives the real telescope (real ntor handshakes, AEAD, links and
relays). Nothing here disables authentication, ACKs, credit checks or
backpressure: the variants only change sizes, thresholds and where an
acknowledgement is awaited.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import os
import time

import pytest

try:  # optional research dependency
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
except ImportError:  # pragma: no cover - exercised in the crypto-free environment
    X25519PrivateKey = None  # type: ignore[assignment,misc]

from anonlab.telescoping import (
    FORWARD_WINDOW_UPDATE,
    INITIAL_STREAM_WINDOW_BYTES,
    MAX_STREAM_WINDOW_BYTES,
    STREAM_CHUNK_BYTES,
    WINDOW_UPDATE_BATCH_BYTES,
    WINDOW_UPDATE_MAX_DELAY_SECONDS,
    RelayNode,
    TelescopingClient,
    _encode_window_update_body,
    serve_node,
)
from anonlab.thor_lab.appproto import start_echo_server
from anonlab.thor_p2_lab.runner import WORKLOADS, run_trial
from anonlab.thor_p2_lab.variants import VARIANTS, VariantSpec, variant_by_name

pytestmark = pytest.mark.skipif(
    X25519PrivateKey is None,
    reason="install aegis-anon-lab[onion-lab] for the real telescope path",
)


def _run(coro):
    return asyncio.run(coro)


class _Testbed:
    def __init__(self, echo, nodes, servers, client) -> None:
        self.echo = echo
        self.nodes = nodes
        self.servers = servers
        self.client = client

    async def close(self) -> None:
        await self.client.close()
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        await self.echo.close()


async def _build(*, client_options: dict | None = None,
                 relay_options: dict | None = None) -> _Testbed:
    echo = await start_echo_server()
    nodes: list[RelayNode] = []
    servers: list[asyncio.AbstractServer] = []
    for index in range(3):
        node = RelayNode(
            identity_digest=os.urandom(20),
            onion_private_key=X25519PrivateKey.generate(),
            **(relay_options or {}),
        )
        if index == 2:
            node.allowed_destinations.add((echo.host, echo.port))
        servers.append(await serve_node(node))
        nodes.append(node)
    client = TelescopingClient(**(client_options or {}))
    await client.connect_guard(nodes[0].descriptor)
    await client.extend(nodes[1].descriptor)
    await client.extend(nodes[2].descriptor)
    return _Testbed(echo, nodes, servers, client)


# --------------------------------------------------------------------------- #
# Registry and bounds
# --------------------------------------------------------------------------- #

def test_registry_changes_exactly_one_dimension_per_variant() -> None:
    from anonlab.thor_p2_lab.variants import assert_single_dimension

    assert_single_dimension()
    assert VARIANTS["control"].changed_dimensions() == ()
    for name, spec in VARIANTS.items():
        if name != "control":
            assert len(spec.changed_dimensions()) == 1, (name, spec.changed_dimensions())


def test_control_matches_the_production_defaults() -> None:
    control = VARIANTS["control"]
    assert control.credit_window_bytes == INITIAL_STREAM_WINDOW_BYTES
    assert control.credit_batch_bytes == WINDOW_UPDATE_BATCH_BYTES
    assert control.credit_delay_seconds == WINDOW_UPDATE_MAX_DELAY_SECONDS
    assert control.relay_read_chunk_bytes == STREAM_CHUNK_BYTES
    assert control.max_event_bytes == STREAM_CHUNK_BYTES
    assert control.credit_pipeline is False
    assert control.flush_floor_bytes == 0


def test_unknown_variant_is_rejected() -> None:
    with pytest.raises(ValueError):
        variant_by_name("no-such-variant")


@pytest.mark.parametrize(
    "overrides",
    [
        {"credit_window_bytes": MAX_STREAM_WINDOW_BYTES + 1},
        {"credit_window_bytes": INITIAL_STREAM_WINDOW_BYTES - 1},
        {"credit_window_bytes": True},
        {"max_event_bytes": 4096, "relay_read_chunk_bytes": 8192},
        {"relay_read_chunk_bytes": MAX_STREAM_WINDOW_BYTES + 1},
        {"flush_floor_bytes": 48 * 1024},
        {"credit_pipeline": "yes"},
    ],
)
def test_unsafe_variant_knobs_are_rejected(overrides: dict) -> None:
    base = VARIANTS["control"].to_dict()
    base.update(overrides)
    with pytest.raises(ValueError):
        VariantSpec(**base)


# --------------------------------------------------------------------------- #
# Credit accounting and fail-closed behaviour
# --------------------------------------------------------------------------- #

def test_over_credit_is_rejected_by_the_relay() -> None:
    """A peer that grants more than the stream window must be refused."""

    async def scenario() -> None:
        bed = await _build()
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            # 64 KiB initial + 256 KiB request exceeds the 256 KiB maximum.
            with pytest.raises(Exception):
                await bed.client._send_duplex_command(
                    stream, "V", _encode_window_update_body(MAX_STREAM_WINDOW_BYTES),
                    FORWARD_WINDOW_UPDATE, timeout=5,
                )
        finally:
            await bed.close()

    _run(scenario())


def test_window_update_flood_fails_closed_without_hanging() -> None:
    """Many credit updates cannot push the exit past its window or wedge it."""

    async def scenario() -> None:
        bed = await _build()
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            started = time.perf_counter()
            failures = 0
            for _ in range(6):
                try:
                    await bed.client._send_duplex_command(
                        stream, "V", _encode_window_update_body(MAX_STREAM_WINDOW_BYTES),
                        FORWARD_WINDOW_UPDATE, timeout=5,
                    )
                except Exception:
                    failures += 1
            assert failures >= 1, "the relay accepted credit beyond its window"
            assert time.perf_counter() - started < 30
        finally:
            await bed.close()

    _run(scenario())


def test_client_rejects_events_larger_than_its_bound() -> None:
    """A peer-forced oversized event must fail closed, not allocate unboundedly."""

    async def scenario() -> None:
        bed = await _build(client_options={"max_event_bytes": 1024})
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            payload = bytes(range(256)) * 256  # 64 KiB
            await stream.write_pipelined(payload, chunk_bytes=16 * 1024, max_in_flight=4)
            with pytest.raises(Exception):
                for _ in range(64):
                    chunk = await asyncio.wait_for(stream.read_chunk(), timeout=10)
                    if not chunk:
                        break
            assert len(stream._receive_buffer) <= MAX_STREAM_WINDOW_BYTES
        finally:
            await bed.close()

    _run(scenario())


def test_slow_consumer_backpressure_bounds_memory() -> None:
    """Writing without reading must not grow the client buffer past one window."""

    async def scenario() -> None:
        bed = await _build()
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            payload = os.urandom(64 * 1024)
            for _ in range(4):
                await stream.write_pipelined(payload, chunk_bytes=64 * 1024, max_in_flight=1)
            for _ in range(200):
                if len(stream._receive_buffer) >= INITIAL_STREAM_WINDOW_BYTES:
                    break
                await asyncio.sleep(0.01)
            assert len(stream._receive_buffer) <= MAX_STREAM_WINDOW_BYTES
        finally:
            await bed.close()

    _run(scenario())


def test_cancel_during_credit_wait_returns_promptly() -> None:
    """Closing a stream whose destination read is credit-blocked must not hang."""

    async def scenario() -> None:
        bed = await _build(client_options={"window_update_batch_bytes": 64 * 1024})
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            await stream.write_pipelined(os.urandom(64 * 1024), chunk_bytes=16 * 1024, max_in_flight=4)
            await asyncio.sleep(0.05)  # let the exit fill the window and block on credit
            started = time.perf_counter()
            await asyncio.wait_for(stream.close(), timeout=10)
            assert time.perf_counter() - started < 10
        finally:
            await bed.close()

    _run(scenario())


def test_circuit_loss_during_pipelined_credit_fails_closed() -> None:
    """With pipelined credit, losing the circuit surfaces an error, never success."""

    async def scenario() -> None:
        bed = await _build(client_options={"window_credit_pipeline": True})
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            payload = os.urandom(256 * 1024)
            writer = asyncio.create_task(
                stream.write_pipelined(payload, chunk_bytes=16 * 1024, max_in_flight=4)
            )
            await asyncio.sleep(0.02)
            await bed.client.close()
            # A lost circuit cancels in-flight work; both a transport error and
            # cancellation are fail-closed, a normal return would not be.
            with pytest.raises((Exception, asyncio.CancelledError)):
                await asyncio.wait_for(writer, timeout=10)
        finally:
            await bed.close()

    _run(scenario())


# --------------------------------------------------------------------------- #
# Isolation, ordering and integrity
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("variant_name", sorted(VARIANTS))
def test_variant_transfer_preserves_integrity_and_sequence(variant_name: str) -> None:
    """Each variant must deliver every byte, in order, for two concurrent streams."""

    async def scenario() -> None:
        variant = VARIANTS[variant_name]
        bed = await _build(
            client_options={
                "window_update_batch_bytes": variant.credit_batch_bytes,
                "window_update_max_delay_seconds": variant.credit_delay_seconds,
                "max_event_bytes": variant.max_event_bytes,
                "window_credit_pipeline": variant.credit_pipeline,
                "window_update_flush_floor_bytes": variant.flush_floor_bytes,
            },
            relay_options={"stream_read_chunk_bytes": variant.relay_read_chunk_bytes},
        )
        try:
            if variant.credit_window_bytes > INITIAL_STREAM_WINDOW_BYTES:
                for _ in range(2):
                    pass
            streams = [await bed.client.open_stream(bed.echo.host, bed.echo.port) for _ in range(2)]
            for stream in streams:
                extra = variant.credit_window_bytes - INITIAL_STREAM_WINDOW_BYTES
                if extra > 0:
                    reply = await bed.client._send_duplex_command(
                        stream, "V", _encode_window_update_body(extra), FORWARD_WINDOW_UPDATE,
                    )
                    assert reply == b"WINDOW_UPDATED"
            payloads = [os.urandom(48 * 1024), os.urandom(32 * 1024)]

            async def drive(stream, payload):
                received = bytearray()

                async def writer():
                    for start in range(0, len(payload), 16 * 1024):
                        await stream.write_pipelined(
                            payload[start:start + 16 * 1024], chunk_bytes=16 * 1024,
                            max_in_flight=4,
                        )
                    await stream.write_eof()

                async def reader():
                    while len(received) < len(payload):
                        chunk = await stream.read_chunk()
                        if not chunk:
                            break
                        received.extend(chunk)
                await asyncio.gather(writer(), reader())
                return bytes(received)

            results = await asyncio.wait_for(
                asyncio.gather(*(drive(s, p) for s, p in zip(streams, payloads, strict=True))),
                timeout=60,
            )
            for result, payload in zip(results, payloads, strict=True):
                assert hashlib.sha256(result).digest() == hashlib.sha256(payload).digest()
        finally:
            await bed.close()

    _run(scenario())


def test_streams_do_not_leak_bytes_across_each_other() -> None:
    """Two streams with distinct markers must never see the other's bytes."""

    async def scenario() -> None:
        bed = await _build()
        try:
            left = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            right = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            left_payload = b"A" * (32 * 1024)
            right_payload = b"B" * (32 * 1024)
            await asyncio.gather(
                left.write_pipelined(left_payload, chunk_bytes=16 * 1024, max_in_flight=4),
                right.write_pipelined(right_payload, chunk_bytes=16 * 1024, max_in_flight=4),
            )
            left_data = bytearray()
            right_data = bytearray()
            while len(left_data) < len(left_payload) or len(right_data) < len(right_payload):
                if len(left_data) < len(left_payload):
                    left_data.extend(await asyncio.wait_for(left.read_chunk(), timeout=10))
                if len(right_data) < len(right_payload):
                    right_data.extend(await asyncio.wait_for(right.read_chunk(), timeout=10))
            assert bytes(left_data) == left_payload
            assert bytes(right_data) == right_payload
        finally:
            await bed.close()

    _run(scenario())


def test_half_close_is_preserved_under_variants() -> None:
    """EOF semantics survive the event-size and ACK variants."""

    async def scenario() -> None:
        variant = VARIANTS["events-64k"]
        bed = await _build(
            client_options={"max_event_bytes": variant.max_event_bytes},
            relay_options={"stream_read_chunk_bytes": variant.relay_read_chunk_bytes},
        )
        try:
            stream = await bed.client.open_stream(bed.echo.host, bed.echo.port)
            payload = os.urandom(40 * 1024)
            await stream.write_pipelined(payload, chunk_bytes=16 * 1024, max_in_flight=4)
            await stream.write_eof()
            received = bytearray()
            while True:
                chunk = await asyncio.wait_for(stream.read_chunk(), timeout=10)
                if not chunk:
                    break
                received.extend(chunk)
            assert bytes(received) == payload
        finally:
            await bed.close()

    _run(scenario())


def test_lab_knobs_default_to_production_values() -> None:
    """The lab must not change the default path implicitly."""
    client = TelescopingClient()
    assert client.max_event_bytes == STREAM_CHUNK_BYTES
    assert client.window_credit_pipeline is False
    assert client.window_update_flush_floor_bytes == 0
    assert client.window_update_batch_bytes == WINDOW_UPDATE_BATCH_BYTES
    node = RelayNode(identity_digest=os.urandom(20), onion_private_key=X25519PrivateKey.generate())
    assert node.stream_read_chunk_bytes == STREAM_CHUNK_BYTES


class _StubNode:
    """Minimal node stub for relay-option validation tests."""


def test_relay_read_chunk_bounds_are_validated() -> None:
    with pytest.raises(ValueError):
        RelayNode(
            identity_digest=os.urandom(20),
            onion_private_key=X25519PrivateKey.generate(),
            stream_read_chunk_bytes=MAX_STREAM_WINDOW_BYTES + 1,
        )
    with pytest.raises(ValueError):
        RelayNode(
            identity_digest=os.urandom(20),
            onion_private_key=X25519PrivateKey.generate(),
            stream_read_chunk_bytes=0,
        )


def test_campaign_decision_requires_reproducible_gain() -> None:
    """The decision rule must reject an arm with only an isolated win."""
    from anonlab.thor_p2_lab.campaign import CampaignConfig, decide

    summary = {
        "cells": {"bulk_256k_c16k/credit-window-128k": {"integrity_verified": True}},
        "paired": {
            "bulk_256k_c16k/credit-window-128k": {
                "goodput_ratio": {"median": 1.4, "ci_low": 0.95, "ci_high": 1.9, "samples": 7},
                "read_latency_p95_ratio": {"median": 1.0, "ci_low": 0.9, "ci_high": 1.1, "samples": 7},
                "read_latency_p99_ratio": {"median": 1.0, "ci_low": 0.9, "ci_high": 1.1, "samples": 7},
            }
        },
    }
    config = CampaignConfig(arms=("control", "credit-window-128k"), workloads=("bulk_256k_c16k",), trials=7, warmups=0)
    decision = decide(summary, config)["credit-window-128k"]
    assert decision["accepted"] is False


def test_workload_definitions_cover_the_p1_p0_shapes() -> None:
    assert WORKLOADS["bulk_1mib_c16k"].total_bytes == 1024 * 1024
    assert WORKLOADS["bulk_256k_c16k"].total_bytes == 256 * 1024
    assert WORKLOADS["bulk_256k_c256k"].write_chunk_bytes == 256 * 1024
    assert WORKLOADS["parallel_8x64k"].streams == 8
    assert WORKLOADS["duplex_4x128cmd"].streams == 4
    assert WORKLOADS["duplex_4x128cmd"].commands_per_stream == 128


def test_full_trial_reports_integrity_and_bounded_waits() -> None:
    """One real trial end-to-end, checking the reported fields exist and are sane."""
    result = _run(run_trial(VARIANTS["credit-policy-window-aware"], WORKLOADS["bulk_256k_c16k"], seed=5))
    payload = result.payload
    assert result.ok
    assert payload["integrity"]["verified"] is True
    assert payload["transfer"]["goodput_mbps"] > 0
    assert payload["counts"]["window_update_count"] >= 0
    assert payload["counts"]["aead_ops_per_kib"] > 0
    assert payload["waits"]["flow_credit_wait_ms"] >= 0
    assert payload["resources"]["peak_rss_kb"] is None or payload["resources"]["peak_rss_kb"] > 0
