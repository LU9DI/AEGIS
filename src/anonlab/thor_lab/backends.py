"""Transport arms measured by the THOR lab.

An arm is a way for one client on this host to reach the application endpoint.
Each arm owns its own relays/servers and its own counting proxy, so an arm can be
started and stopped without comparing against a warm or shared resource.

Arms implemented here:

``surface``
    Direct TCP from the client to the endpoint (loopback or public).
``relay3_plain``
    Three chained plain-TCP relays with no cryptography, equivalent to the
    non-anonymous relay in :mod:`anonlab.relay`. It isolates the cost of extra
    hops and copies from the cost of cryptography.
``aegis_telescope3``
    The real prototype: three :class:`anonlab.telescoping.RelayNode` hops with
    per-hop AEAD, authenticated links and a multiplexed duplex stream.
``tor_socks``
    A real local Tor process reached through its SOCKS5 port.

Nothing in this module provides anonymity by itself, and none of these arms is a
production transport. The reference for what may be claimed is
``docs/research/thor/04-THREAT-MODEL.md``.
"""
from __future__ import annotations

import abc
import asyncio
import contextlib
import dataclasses
import os
from dataclasses import dataclass, field
from typing import Any

from .counting_proxy import CountingProxy
from .socks5 import Socks5Error, open_socks5

__all__ = [
    "AegisTelescopeBackend",
    "Backend",
    "BackendUnavailable",
    "ByteStream",
    "Connection",
    "PlainChainBackend",
    "SetupStep",
    "SocketByteStream",
    "SurfaceBackend",
    "TorSocksBackend",
    "ARMS",
    "arm_by_name",
    "probe_tor",
]


class BackendUnavailable(RuntimeError):
    """Raised when an arm cannot run on this host, with a machine-readable reason."""

    def __init__(self, backend: str, reason: str, detail: str | None = None) -> None:
        self.backend = backend
        self.reason = reason
        self.detail = detail
        message = f"arm {backend!r} unavailable: {reason}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)

    def to_dict(self) -> dict[str, object]:
        return {"backend": self.backend, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class SetupStep:
    step: str
    ms: float

    def to_dict(self) -> dict[str, object]:
        return {"step": self.step, "ms": round(self.ms, 4)}


class ByteStream(abc.ABC):
    """Minimal full-duplex byte stream shared by every arm.

    ``write_bulk`` defaults to sequential chunked writes. Arms that can batch
    natively (the AEGIS duplex stream supports a bounded in-flight WRITE
    pipeline) override it, so one workload specification measures each arm with
    its own mechanism instead of handicapping whichever arm sends fewer
    syscalls per chunk.
    """

    @abc.abstractmethod
    async def write(self, data: bytes) -> None: ...

    async def write_bulk(self, data: bytes, *, chunk_bytes: int, max_in_flight: int) -> None:
        if chunk_bytes < 1:
            raise ValueError("chunk_bytes must be positive")
        batch_bytes = chunk_bytes * max(1, max_in_flight)
        for start in range(0, len(data), batch_bytes):
            end = min(len(data), start + batch_bytes)
            for offset in range(start, end, chunk_bytes):
                await self.write(data[offset : min(offset + chunk_bytes, end)])

    @abc.abstractmethod
    async def read(self, max_bytes: int) -> bytes:
        """Return up to ``max_bytes``; an empty result means end of stream."""

    @abc.abstractmethod
    async def write_eof(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


class SocketByteStream(ByteStream):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def write(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def read(self, max_bytes: int) -> bytes:
        return await self._reader.read(max_bytes)

    async def write_eof(self) -> None:
        if self._writer.can_write_eof():
            with contextlib.suppress(OSError, RuntimeError):
                self._writer.write_eof()
                await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await self._writer.wait_closed()


class AegisByteStream(ByteStream):
    """Adapts an ``anonlab.telescoping.DuplexCircuitStream`` to the arm API."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def write(self, data: bytes) -> None:
        await self._stream.write(data)

    async def write_bulk(self, data: bytes, *, chunk_bytes: int, max_in_flight: int) -> None:
        # The prototype caps one pipelined call at 4 MiB and four commands in
        # flight; larger payloads are split into consecutive batches.
        block_bytes = min(len(data), 4 * 1024 * 1024) or 1
        for start in range(0, len(data), block_bytes):
            await self._stream.write_pipelined(
                data[start : start + block_bytes],
                chunk_bytes=chunk_bytes,
                max_in_flight=max(1, min(int(max_in_flight), 4)),
            )

    async def read(self, max_bytes: int) -> bytes:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        chunk = await self._stream.read_chunk()
        if not chunk:
            return b""
        if len(chunk) > max_bytes:
            raise ValueError("duplex read returned more than the requested maximum")
        return chunk

    async def write_eof(self) -> None:
        await self._stream.write_eof()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._stream.close()


@dataclass(slots=True)
class Connection:
    stream: ByteStream
    setup_steps: list[SetupStep] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)
    raw: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None

    @property
    def setup_ms(self) -> float:
        return round(sum(step.ms for step in self.setup_steps), 4)


class Backend(abc.ABC):
    """One measurement arm."""

    name: str = "abstract"
    family: str = "abstract"
    tier: str = "lab"
    needs_loopback_target: bool = True

    def __init__(self, *, proxy: bool = True) -> None:
        self._proxy_enabled = proxy
        self._proxy: CountingProxy | None = None
        self._shaper: Any | None = None
        self._link_profile: Any | None = None
        self._started = False

    @property
    def edge(self) -> CountingProxy | None:
        return self._proxy

    def describe(self) -> dict[str, object]:
        return {
            "arm": self.name,
            "family": self.family,
            "tier": self.tier,
            "edge_counting_proxy": self._proxy is not None,
        }

    def edge_snapshot(self) -> dict[str, int] | None:
        return None if self._proxy is None else self._proxy.counters.as_dict()

    async def start(self) -> None:
        await self._start()
        self._started = True

    async def _start(self) -> None:
        return None

    async def connect(self, *, timeout: float = 30.0) -> Connection:
        if not self._started:
            raise RuntimeError("backend.start() must be called before connect()")
        return await self._connect(timeout=timeout)

    @abc.abstractmethod
    async def _connect(self, *, timeout: float) -> Connection: ...

    async def close(self) -> None:
        await self._close()
        self._started = False

    async def after_trial(self) -> None:
        """Release per-trial resources so RSS and CPU stay attributable.

        The default implementation does nothing; an arm that allocates a circuit
        per connection overrides it. The runner calls this after every trial,
        including failed ones, before sampling the post-trial resources.
        """
        return None

    async def _close(self) -> None:
        if self._proxy is not None:
            await self._proxy.close()
            self._proxy = None
        if self._shaper is not None:
            await self._shaper.close()
            self._shaper = None

    def set_link_profile(self, profile: Any | None) -> None:
        """Attach the repository's loopback link shaper in front of this arm.

        The shaper itself rejects a non-loopback upstream, so a public arm with a
        profile fails when it starts rather than producing a silently unshaped
        public measurement.
        """
        self._link_profile = profile

    async def _start_proxy(self, upstream_host: str, upstream_port: int) -> int:
        if not self._proxy_enabled:
            return int(upstream_port)
        if self._link_profile is not None:
            from ..network_impairment import TcpImpairmentProxy  # noqa: PLC0415 - optional path

            self._shaper = await TcpImpairmentProxy(
                upstream_host, int(upstream_port), self._link_profile, max_connections=512
            ).start()
            upstream_host, upstream_port = "127.0.0.1", self._shaper.listen_port
        self._proxy = CountingProxy(upstream_host, upstream_port, name=self.name)
        await self._proxy.start()
        return self._proxy.listen_port

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} arm={self.name!r} tier={self.tier!r}>"


class SurfaceBackend(Backend):
    """Direct TCP to the endpoint: the "Surface" reference arm."""

    family = "surface"
    needs_loopback_target = False

    def __init__(
        self,
        target_host: str,
        target_port: int,
        *,
        tier: str = "lab",
        name: str = "surface",
    ) -> None:
        super().__init__(proxy=True)
        if not isinstance(target_host, str) or not target_host:
            raise ValueError("target_host must be a non-empty string")
        if not 1 <= int(target_port) <= 65535:
            raise ValueError("target_port must be within 1..65535")
        self.target_host = target_host
        self.target_port = int(target_port)
        self.tier = tier
        self.name = name
        self.upstream_port = 0

    async def _start(self) -> None:
        self.upstream_port = await self._start_proxy(self.target_host, self.target_port)

    async def _connect(self, *, timeout: float) -> Connection:
        started = asyncio.get_running_loop().time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self.upstream_port), timeout=timeout
        )
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000.0
        return Connection(
            stream=SocketByteStream(reader, writer),
            setup_steps=[SetupStep("tcp_connect", elapsed_ms)],
            meta={"endpoint": f"{self.target_host}:{self.target_port}"},
            raw=(reader, writer),
        )


class PlainChainBackend(Backend):
    """Three chained plain-TCP relays without cryptography (hop-cost reference)."""

    family = "relay_chain"

    def __init__(
        self,
        target_host: str,
        target_port: int,
        *,
        hop_count: int = 3,
        tier: str = "lab",
        name: str = "relay3_plain",
    ) -> None:
        super().__init__(proxy=True)
        if not 1 <= int(hop_count) <= 5:
            raise ValueError("hop_count must be within 1..5")
        if not 1 <= int(target_port) <= 65535:
            raise ValueError("target_port must be within 1..65535")
        self.target_host = target_host
        self.target_port = int(target_port)
        self.hop_count = int(hop_count)
        self.tier = tier
        self.name = name
        self._servers: list[asyncio.AbstractServer] = []
        self._hop_ports: list[int] = []
        self._tasks: set[asyncio.Task[None]] = set()

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await reader.read(64 * 1024)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
            if writer.can_write_eof():
                with contextlib.suppress(OSError, RuntimeError):
                    writer.write_eof()
                    await writer.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            return

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        upstream_host: str,
        upstream_port: int,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(upstream_host, upstream_port)
            await asyncio.gather(
                self._pipe(reader, upstream_writer),
                self._pipe(upstream_reader, writer),
                return_exceptions=True,
            )
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            if upstream_writer is not None:
                upstream_writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await upstream_writer.wait_closed()
            if task is not None:
                self._tasks.discard(task)

    async def _start(self) -> None:
        upstream_host, upstream_port = self.target_host, self.target_port
        for _ in range(self.hop_count):
            host, port = upstream_host, upstream_port
            server = await asyncio.start_server(
                lambda r, w, h=host, p=port: self._handle(r, w, h, p), "127.0.0.1", 0
            )
            bound = int(server.sockets[0].getsockname()[1])
            self._servers.append(server)
            self._hop_ports.insert(0, bound)
            upstream_host, upstream_port = "127.0.0.1", bound
        await self._start_proxy("127.0.0.1", self._hop_ports[0])

    async def _connect(self, *, timeout: float) -> Connection:
        if self._proxy is None:
            raise RuntimeError("plain chain requires the counting proxy")
        started = asyncio.get_running_loop().time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self._proxy.listen_port), timeout=timeout
        )
        elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000.0
        return Connection(
            stream=SocketByteStream(reader, writer),
            setup_steps=[SetupStep("tcp_connect", elapsed_ms)],
            meta={"hops": self.hop_count},
            raw=(reader, writer),
        )

    async def _close(self) -> None:
        for server in self._servers:
            server.close()
        for server in self._servers:
            await server.wait_closed()
        self._servers.clear()
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await super()._close()


class AegisTelescopeBackend(Backend):
    """The AEGIS telescoping prototype: three authenticated AEAD relay hops."""

    family = "aegis"

    def __init__(
        self,
        target_host: str,
        target_port: int,
        *,
        hop_count: int = 3,
        window_update_batch_bytes: int = 64 * 1024,
        tier: str = "lab",
        name: str = "aegis_telescope3",
    ) -> None:
        super().__init__(proxy=True)
        if not 1 <= int(hop_count) <= 5:
            raise ValueError("hop_count must be within 1..5")
        if not 1 <= int(target_port) <= 65535:
            raise ValueError("target_port must be within 1..65535")
        self.target_host = target_host
        self.target_port = int(target_port)
        self.hop_count = int(hop_count)
        self.window_update_batch_bytes = int(window_update_batch_bytes)
        self.tier = tier
        self.name = name
        self._nodes: list[Any] = []
        self._servers: list[asyncio.AbstractServer] = []
        self._client: Any | None = None
        self._clients: list[Any] = []
        self._telescoping: Any | None = None
        self._guard_descriptor: Any | None = None

    def _module(self) -> Any:
        if self._telescoping is not None:
            return self._telescoping
        try:
            from .. import telescoping  # noqa: PLC0415 - optional crypto extra
        except Exception as exc:  # noqa: BLE001 - reported as unavailable, never skipped silently
            raise BackendUnavailable(
                self.name, "crypto_extra_unavailable", f"{type(exc).__name__}: {exc}"
            ) from exc
        self._telescoping = telescoping
        return telescoping

    async def _start(self) -> None:
        module = self._module()
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(
                self.name, "crypto_extra_unavailable", f"{type(exc).__name__}: {exc}"
            ) from exc
        for _ in range(self.hop_count):
            node = module.RelayNode(
                identity_digest=os.urandom(20),
                onion_private_key=X25519PrivateKey.generate(),
            )
            server = await module.serve_node(node)
            self._nodes.append(node)
            self._servers.append(server)
        self._nodes[-1].allowed_destinations.add((self.target_host, self.target_port))
        guard = self._nodes[0].descriptor
        edge_port = await self._start_proxy("127.0.0.1", guard.port)
        # The client must authenticate the real guard identity through the proxy,
        # so only the address is redirected; the keys and digest stay the guard's.
        self._guard_descriptor = dataclasses.replace(guard, host="127.0.0.1", port=edge_port)

    async def _connect(self, *, timeout: float) -> Connection:
        module = self._module()
        if self._guard_descriptor is None:
            raise BackendUnavailable(self.name, "arm_not_started")
        client = module.TelescopingClient(
            max_active_streams=32,
            window_update_batch_bytes=self.window_update_batch_bytes,
        )
        steps: list[SetupStep] = []
        loop = asyncio.get_running_loop()
        try:
            started = loop.time()
            await asyncio.wait_for(client.connect_guard(self._guard_descriptor), timeout=timeout)
            steps.append(SetupStep("guard_connect", (loop.time() - started) * 1000.0))
            for index, node in enumerate(self._nodes[1:], start=1):
                started = loop.time()
                await asyncio.wait_for(client.extend(node.descriptor), timeout=timeout)
                steps.append(SetupStep(f"extend_{index}", (loop.time() - started) * 1000.0))
            started = loop.time()
            stream = await asyncio.wait_for(
                client.open_stream(self.target_host, self.target_port), timeout=timeout
            )
            steps.append(SetupStep("stream_open", (loop.time() - started) * 1000.0))
        except BaseException:
            with contextlib.suppress(Exception):
                await client.close()
            raise
        self._client = client
        self._clients.append(client)
        return Connection(
            stream=AegisByteStream(stream),
            setup_steps=steps,
            meta={
                "hops": len(client.hops),
                "direct_client_connections": client.direct_connections_opened,
                "guard_via_counting_proxy": True,
            },
        )

    async def after_trial(self) -> None:
        """Close every circuit opened during the trial (one per connection)."""
        for client in self._clients:
            with contextlib.suppress(Exception):
                await client.close()
        self._clients.clear()
        self._client = None

    async def _close(self) -> None:
        await self.after_trial()
        for server in self._servers:
            server.close()
        for server in self._servers:
            await server.wait_closed()
        self._servers.clear()
        await super()._close()


class TorSocksBackend(Backend):
    """A real local Tor process reached through its SOCKS5 port."""

    family = "tor"
    needs_loopback_target = False

    def __init__(
        self,
        target_host: str,
        target_port: int,
        *,
        socks_host: str = "127.0.0.1",
        socks_port: int = 9050,
        tier: str = "public",
        name: str = "tor_socks",
    ) -> None:
        super().__init__(proxy=True)
        if not 1 <= int(target_port) <= 65535:
            raise ValueError("target_port must be within 1..65535")
        if not 1 <= int(socks_port) <= 65535:
            raise ValueError("socks_port must be within 1..65535")
        self.target_host = target_host
        self.target_port = int(target_port)
        self.socks_host = socks_host
        self.socks_port = int(socks_port)
        self.tier = tier
        self.name = name
        self.last_socks_reply: int | None = None

    async def _start(self) -> None:
        probe = await probe_tor(self.socks_host, self.socks_port, timeout=5.0)
        if not probe["available"]:
            raise BackendUnavailable(
                self.name, str(probe["reason"]), str(probe.get("detail") or "")
            )
        await self._start_proxy(self.socks_host, self.socks_port)

    async def _connect(self, *, timeout: float) -> Connection:
        if self._proxy is None:
            raise RuntimeError("tor arm requires the counting proxy")
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            reader, writer = await open_socks5(
                "127.0.0.1",
                self._proxy.listen_port,
                self.target_host,
                self.target_port,
                timeout=timeout,
            )
        except Socks5Error as exc:
            raise BackendUnavailable(
                self.name, "socks_connect_failed", str(exc)
            ) from exc
        steps = [SetupStep("socks_connect", (loop.time() - started) * 1000.0)]
        return Connection(
            stream=SocketByteStream(reader, writer),
            setup_steps=steps,
            meta={
                "endpoint": f"{self.target_host}:{self.target_port}",
                "socks_endpoint": f"{self.socks_host}:{self.socks_port}",
            },
            raw=(reader, writer),
        )


async def probe_tor(
    socks_host: str = "127.0.0.1", socks_port: int = 9050, *, timeout: float = 5.0
) -> dict[str, object]:
    """Report whether a no-authentication SOCKS5 endpoint is reachable."""
    endpoint = f"{socks_host}:{socks_port}"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(socks_host, socks_port), timeout=timeout
        )
    except (OSError, TimeoutError) as exc:
        return {
            "available": False,
            "reason": "socks_port_unreachable",
            "detail": f"{type(exc).__name__}: {exc}",
            "socks_endpoint": endpoint,
        }
    try:
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        reply = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
        if reply[0] != 0x05:
            return {
                "available": False,
                "reason": "not_a_socks5_endpoint",
                "detail": f"version byte 0x{reply[0]:02x}",
                "socks_endpoint": endpoint,
            }
        if reply[1] != 0x00:
            return {
                "available": False,
                "reason": "no_auth_method_refused",
                "detail": f"method byte 0x{reply[1]:02x}",
                "socks_endpoint": endpoint,
            }
        return {
            "available": True,
            "reason": "ok",
            "detail": "SOCKS5 no-authentication method accepted",
            "socks_endpoint": endpoint,
        }
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
        return {
            "available": False,
            "reason": "socks_greeting_failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "socks_endpoint": endpoint,
        }
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()


ARMS: dict[str, type[Backend]] = {
    "surface": SurfaceBackend,
    "relay3_plain": PlainChainBackend,
    "aegis_telescope3": AegisTelescopeBackend,
    "tor_socks": TorSocksBackend,
}


def arm_by_name(name: str) -> type[Backend]:
    try:
        return ARMS[name]
    except KeyError as exc:
        raise ValueError(f"unknown arm {name!r}; known arms: {', '.join(sorted(ARMS))}") from exc
