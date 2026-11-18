"""Deterministic workloads executed by the THOR lab arms.

Payloads are pseudorandom bytes derived from the run seed, so no real or
sensitive traffic is ever placed in a prototype or an artifact. Every workload
returns raw per-operation samples; aggregation happens in
:mod:`anonlab.thor_lab.metrics`, never here.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

from .appproto import http_get
from .backends import ByteStream
from .counting_proxy import CountingProxy

__all__ = ["PayloadFactory", "WorkloadOutcome", "WorkloadSpec", "run_workload"]

_KINDS = ("bulk_echo", "small_rtt", "parallel_bulk", "http_get")


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    """One workload shape; identical parameters are what make a ratio valid."""

    kind: str
    payload_bytes: int = 256 * 1024
    chunk_bytes: int = 16 * 1024
    operations: int = 1
    streams: int = 1
    max_in_flight: int = 4
    timeout_s: float = 120.0
    http_host: str | None = None
    http_path: str = "/"
    http_headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}")
        if not 1 <= int(self.payload_bytes) <= 64 * 1024 * 1024:
            raise ValueError("payload_bytes must be within 1..67108864")
        if not 1 <= int(self.chunk_bytes) <= 256 * 1024:
            raise ValueError("chunk_bytes must be within 1..262144")
        if not 1 <= int(self.operations) <= 10_000:
            raise ValueError("operations must be within 1..10000")
        if not 1 <= int(self.streams) <= 64:
            raise ValueError("streams must be within 1..64")
        if not 1 <= int(self.max_in_flight) <= 16:
            raise ValueError("max_in_flight must be within 1..16")
        if not 0.1 <= float(self.timeout_s) <= 3600.0:
            raise ValueError("timeout_s must be within 0.1..3600")
        if self.kind == "parallel_bulk" and self.streams < 2:
            raise ValueError("parallel_bulk requires streams >= 2")
        if self.kind == "http_get":
            if not self.http_host:
                raise ValueError("http_get requires http_host")
            if not self.http_path.startswith("/"):
                raise ValueError("http_path must start with '/'")
            for name, value in self.http_headers:
                if not name or any(char in name + value for char in "\r\n"):
                    raise ValueError("http headers must have a name and no CR/LF")
        elif self.http_host is not None or self.http_path != "/" or self.http_headers:
            raise ValueError("http_host/http_path/http_headers are only valid for http_get")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "payload_bytes": self.payload_bytes,
            "chunk_bytes": self.chunk_bytes,
            "operations": self.operations,
            "streams": self.streams,
            "max_in_flight": self.max_in_flight,
            "timeout_s": self.timeout_s,
            "http_host": self.http_host,
            "http_path": self.http_path,
            "http_headers": [list(item) for item in self.http_headers],
        }

    @property
    def label(self) -> str:
        """Stable identifier *including* the parameters that make a ratio valid.

        Two specifications with the same payload but different chunking are
        different measurements and must never be grouped together in a summary,
        so chunk size and in-flight depth are part of the label.
        """
        suffix = f"@c{self.chunk_bytes}i{self.max_in_flight}"
        if self.kind == "parallel_bulk":
            return f"{self.kind}:{self.streams}x{self.payload_bytes}{suffix}"
        if self.kind == "http_get":
            return f"{self.kind}:{self.operations}x{self.http_host}{self.http_path}"
        return f"{self.kind}:{self.payload_bytes}x{self.operations}{suffix}"


class PayloadFactory:
    """Seeded pseudorandom payloads; the same seed yields the same bytes."""

    def __init__(self, seed: int) -> None:
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError("seed must be an integer")
        self.seed = seed
        self._rng = random.Random(seed)

    def payload(self, size: int) -> bytes:
        if size < 0:
            raise ValueError("size must be non-negative")
        return self._rng.randbytes(size)


@dataclass(slots=True)
class WorkloadOutcome:
    ok: bool
    payload_bytes: int = 0
    received_bytes: int = 0
    integrity: bool | None = None
    total_ms: float = 0.0
    ttfb_ms: float | None = None
    goodput_mbps: float | None = None
    latency_ms: list[float] = field(default_factory=list)
    per_stream_ms: list[float] = field(default_factory=list)
    ttfb_samples_ms: list[float] = field(default_factory=list)
    http_status: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "payload_bytes": self.payload_bytes,
            "received_bytes": self.received_bytes,
            "integrity": self.integrity,
            "total_ms": round(self.total_ms, 4),
            "ttfb_ms": None if self.ttfb_ms is None else round(self.ttfb_ms, 4),
            "goodput_mbps": None if self.goodput_mbps is None else round(self.goodput_mbps, 4),
            "latency_ms": [round(value, 4) for value in self.latency_ms],
            "per_stream_ms": [round(value, 4) for value in self.per_stream_ms],
            "ttfb_samples_ms": [round(value, 4) for value in self.ttfb_samples_ms],
            "http_status": list(self.http_status),
        }


def _goodput_mbps(payload_bytes: int, elapsed_ms: float) -> float | None:
    if elapsed_ms <= 0:
        return None
    return (payload_bytes * 8) / (elapsed_ms / 1000.0) / 1_000_000.0


async def _read_exactly(stream: ByteStream, want: int, *, deadline: float) -> tuple[bytes, float | None]:
    """Read ``want`` bytes; return them and the time to the first byte in ms."""
    chunks: list[bytes] = []
    received = 0
    first_byte_ms: float | None = None
    started = time.perf_counter()
    while received < want:
        remaining_s = deadline - time.perf_counter()
        if remaining_s <= 0:
            raise TimeoutError("read deadline exceeded")
        chunk = await asyncio.wait_for(stream.read(min(64 * 1024, want - received)), timeout=remaining_s)
        if not chunk:
            raise ConnectionError("stream ended before the expected byte count")
        if first_byte_ms is None:
            first_byte_ms = (time.perf_counter() - started) * 1000.0
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks), first_byte_ms


async def _bulk(stream: ByteStream, payload: bytes, spec: WorkloadSpec, *, deadline: float) -> WorkloadOutcome:
    started = time.perf_counter()
    await asyncio.wait_for(
        stream.write_bulk(payload, chunk_bytes=spec.chunk_bytes, max_in_flight=spec.max_in_flight),
        timeout=max(0.1, deadline - time.perf_counter()),
    )
    written_ms = (time.perf_counter() - started) * 1000.0
    echoed, first_byte_ms = await asyncio.wait_for(
        _read_exactly(stream, len(payload), deadline=deadline), timeout=max(0.1, deadline - time.perf_counter())
    )
    total_ms = (time.perf_counter() - started) * 1000.0
    ttfb = None if first_byte_ms is None else written_ms + first_byte_ms
    return WorkloadOutcome(
        ok=True,
        payload_bytes=len(payload),
        received_bytes=len(echoed),
        integrity=echoed == payload,
        total_ms=total_ms,
        ttfb_ms=ttfb,
        goodput_mbps=_goodput_mbps(len(payload), total_ms),
    )


async def run_workload(
    connector,
    spec: WorkloadSpec,
    payload_factory: PayloadFactory,
    *,
    proxy: CountingProxy | None = None,
) -> WorkloadOutcome:
    """Run one workload against one arm.

    ``connector`` is an awaitable returning a fresh ``Connection``; it is called
    once per stream so ``parallel_bulk`` exercises independent connections.
    """
    if spec.kind == "bulk_echo":
        connection = await connector()
        try:
            payload = payload_factory.payload(spec.payload_bytes)
            deadline = time.perf_counter() + spec.timeout_s
            outcome = await _bulk(connection.stream, payload, spec, deadline=deadline)
            await _close_quietly(connection.stream)
            return outcome
        except BaseException:
            await _close_quietly(connection.stream)
            raise

    if spec.kind == "small_rtt":
        connection = await connector()
        try:
            payload = payload_factory.payload(spec.payload_bytes)
            latencies: list[float] = []
            integrity = True
            for _ in range(spec.operations):
                started = time.perf_counter()
                deadline = started + spec.timeout_s
                await asyncio.wait_for(
                    connection.stream.write_bulk(
                        payload, chunk_bytes=spec.chunk_bytes, max_in_flight=spec.max_in_flight
                    ),
                    timeout=max(0.1, deadline - time.perf_counter()),
                )
                echoed, _first = await asyncio.wait_for(
                    _read_exactly(connection.stream, len(payload), deadline=deadline),
                    timeout=max(0.1, deadline - time.perf_counter()),
                )
                latencies.append((time.perf_counter() - started) * 1000.0)
                integrity = integrity and echoed == payload
            total_ms = sum(latencies)
            await _close_quietly(connection.stream)
            return WorkloadOutcome(
                ok=True,
                payload_bytes=spec.payload_bytes * spec.operations,
                received_bytes=spec.payload_bytes * spec.operations,
                integrity=integrity,
                total_ms=total_ms,
                latency_ms=latencies,
                goodput_mbps=_goodput_mbps(spec.payload_bytes * spec.operations, total_ms),
            )
        except BaseException:
            await _close_quietly(connection.stream)
            raise

    if spec.kind == "http_get":
        assert spec.http_host is not None
        latency_ms: list[float] = []
        ttfb_samples: list[float] = []
        body_bytes = 0
        status_codes: list[int] = []
        checksums: list[str] = []
        for _ in range(spec.operations):
            connection = await connector()
            if connection.raw is None:
                await _close_quietly(connection.stream)
                raise ValueError("http_get requires a socket-backed arm")
            reader, writer = connection.raw
            try:
                result = await http_get(
                    reader,
                    writer,
                    host=spec.http_host,
                    path=spec.http_path,
                    timeout=spec.timeout_s,
                    extra_headers=dict(spec.http_headers) if spec.http_headers else None,
                )
            finally:
                await _close_quietly(connection.stream)
            if result.status >= 400:
                raise ConnectionError(f"HTTP status {result.status} {result.reason}".strip())
            latency_ms.append(result.total_ms)
            if result.first_body_byte_ms is not None:
                ttfb_samples.append(result.first_body_byte_ms)
            body_bytes += result.body_bytes
            status_codes.append(result.status)
            checksums.append(result.body_sha256)
        total_ms = sum(latency_ms)
        return WorkloadOutcome(
            ok=True,
            payload_bytes=body_bytes,
            received_bytes=body_bytes,
            integrity=len(set(checksums)) == 1,
            total_ms=total_ms,
            ttfb_ms=ttfb_samples[0] if ttfb_samples else None,
            goodput_mbps=_goodput_mbps(body_bytes, total_ms),
            latency_ms=latency_ms,
            ttfb_samples_ms=ttfb_samples,
            http_status=status_codes,
        )

    if spec.kind == "parallel_bulk":
        payload_size = spec.payload_bytes
        payloads = [payload_factory.payload(payload_size) for _ in range(spec.streams)]

        async def one(payload: bytes) -> tuple[float, bool]:
            connection = await connector()
            try:
                deadline = time.perf_counter() + spec.timeout_s
                started = time.perf_counter()
                await asyncio.wait_for(
                    connection.stream.write_bulk(
                        payload, chunk_bytes=spec.chunk_bytes, max_in_flight=spec.max_in_flight
                    ),
                    timeout=max(0.1, deadline - time.perf_counter()),
                )
                echoed, _first = await asyncio.wait_for(
                    _read_exactly(connection.stream, len(payload), deadline=deadline),
                    timeout=max(0.1, deadline - time.perf_counter()),
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                return elapsed_ms, echoed == payload
            finally:
                await _close_quietly(connection.stream)

        started = time.perf_counter()
        results = await asyncio.gather(*(one(payload) for payload in payloads))
        wall_ms = (time.perf_counter() - started) * 1000.0
        per_stream = [elapsed for elapsed, _ in results]
        integrity = all(ok for _, ok in results)
        return WorkloadOutcome(
            ok=True,
            payload_bytes=payload_size * spec.streams,
            received_bytes=payload_size * spec.streams,
            integrity=integrity,
            total_ms=wall_ms,
            per_stream_ms=per_stream,
            goodput_mbps=_goodput_mbps(payload_size * spec.streams, wall_ms),
        )

    raise ValueError(f"unsupported workload kind {spec.kind!r}")


async def _close_quietly(stream: ByteStream) -> None:
    try:
        await stream.close()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    except Exception:  # noqa: BLE001 - teardown must not mask the trial result
        pass
