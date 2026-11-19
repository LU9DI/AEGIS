"""Isolated dispatch/batching laboratory for the AEGIS telescoping client.

Purpose (THOR phase P1): find out, by measurement, whether batching and a leaner
dispatch core recover meaningful goodput on the current Python path, without
touching the protocol, the cryptography, the authentication or the admission
controls.

Design rules:

* The baseline (``control``) is the unmodified :class:`anonlab.telescoping.TelescopingClient`.
  Every variant is a *subclass* that overrides only the client-side send loop.
* Relay nodes, framing, AEAD, sequences, stream IDs, admission limits, ACK
  validation and failure semantics are unchanged: a variant that changed any of
  them would not be measuring dispatch.
* No key material is cached. The only cache is the public associated-data string
  (``prefix + relay_id``), which is already part of the cleartext construction.
* Variants are selected by a lab configuration object and are never the default.

Variants:

``io_batch``
    Encode the whole batch into one byte buffer and issue a single socket write
    plus one drain, instead of one write per command.
``lean_dispatch``
    Remove per-command dictionary allocations and per-command AAD rebuilding in
    the encode and decode loops, deriving per-hop sequences arithmetically from
    the batch base sequence.
``combined``
    Both of the above.

What this module cannot fix, and states explicitly: the relay-side hot loop still
processes one command at a time with its own per-command timer and task. Client
batching therefore amortises client-side dispatch only; the profile report
records the measured share so the next phase is chosen by evidence.
"""
from __future__ import annotations

import asyncio
import contextlib
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..telescoping import (
    FORWARD_WRITE_STREAM,
    MAX_COMMANDS_PER_CIRCUIT,
    MAX_PIPELINE_DEPTH,
    REQUEST_AAD_PREFIX,
    STREAM_WRITE_MAX_BYTES,
    _COMMAND_HEADER,
    _aad,
    _encode_forward,
    _encode_stream_write_body,
    _open_reply,
    frame,
    seal,
)

__all__ = [
    "DISPATCH_VARIANTS",
    "DispatchVariant",
    "PrimitiveCosts",
    "PrimitiveCounters",
    "build_lab_client_class",
    "count_aead_ops",
    "count_primitives",
    "measure_primitive_costs",
]


@dataclass(frozen=True, slots=True)
class DispatchVariant:
    """Lab switch for the client send loop; ``control`` is the current code."""

    name: str
    io_batch: bool = False
    lean_dispatch: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "variant": self.name,
            "io_batch": self.io_batch,
            "lean_dispatch": self.lean_dispatch,
        }


DISPATCH_VARIANTS: dict[str, DispatchVariant] = {
    "control": DispatchVariant("control"),
    "io_batch": DispatchVariant("io_batch", io_batch=True),
    "lean_dispatch": DispatchVariant("lean_dispatch", lean_dispatch=True),
    "combined": DispatchVariant("combined", io_batch=True, lean_dispatch=True),
}


@dataclass(slots=True)
class PrimitiveCounters:
    """How many asyncio primitives the real path created or used in one workload."""

    futures_created: int = 0
    wait_for_calls: int = 0
    gather_calls: int = 0
    lock_acquires: int = 0
    loop_iterations: int = 0
    timeout_contexts: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "futures_created": self.futures_created,
            "wait_for_calls": self.wait_for_calls,
            "gather_calls": self.gather_calls,
            "lock_acquires": self.lock_acquires,
            "loop_iterations": self.loop_iterations,
            "timeout_contexts": self.timeout_contexts,
        }


@dataclass(slots=True)
class _CountersState:
    counters: PrimitiveCounters = field(default_factory=PrimitiveCounters)
    active: bool = False


@contextlib.contextmanager
def count_primitives() -> Iterator[PrimitiveCounters]:
    """Count asyncio primitives created/used by the code running in this block.

    This patches module-level entry points for the duration of the block, so it
    is a *profiling* instrument: used only by the lab profiler, restored on exit,
    and it never changes the semantics of the wrapped calls. Counting is
    process-wide on purpose: the relay nodes of the lab testbed live in the same
    process, and their per-command primitives are part of the cost being studied.
    """
    state = _CountersState(active=True)
    loop = asyncio.get_running_loop()

    original_wait_for = asyncio.wait_for
    original_gather = asyncio.gather
    original_timeout = asyncio.timeout
    original_create_future = loop.create_future
    original_lock_acquire = asyncio.Lock.acquire
    original_run_once = getattr(loop, "_run_once", None)

    async def wait_for_wrapper(fut: Any, timeout: Any) -> Any:
        state.counters.wait_for_calls += 1
        return await original_wait_for(fut, timeout)

    def gather_wrapper(*aws: Any, **kwargs: Any) -> Any:
        state.counters.gather_calls += 1
        return original_gather(*aws, **kwargs)

    def timeout_wrapper(delay: Any) -> Any:
        state.counters.timeout_contexts += 1
        return original_timeout(delay)

    def create_future_wrapper() -> Any:
        state.counters.futures_created += 1
        return original_create_future()

    async def lock_acquire_wrapper(lock_self: Any) -> Any:
        state.counters.lock_acquires += 1
        return await original_lock_acquire(lock_self)

    def run_once_wrapper(*args: Any, **kwargs: Any) -> Any:
        state.counters.loop_iterations += 1
        return original_run_once(*args, **kwargs)

    asyncio.wait_for = wait_for_wrapper  # type: ignore[assignment]
    asyncio.gather = gather_wrapper  # type: ignore[assignment]
    asyncio.timeout = timeout_wrapper  # type: ignore[assignment]
    loop.create_future = create_future_wrapper  # type: ignore[assignment]
    asyncio.Lock.acquire = lock_acquire_wrapper  # type: ignore[assignment]
    if original_run_once is not None:
        loop._run_once = run_once_wrapper  # type: ignore[attr-defined]
    try:
        yield state.counters
    finally:
        state.active = False
        asyncio.wait_for = original_wait_for  # type: ignore[assignment]
        asyncio.gather = original_gather  # type: ignore[assignment]
        asyncio.timeout = original_timeout  # type: ignore[assignment]
        loop.create_future = original_create_future  # type: ignore[assignment]
        asyncio.Lock.acquire = original_lock_acquire  # type: ignore[assignment]
        if original_run_once is not None:
            loop._run_once = original_run_once  # type: ignore[attr-defined]


@contextlib.contextmanager
def count_aead_ops() -> Iterator[dict[str, int]]:
    """Measure how much time the real path spends inside AEAD seal/open.

    ``telescoping`` resolves ``seal``/``open_sealed`` from its module globals at
    call time, but this module imports them by name, so both aliases must be
    wrapped or the variant's client-side seals would go uncounted. Patching the
    module attributes captures every relay and client AEAD operation of the live
    circuit without changing the protocol. Used only by the profiler.
    """
    from .. import telescoping as telescoping_module  # noqa: PLC0415 - avoid import at module load

    targets: list[tuple[Any, str, Any]] = [
        (telescoping_module, "seal", telescoping_module.seal),
        (telescoping_module, "open_sealed", telescoping_module.open_sealed),
    ]
    import sys as _sys  # noqa: PLC0415 - local to avoid a global import change

    lab_module = _sys.modules.get(__name__)
    if lab_module is not None:
        for attribute in ("seal", "open_sealed"):
            if hasattr(lab_module, attribute):
                targets.append((lab_module, attribute, getattr(lab_module, attribute)))

    stats: dict[str, int] = {"seal_calls": 0, "open_calls": 0, "seal_ns": 0, "open_ns": 0}

    def _wrap(original: Any, kind: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter_ns()
            result = original(*args, **kwargs)
            stats[f"{kind}_ns"] += time.perf_counter_ns() - started
            stats[f"{kind}_calls"] += 1
            return result

        return wrapper

    originals = [(module, attribute, original) for module, attribute, original in targets]
    for module, attribute, original in originals:
        kind = "seal" if attribute == "seal" else "open"
        setattr(module, attribute, _wrap(original, kind))
    try:
        yield stats
    finally:
        for module, attribute, original in originals:
            setattr(module, attribute, original)


@dataclass(frozen=True, slots=True)
class PrimitiveCosts:
    """Per-operation cost of the asyncio primitives on this host and loop."""

    future_create_ns: float
    future_set_result_ns: float
    lock_acquire_ns: float
    wait_for_arm_disarm_ns: float
    gather_two_futures_ns: float
    monotonic_call_ns: float

    def to_dict(self) -> dict[str, float]:
        return {
            "future_create_ns": round(self.future_create_ns, 1),
            "future_set_result_ns": round(self.future_set_result_ns, 1),
            "lock_acquire_ns": round(self.lock_acquire_ns, 1),
            "wait_for_arm_disarm_ns": round(self.wait_for_arm_disarm_ns, 1),
            "gather_two_futures_ns": round(self.gather_two_futures_ns, 1),
            "monotonic_call_ns": round(self.monotonic_call_ns, 1),
        }


def _median(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[len(ordered) // 2]


async def _time_async(operation: Any, repeats: int) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        await operation()
        samples.append(time.perf_counter_ns() - started)
    return _median(samples)


async def measure_primitive_costs(*, repeats: int = 2000) -> PrimitiveCosts:
    """Measure the cost of each asyncio primitive used per command.

    ``wait_for_arm_disarm_ns`` uses an already-resolved future so the measured
    value is the timer bookkeeping, not a real wait.
    """
    if not 100 <= repeats <= 100_000:
        raise ValueError("repeats must be within 100..100000")
    loop = asyncio.get_running_loop()

    future_samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        future = loop.create_future()
        future_samples.append(time.perf_counter_ns() - started)
        future.cancel()

    resolve_samples: list[float] = []
    for _ in range(repeats):
        future = loop.create_future()
        started = time.perf_counter_ns()
        future.set_result(b"x")
        resolve_samples.append(time.perf_counter_ns() - started)

    lock = asyncio.Lock()

    async def acquire_release() -> None:
        async with lock:
            pass

    lock_ns = await _time_async(acquire_release, repeats)

    async def resolved_wait_for() -> None:
        future = loop.create_future()
        future.set_result(None)
        await asyncio.wait_for(future, timeout=10)

    wait_for_ns = await _time_async(resolved_wait_for, repeats)

    async def gather_resolved() -> None:
        futures = [loop.create_future(), loop.create_future()]
        for future in futures:
            future.set_result(None)
        await asyncio.gather(*futures)

    gather_ns = await _time_async(gather_resolved, repeats)

    monotonic_samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        time.monotonic()
        monotonic_samples.append(time.perf_counter_ns() - started)

    return PrimitiveCosts(
        future_create_ns=_median(future_samples),
        future_set_result_ns=_median(resolve_samples),
        lock_acquire_ns=lock_ns,
        wait_for_arm_disarm_ns=wait_for_ns,
        gather_two_futures_ns=gather_ns,
        monotonic_call_ns=_median(monotonic_samples),
    )


def build_lab_client_class(base: type) -> type:
    """Return a subclass of ``base`` (TelescopingClient) implementing variants."""

    class _LabDispatchClient(base):  # type: ignore[misc, valid-type]
        """Telescoping client with a selectable dispatch variant (lab only)."""

        def __init__(self, *, dispatch_variant: str = "control", **kwargs: Any) -> None:
            variant = DISPATCH_VARIANTS.get(dispatch_variant)
            if variant is None:
                raise ValueError(
                    f"unknown dispatch variant {dispatch_variant!r}; "
                    f"choose from {', '.join(sorted(DISPATCH_VARIANTS))}"
                )
            if variant.name != "control" and kwargs.get("fair_write_scheduling"):
                # The round-robin scheduler has its own send loop; a variant that
                # silently fell back to it would not be measuring the variant.
                raise ValueError("dispatch variants require fair_write_scheduling=False")
            super().__init__(**kwargs)
            self.dispatch_variant = variant
            self._lab_aad: dict[str, bytes] = {}

        def _lab_request_aad(self, relay_id: str) -> bytes:
            if not self.dispatch_variant.lean_dispatch:
                return _aad(REQUEST_AAD_PREFIX, relay_id)
            cached = self._lab_aad.get(relay_id)
            if cached is None:
                cached = _aad(REQUEST_AAD_PREFIX, relay_id)
                self._lab_aad[relay_id] = cached
            return cached

        def _lab_encode_batch(
            self, stream: Any, payloads: list[bytes]
        ) -> tuple[list[bytes], list[int]]:
            """Encode up to MAX_PIPELINE_DEPTH WRITE commands for one stream.

            Returns the frames to write and the per-hop base sequence of the batch.
            Each command advances every hop by exactly one, so hop *h* uses
            ``base[h] + index``; with ``lean_dispatch`` that identity replaces the
            per-command sequence/stream-id dictionaries. Relay and stream
            identifiers are immutable for the lifetime of a stream, so they are
            read directly instead of being copied per command.
            """
            hops = self.hops
            hop_count = len(hops)
            base_sequences = [hop.next_sequence for hop in hops]
            relay_ids = [hop.descriptor.relay_id for hop in hops]
            request_keys = [hop.keys.request_key for hop in hops]
            stream_ids = [stream.hop_stream_ids[relay_id] for relay_id in relay_ids]
            frames: list[bytes] = []
            batch_buffer = bytearray() if self.dispatch_variant.io_batch else None
            for index, payload in enumerate(payloads):
                last_index = hop_count - 1
                plaintext = (
                    _COMMAND_HEADER.pack(base_sequences[last_index] + index, stream_ids[last_index], ord("W"))
                    + _encode_stream_write_body(payload)
                )
                packet = seal(
                    request_keys[last_index],
                    plaintext,
                    self._lab_request_aad(relay_ids[last_index]),
                )
                for hop_index in range(hop_count - 2, -1, -1):
                    body = _encode_forward(
                        base_sequences[hop_index] + index,
                        stream_ids[hop_index],
                        base_sequences[hop_index + 1] + index,
                        stream_ids[hop_index + 1],
                        packet,
                        kind=FORWARD_WRITE_STREAM,
                    )
                    packet = seal(
                        request_keys[hop_index],
                        body,
                        self._lab_request_aad(relay_ids[hop_index]),
                    )
                if batch_buffer is not None:
                    batch_buffer.extend(struct.pack("!I", len(packet)))
                    batch_buffer.extend(packet)
                else:
                    frames.append(frame(packet))
            for hop_index, hop in enumerate(hops):
                hop.next_sequence = base_sequences[hop_index] + len(payloads)
            if batch_buffer is not None:
                frames = [bytes(batch_buffer)]
            return frames, base_sequences

        async def _send_duplex_write_batch_direct(
            self, stream: Any, payloads: list[bytes], *, timeout: float = 10.0,
        ) -> list[bytes]:
            """Variant-aware implementation of the baseline WRITE batch.

            Preserved from the prototype: per-hop sequences advance by exactly one
            per command, one drain per batch, ACKs correlated by
            (sequence, stream id), any send/ACK failure closes the circuit
            fail-closed, and cancellation during the ACK wait also closes it.
            """
            if not 1 <= len(payloads) <= MAX_PIPELINE_DEPTH:
                raise ValueError(f"write batch must contain 1..{MAX_PIPELINE_DEPTH} commands")
            for payload in payloads:
                if not isinstance(payload, bytes) or not 1 <= len(payload) <= STREAM_WRITE_MAX_BYTES:
                    raise ValueError(f"each pipelined write must contain 1..{STREAM_WRITE_MAX_BYTES} bytes")
            if self.dispatch_variant.name == "control":
                return await super()._send_duplex_write_batch_direct(stream, payloads, timeout=timeout)

            records: list[tuple[int, int, asyncio.Future[bytes]]] = []
            async with self._send_lock:
                await self._assert_circuit_usable_unlocked()
                if any(hop.next_sequence + len(payloads) > MAX_COMMANDS_PER_CIRCUIT for hop in self.hops):
                    await self._close_unlocked()
                    raise ValueError("pipeline would exceed the circuit command budget; rebuild the circuit")
                assert self._writer is not None
                try:
                    frames, base_sequences = self._lab_encode_batch(stream, payloads)
                    guard = self.hops[0]
                    guard_stream_id = stream.hop_stream_ids[guard.descriptor.relay_id]
                    for index in range(len(payloads)):
                        sequence = base_sequences[0] + index
                        records.append(
                            (sequence, guard_stream_id, self._register_pending(sequence, guard_stream_id))
                        )
                    for chunk in frames:
                        self._writer.write(chunk)
                    self._touch_activity()
                    await self._writer.drain()
                except BaseException:
                    for sequence, stream_id, future in records:
                        self._pending_replies.pop((sequence, stream_id), None)
                        if not future.done():
                            future.cancel()
                    await self._close_unlocked()
                    raise

            try:
                envelopes = await asyncio.wait_for(
                    asyncio.gather(*(future for _, _, future in records)), timeout=timeout
                )
                responses: list[bytes] = []
                # Each hop authenticates its own reply with the sequence and stream
                # identifier it observed for that command: hop h used
                # base_sequences[h] + index for sequence and the stream's per-hop id.
                for index, envelope in enumerate(envelopes):
                    response = envelope
                    for hop_index, hop in enumerate(self.hops):
                        relay_id = hop.descriptor.relay_id
                        response = _open_reply(
                            hop.keys.response_key,
                            relay_id,
                            base_sequences[hop_index] + index,
                            response,
                            stream.hop_stream_ids[relay_id],
                        )
                    responses.append(response)
                await self._check_after_stream_response()
                self._touch_activity()
                return responses
            except asyncio.CancelledError:
                await self._close_unlocked()
                raise
            except Exception:
                await self._close_unlocked()
                raise

    return _LabDispatchClient
