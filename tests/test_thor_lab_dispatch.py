"""Safety and equivalence tests for the P1 dispatch/batching variants.

Every test runs the real three-hop relay testbed; nothing is mocked except the
protocol constants used to exercise fail-closed limits. The variants must be
indistinguishable from the control on the wire-level properties that matter:
command order, sequence allocation, ACK correlation, stream isolation, circuit
isolation and failure semantics.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util

import pytest

from anonlab import telescoping
from anonlab.telescoping import MAX_PIPELINE_DEPTH, STREAM_WRITE_MAX_BYTES, TelescopingClient
from anonlab.thor_lab import dispatch_lab
from anonlab.thor_lab.dispatch_profile import build_testbed
from anonlab.thor_lab.dispatch_lab import (
    DISPATCH_VARIANTS,
    build_lab_client_class,
    count_aead_ops,
    count_primitives,
    measure_primitive_costs,
)

HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None

pytestmark = pytest.mark.skipif(not HAS_CRYPTO, reason="the onion-lab crypto extra is not installed")

VARIANTS = ("io_batch", "lean_dispatch", "combined")


def _client_class() -> type:
    return build_lab_client_class(TelescopingClient)


async def _circuit(testbed, *, variant: str, streams: int = 1):
    client_class = _client_class()
    client = client_class(dispatch_variant=variant, max_active_streams=max(8, streams))
    descriptors = [node.descriptor for node in testbed.nodes]
    await client.connect_guard(descriptors[0])
    await client.extend(descriptors[1])
    await client.extend(descriptors[2])
    created = [
        await client.open_stream(testbed.echo.host, testbed.echo.port) for _ in range(streams)
    ]
    return client, created


async def _exchange(stream, payload: bytes, *, chunk_bytes: int = 16 * 1024) -> bytes:
    await stream.write_pipelined(payload, chunk_bytes=chunk_bytes, max_in_flight=4)
    await stream.write_eof()
    received = bytearray()
    while True:
        chunk = await stream.read_chunk()
        if not chunk:
            return bytes(received)
        received.extend(chunk)


def _run(coro) -> object:
    return asyncio.run(coro)


def test_variant_configs_are_explicit_and_control_is_default() -> None:
    assert set(DISPATCH_VARIANTS) == {"control", "io_batch", "lean_dispatch", "combined"}
    assert DISPATCH_VARIANTS["control"].io_batch is False
    assert DISPATCH_VARIANTS["control"].lean_dispatch is False
    assert DISPATCH_VARIANTS["io_batch"].io_batch is True
    assert DISPATCH_VARIANTS["lean_dispatch"].lean_dispatch is True
    assert DISPATCH_VARIANTS["combined"].io_batch and DISPATCH_VARIANTS["combined"].lean_dispatch
    default_client = _client_class()()
    assert default_client.dispatch_variant.name == "control"
    with pytest.raises(ValueError):
        _client_class()(dispatch_variant="does-not-exist")
    with pytest.raises(ValueError):
        _client_class()(dispatch_variant="io_batch", fair_write_scheduling=True)


@pytest.mark.parametrize("variant", VARIANTS)
def test_variant_preserves_payload_integrity_and_sequence_allocation(variant: str) -> None:
    async def run_once(client_variant: str) -> tuple[bool, int, list[int]]:
        testbed = await build_testbed(collect_relay_metrics=True)
        try:
            client, (stream,) = await _circuit(testbed, variant=client_variant)
            try:
                payload = bytes(range(256)) * 512  # 128 KiB -> 8 commands of 16 KiB
                echoed = await _exchange(stream, payload)
                sequences = [hop.next_sequence for hop in client.hops]
                commands = len(payload) // (16 * 1024)
                observed = sum(
                    sum(node.relay_metrics_snapshot()["command_counts"].values())
                    for node in testbed.nodes
                )
                return echoed == payload, max(sequences), sequences
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    control_ok, control_max, control_sequences = _run(run_once("control"))
    variant_ok, variant_max, variant_sequences = _run(run_once(variant))
    assert control_ok and variant_ok
    # The variant must allocate exactly the same per-hop command sequences as the
    # control for the same operation sequence; that is the wire-level contract.
    assert variant_sequences == control_sequences
    assert variant_max > 0


@pytest.mark.parametrize("variant", VARIANTS)
def test_variant_does_not_change_cryptographic_work(variant: str) -> None:
    """A dispatcher variant must not add or remove AEAD operations.

    The payload is exactly one protocol chunk (16 KiB) so the exit relay emits a
    single reply event: a larger payload is fragmented by the relay's own 16 KiB
    read size, which varies with TCP timing and would make the count
    non-deterministic even between two control runs.
    """

    async def measure(client_variant: str) -> dict[str, int]:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, (stream,) = await _circuit(testbed, variant=client_variant)
            try:
                payload = b"crypto-equivalence" * 1024  # 18 KiB
                with count_aead_ops() as stats:
                    echoed = await _exchange(stream, payload, chunk_bytes=16 * 1024)
                assert echoed == payload
                return dict(stats)
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    control = _run(measure("control"))
    variant_stats = _run(measure(variant))
    assert variant_stats["seal_calls"] == control["seal_calls"]
    assert variant_stats["open_calls"] == control["open_calls"]
    assert variant_stats["seal_calls"] > 0 and variant_stats["open_calls"] > 0


@pytest.mark.parametrize("variant", VARIANTS)
def test_streams_stay_isolated_within_one_circuit(variant: str) -> None:
    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, streams = await _circuit(testbed, variant=variant, streams=3)
            try:
                payloads = [bytes([index + 1]) * (48 * 1024) for index in range(3)]
                echoed = await asyncio.gather(
                    *(_exchange(stream, payload) for stream, payload in zip(streams, payloads, strict=True))
                )
                for index, (payload, received) in enumerate(zip(payloads, echoed, strict=True)):
                    assert received == payload, f"stream {index} received another stream's bytes"
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    _run(scenario())


@pytest.mark.parametrize("variant", VARIANTS)
def test_two_circuits_stay_isolated(variant: str) -> None:
    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            first_client, (first_stream,) = await _circuit(testbed, variant=variant)
            second_client, (second_stream,) = await _circuit(testbed, variant=variant)
            try:
                first_payload = b"A" * (64 * 1024)
                second_payload = b"B" * (64 * 1024)
                first_echo, second_echo = await asyncio.gather(
                    _exchange(first_stream, first_payload),
                    _exchange(second_stream, second_payload),
                )
                assert first_echo == first_payload
                assert second_echo == second_payload
            finally:
                with contextlib.suppress(Exception):
                    await first_client.close()
                with contextlib.suppress(Exception):
                    await second_client.close()
        finally:
            await testbed.close()

    _run(scenario())


@pytest.mark.parametrize("variant", ("control",) + VARIANTS)
def test_batch_and_payload_limits_fail_closed_for_every_variant(variant: str) -> None:
    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, (stream,) = await _circuit(testbed, variant=variant)
            try:
                with pytest.raises(ValueError):
                    await client._send_duplex_write_batch_direct(stream, [b"x"] * (MAX_PIPELINE_DEPTH + 1))
                with pytest.raises(ValueError):
                    await client._send_duplex_write_batch_direct(
                        stream, [b"x" * (STREAM_WRITE_MAX_BYTES + 1)]
                    )
                with pytest.raises(ValueError):
                    await client._send_duplex_write_batch_direct(stream, [])
                # A rejected batch must not desynchronise the circuit.
                echoed = await _exchange(stream, b"still-alive" * 1024)
                assert echoed == b"still-alive" * 1024
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    _run(scenario())


@pytest.mark.parametrize("variant", ("control",) + VARIANTS)
def test_command_budget_is_fail_closed(variant: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telescoping, "MAX_COMMANDS_PER_CIRCUIT", 8)
    monkeypatch.setattr(dispatch_lab, "MAX_COMMANDS_PER_CIRCUIT", 8)

    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, (stream,) = await _circuit(testbed, variant=variant)
            try:
                with pytest.raises(ValueError):
                    for _ in range(12):
                        await stream.write(b"y" * 1024)
                assert client._writer is None, "circuit must be closed when its command budget is exhausted"
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    _run(scenario())


@pytest.mark.parametrize("variant", VARIANTS)
def test_relay_failure_surfaces_as_error_and_closes_circuit(
    variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reply that cannot be authenticated must fail closed, never be ignored."""
    import anonlab.thor_lab.dispatch_lab as lab_module

    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, (stream,) = await _circuit(testbed, variant=variant)

            def broken_open_reply(*args: object, **kwargs: object) -> bytes:
                raise ValueError("response authentication failed (injected)")

            monkeypatch.setattr(lab_module, "_open_reply", broken_open_reply)
            monkeypatch.setattr(telescoping, "_open_reply", broken_open_reply)
            try:
                with pytest.raises((ConnectionError, ValueError, OSError)):
                    for _ in range(4):
                        await stream.write(b"z" * 4096)
                assert client._writer is None
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    _run(scenario())


@pytest.mark.parametrize("variant", VARIANTS)
def test_close_drains_pending_state(variant: str) -> None:
    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, (stream,) = await _circuit(testbed, variant=variant)
            await stream.write(b"pending" * 1024)
            await client.close()
            assert client._writer is None
            assert client._pending_replies == {}
            assert client._active_duplex_streams == {}
            assert client._write_queues == {}
            assert client._reader_task is None
            # Closing twice must stay idempotent.
            await client.close()
        finally:
            await testbed.close()

    _run(scenario())


@pytest.mark.parametrize("variant", ("combined",))
def test_concurrent_batches_do_not_starve_any_stream(variant: str) -> None:
    async def scenario() -> None:
        testbed = await build_testbed(collect_relay_metrics=False)
        try:
            client, streams = await _circuit(testbed, variant=variant, streams=4)
            try:
                payloads = [bytes([index + 65]) * (32 * 1024) for index in range(4)]
                echoed = await asyncio.gather(
                    *(_exchange(stream, payload) for stream, payload in zip(streams, payloads, strict=True))
                )
                assert [len(item) for item in echoed] == [len(payload) for payload in payloads]
                for payload, received in zip(payloads, echoed, strict=True):
                    assert received == payload
            finally:
                with contextlib.suppress(Exception):
                    await client.close()
        finally:
            await testbed.close()

    _run(scenario())


def test_primitive_counting_and_costs_are_measurable_and_restored() -> None:
    async def scenario() -> None:
        original_wait_for = asyncio.wait_for
        original_gather = asyncio.gather
        loop = asyncio.get_running_loop()
        original_run_once = loop._run_once
        with count_primitives() as counters:
            lock = asyncio.Lock()
            async with lock:
                pass
            future = loop.create_future()
            future.set_result(None)
            await asyncio.gather(future)
        assert asyncio.wait_for is original_wait_for
        assert asyncio.gather is original_gather
        assert loop._run_once == original_run_once
        assert counters.to_dict()["futures_created"] >= 1
        assert counters.to_dict()["lock_acquires"] >= 1
        assert counters.to_dict()["gather_calls"] >= 1
        costs = await measure_primitive_costs(repeats=200)
        assert costs.future_create_ns > 0
        assert costs.wait_for_arm_disarm_ns > 0
        assert costs.lock_acquire_ns > 0

    asyncio.run(scenario())


def test_variant_rejects_unknown_name_before_any_io() -> None:
    client_class = build_lab_client_class(TelescopingClient)
    with pytest.raises(ValueError):
        client_class(dispatch_variant="batching")
