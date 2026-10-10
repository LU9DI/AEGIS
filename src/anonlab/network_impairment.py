"""Loopback-only, user-space link shaper for AEGIS experiments.

This emulates one-way propagation delay, bounded jitter and serialization rate
on a byte stream. It does NOT emulate IP packet loss or a real WAN: TCP remains
reliable, and the read chunks are implementation-dependent rather than packets.
"""
from __future__ import annotations

import asyncio
import ipaddress
import math
import random
import time
from dataclasses import dataclass, field
from typing import Final

DEFAULT_SHAPER_CHUNK_BYTES: Final[int] = 16 * 1024
DEFAULT_SHAPER_QUEUE_CHUNKS: Final[int] = 16
MAX_SHAPER_CHUNK_BYTES: Final[int] = 64 * 1024
MAX_SHAPER_QUEUE_CHUNKS: Final[int] = 256


def _validate_loopback(host: str, *, name: str) -> None:
    if not isinstance(host, str):
        raise ValueError(f"{name} must be a literal loopback IP address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(f"{name} must be a literal loopback IP address") from exc
    if not address.is_loopback or address.version != 4:
        raise ValueError(f"{name} must be IPv4 loopback-only")


@dataclass(frozen=True, slots=True)
class LinkImpairmentProfile:
    """One-way profile used by a local transparent TCP proxy.

    ``latency_ms`` is a propagation delay per direction. ``bandwidth_mbps`` is
    an aggregate per-proxy, per-direction serialization rate shared by all TCP
    connections traversing that proxy; when None, no explicit rate limit is
    applied. ``jitter_ms`` is sampled from a uniform +/- range. ``queue_chunks``
    bounds userspace buffering per direction. No packet loss is simulated.
    """

    name: str
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    bandwidth_mbps: float | None = None
    seed: int = 20261009
    chunk_bytes: int = DEFAULT_SHAPER_CHUNK_BYTES
    queue_chunks: int = DEFAULT_SHAPER_QUEUE_CHUNKS

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("profile name must not be empty")
        for name, value in (("latency_ms", self.latency_ms), ("jitter_ms", self.jitter_ms)):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.bandwidth_mbps is not None and (
            not isinstance(self.bandwidth_mbps, (int, float))
            or isinstance(self.bandwidth_mbps, bool)
            or not math.isfinite(self.bandwidth_mbps)
            or self.bandwidth_mbps <= 0
        ):
            raise ValueError("bandwidth_mbps must be None or a finite positive number")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")
        if not isinstance(self.chunk_bytes, int) or isinstance(self.chunk_bytes, bool) or not 1 <= self.chunk_bytes <= MAX_SHAPER_CHUNK_BYTES:
            raise ValueError(f"chunk_bytes must be within 1..{MAX_SHAPER_CHUNK_BYTES}")
        if not isinstance(self.queue_chunks, int) or isinstance(self.queue_chunks, bool) or not 1 <= self.queue_chunks <= MAX_SHAPER_QUEUE_CHUNKS:
            raise ValueError(f"queue_chunks must be within 1..{MAX_SHAPER_QUEUE_CHUNKS}")


DEFAULT_PROFILES: dict[str, LinkImpairmentProfile] = {
    "loopback": LinkImpairmentProfile("loopback", latency_ms=0.0, jitter_ms=0.0),
    "lan": LinkImpairmentProfile("lan", latency_ms=0.5, jitter_ms=0.1, bandwidth_mbps=1000.0, seed=20261010),
    "metro": LinkImpairmentProfile("metro", latency_ms=5.0, jitter_ms=1.0, bandwidth_mbps=200.0, seed=20261011),
    "intercontinental": LinkImpairmentProfile("intercontinental", latency_ms=25.0, jitter_ms=5.0, bandwidth_mbps=50.0, seed=20261012),
    "constrained": LinkImpairmentProfile("constrained", latency_ms=40.0, jitter_ms=8.0, bandwidth_mbps=10.0, seed=20261013),
}


@dataclass(slots=True)
class ProxyMetrics:
    accepted_connections: int = 0
    rejected_connections: int = 0
    active_connections: int = 0
    bytes_client_to_upstream: int = 0
    bytes_upstream_to_client: int = 0
    max_queue_chunks_observed: int = 0
    directional_pump_errors: int = 0
    _connection_counter: int = field(default=0, repr=False)


class TcpImpairmentProxy:
    """Transparent, bounded-buffer TCP shaper restricted to IPv4 loopback."""

    def __init__(
        self,
        upstream_host: str,
        upstream_port: int,
        profile: LinkImpairmentProfile,
        *,
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
        max_connections: int = 64,
    ) -> None:
        _validate_loopback(upstream_host, name="upstream_host")
        _validate_loopback(listen_host, name="listen_host")
        if not isinstance(upstream_port, int) or isinstance(upstream_port, bool) or not 1 <= upstream_port <= 65535:
            raise ValueError("upstream_port must be within 1..65535")
        if not isinstance(listen_port, int) or isinstance(listen_port, bool) or not 0 <= listen_port <= 65535:
            raise ValueError("listen_port must be within 0..65535")
        if not isinstance(max_connections, int) or isinstance(max_connections, bool) or not 1 <= max_connections <= 1024:
            raise ValueError("max_connections must be within 1..1024")
        if not isinstance(profile, LinkImpairmentProfile):
            raise ValueError("profile must be a LinkImpairmentProfile")
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.profile = profile
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.max_connections = max_connections
        self.server: asyncio.AbstractServer | None = None
        self.metrics = ProxyMetrics()
        self._handlers: set[asyncio.Task[None]] = set()
        # A configured rate is shared across every connection traversing this
        # proxy in each direction, not granted independently to each stream.
        self._tx_clocks = [0.0, 0.0]

    async def start(self) -> "TcpImpairmentProxy":
        if self.server is not None:
            raise RuntimeError("proxy is already started")
        self.server = await asyncio.start_server(
            self._handle, self.listen_host, self.listen_port, limit=self.profile.chunk_bytes * 2
        )
        self.listen_port = int(self.server.sockets[0].getsockname()[1])
        return self

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        handlers = list(self._handlers)
        for task in handlers:
            if not task.done():
                task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        self._handlers.clear()

    async def __aenter__(self) -> "TcpImpairmentProxy":
        return await self.start()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    async def _handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        # Admission is decided before the first await, so this check is atomic
        # relative to other handlers on the same asyncio event loop.
        if self.metrics.active_connections >= self.max_connections:
            self.metrics.rejected_connections += 1
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task is not None:
                self._handlers.discard(task)
            return
        self.metrics.accepted_connections += 1
        self.metrics.active_connections += 1
        upstream_writer: asyncio.StreamWriter | None = None
        pumps: list[asyncio.Task[None]] = []
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self.upstream_host, self.upstream_port, limit=self.profile.chunk_bytes * 2
            )
            connection_id = self.metrics._connection_counter
            self.metrics._connection_counter += 1
            pumps = [
                asyncio.create_task(self._pump(
                    client_reader, upstream_writer, connection_id=connection_id, direction=0
                )),
                asyncio.create_task(self._pump(
                    upstream_reader, client_writer, connection_id=connection_id, direction=1
                )),
            ]
            done, pending = await asyncio.wait(pumps, return_when=asyncio.FIRST_EXCEPTION)
            error = next((t.exception() for t in done if not t.cancelled() and t.exception() is not None), None)
            if error is not None:
                for pending_task in pending:
                    pending_task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
        except (ConnectionError, asyncio.IncompleteReadError, OSError, asyncio.CancelledError):
            if asyncio.current_task() is not None and asyncio.current_task().cancelling():
                raise
        finally:
            for pump in pumps:
                if not pump.done():
                    pump.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if upstream_writer is not None:
                upstream_writer.close()
                try:
                    await upstream_writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
            self.metrics.active_connections = max(0, self.metrics.active_connections - 1)
            if task is not None:
                self._handlers.discard(task)

    async def _pump(
        self,
        source: asyncio.StreamReader,
        destination: asyncio.StreamWriter,
        *,
        connection_id: int,
        direction: int,
    ) -> None:
        """Bounded producer/consumer queue approximates a shaped byte-stream link."""
        profile = self.profile
        queue: asyncio.Queue[tuple[float, bytes] | None] = asyncio.Queue(maxsize=profile.queue_chunks)
        rng = random.Random(profile.seed + connection_id * 1_000_003 + direction * 97_409)
        loop = asyncio.get_running_loop()
        delivery_clock = loop.time()
        sent_bytes = 0

        async def produce() -> None:
            nonlocal delivery_clock
            was_cancelled = False
            try:
                while True:
                    data = await source.read(profile.chunk_bytes)
                    if not data:
                        break
                    now = loop.time()
                    # Update without an await: asyncio tasks in this event loop
                    # share one aggregate per-direction serialization schedule.
                    tx_start = max(self._tx_clocks[direction], now)
                    serialization_s = (
                        len(data) * 8 / (profile.bandwidth_mbps * 1_000_000)
                        if profile.bandwidth_mbps is not None else 0.0
                    )
                    tx_end = tx_start + serialization_s
                    self._tx_clocks[direction] = tx_end
                    jitter_s = rng.uniform(-profile.jitter_ms, profile.jitter_ms) / 1000.0
                    arrival_time = tx_end + max(0.0, (profile.latency_ms / 1000.0) + jitter_s)
                    # A TCP byte stream preserves order even if independent jitter samples would reorder chunks.
                    delivery_clock = max(delivery_clock, arrival_time)
                    await queue.put((delivery_clock, data))
                    self.metrics.max_queue_chunks_observed = max(
                        self.metrics.max_queue_chunks_observed, queue.qsize()
                    )
            except asyncio.CancelledError:
                was_cancelled = True
                raise
            finally:
                if was_cancelled:
                    # Cancellation must not block forever trying to enqueue a sentinel
                    # after the consumer has been cancelled with a full bounded queue.
                    try:
                        queue.put_nowait(None)
                    except asyncio.QueueFull:
                        pass
                else:
                    await queue.put(None)

        async def consume() -> None:
            nonlocal sent_bytes
            while True:
                item = await queue.get()
                if item is None:
                    break
                delivery_time, data = item
                wait_s = delivery_time - loop.time()
                if wait_s > 0:
                    await asyncio.sleep(wait_s)
                destination.write(data)
                await destination.drain()
                sent_bytes += len(data)
            if destination.can_write_eof():
                destination.write_eof()
                await destination.drain()

        producer = asyncio.create_task(produce())
        consumer = asyncio.create_task(consume())
        try:
            done, pending = await asyncio.wait((producer, consumer), return_when=asyncio.FIRST_EXCEPTION)
            error = next((t.exception() for t in done if not t.cancelled() and t.exception() is not None), None)
            if error is not None:
                for pending_task in pending:
                    pending_task.cancel()
                raise error
            await asyncio.gather(producer, consumer)
        except asyncio.CancelledError:
            producer.cancel()
            consumer.cancel()
            await asyncio.gather(producer, consumer, return_exceptions=True)
            raise
        except Exception:
            self.metrics.directional_pump_errors += 1
            producer.cancel()
            consumer.cancel()
            await asyncio.gather(producer, consumer, return_exceptions=True)
            raise
        finally:
            if direction == 0:
                self.metrics.bytes_client_to_upstream += sent_bytes
            else:
                self.metrics.bytes_upstream_to_client += sent_bytes
            for task in (producer, consumer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer, consumer, return_exceptions=True)
