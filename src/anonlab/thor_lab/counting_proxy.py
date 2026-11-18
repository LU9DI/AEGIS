"""Transparent TCP counting proxy used to attribute wire bytes to a trial.

Every arm of the THOR lab connects through one of these. It gives a single,
uniform place to count the bytes the client actually puts on its access link
(including AEAD tags, command headers, window updates and retransmission-free
loopback copies) without reading any protocol internals.

It is deliberately *not* a shaper: the repository already has one
(:class:`anonlab.network_impairment.TcpImpairmentProxy`) which is restricted to
loopback upstreams, while the public tier must reach the Internet. Use the
shaper in front of this proxy when a link profile is requested.

The proxy is loopback-only on the listen side on purpose; it is a measurement
instrument, not a forward proxy.
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from dataclasses import dataclass

__all__ = ["CountingProxy", "ProxyCounters"]

_PUMP_CHUNK_BYTES = 64 * 1024


@dataclass(slots=True)
class ProxyCounters:
    """Cumulative counters; take deltas around a trial."""

    accepted_connections: int = 0
    failed_connections: int = 0
    client_to_upstream_bytes: int = 0
    upstream_to_client_bytes: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "accepted_connections": self.accepted_connections,
            "failed_connections": self.failed_connections,
            "client_to_upstream_bytes": self.client_to_upstream_bytes,
            "upstream_to_client_bytes": self.upstream_to_client_bytes,
        }

    def delta(self, later: "ProxyCounters") -> dict[str, int]:
        """Counters added between this snapshot and ``later``."""
        return {
            name: getattr(later, name) - getattr(self, name)
            for name in (
                "accepted_connections",
                "failed_connections",
                "client_to_upstream_bytes",
                "upstream_to_client_bytes",
            )
        }


class CountingProxy:
    """Byte-counting TCP proxy with a fixed upstream endpoint."""

    def __init__(
        self,
        upstream_host: str,
        upstream_port: int,
        *,
        listen_port: int = 0,
        max_connections: int = 512,
        name: str = "counting-proxy",
    ) -> None:
        if not isinstance(upstream_host, str) or not upstream_host:
            raise ValueError("upstream_host must be a non-empty string")
        if not 1 <= int(upstream_port) <= 65535:
            raise ValueError("upstream_port must be within 1..65535")
        if not 0 <= int(listen_port) <= 65535:
            raise ValueError("listen_port must be within 0..65535")
        if not 1 <= int(max_connections) <= 4096:
            raise ValueError("max_connections must be within 1..4096")
        self.upstream_host = upstream_host
        self.upstream_port = int(upstream_port)
        self.listen_port = int(listen_port)
        self.max_connections = int(max_connections)
        self.name = name
        self.counters = ProxyCounters()
        self._server: asyncio.AbstractServer | None = None
        self._handlers: set[asyncio.Task[None]] = set()

    @property
    def ready(self) -> bool:
        return self._server is not None

    async def start(self) -> "CountingProxy":
        if self._server is not None:
            raise RuntimeError("counting proxy is already started")
        self._server = await asyncio.start_server(
            self._handle, "127.0.0.1", self.listen_port, limit=_PUMP_CHUNK_BYTES * 2
        )
        self.listen_port = int(self._server.sockets[0].getsockname()[1])
        return self

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        handlers = [task for task in self._handlers if not task.done()]
        for task in handlers:
            task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        self._handlers.clear()

    async def __aenter__(self) -> "CountingProxy":
        return await self.start()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    async def _handle(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        if self.counters.accepted_connections - self.counters.failed_connections >= self.max_connections:
            self.counters.failed_connections += 1
            client_writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await client_writer.wait_closed()
            return
        self.counters.accepted_connections += 1
        upstream_writer: asyncio.StreamWriter | None = None
        pumps: list[asyncio.Task[None]] = []
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self.upstream_host, self.upstream_port, limit=_PUMP_CHUNK_BYTES * 2
            )
            pumps = [
                asyncio.create_task(self._pump(client_reader, upstream_writer, direction="up")),
                asyncio.create_task(self._pump(upstream_reader, client_writer, direction="down")),
            ]
            await asyncio.gather(*pumps, return_exceptions=True)
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            self.counters.failed_connections += 1
        finally:
            for pump in pumps:
                if not pump.done():
                    pump.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            client_writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await client_writer.wait_closed()
            if upstream_writer is not None:
                upstream_writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await upstream_writer.wait_closed()
            if task is not None:
                self._handlers.discard(task)

    async def _pump(
        self,
        source: asyncio.StreamReader,
        destination: asyncio.StreamWriter,
        *,
        direction: str,
    ) -> None:
        try:
            while True:
                data = await source.read(_PUMP_CHUNK_BYTES)
                if not data:
                    break
                destination.write(data)
                await destination.drain()
                if direction == "up":
                    self.counters.client_to_upstream_bytes += len(data)
                else:
                    self.counters.upstream_to_client_bytes += len(data)
            if destination.can_write_eof():
                with contextlib.suppress(OSError, RuntimeError):
                    destination.write_eof()
                    await destination.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            return


def _is_loopback(host: str) -> bool:  # pragma: no cover - helper kept for clarity
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
