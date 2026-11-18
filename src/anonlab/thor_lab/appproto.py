"""Application protocols used by the THOR lab arms.

Two protocols exist because the two tiers answer different questions.

* Loopback tier ("lab"/"emulated"): a raw byte echo, the same semantics as
  :mod:`anonlab.echo_server` and the existing duplex benchmark, so the measured
  bytes are application payload plus anonymity overhead only.
* Public tier: one HTTP/1.1 GET of a fixed body from a public endpoint, because
  a public echo service cannot be assumed and every extra protocol feature would
  have to be implemented identically in both arms.

Neither protocol is a browser. Time-to-first-byte here means "time until the
first body byte", which is reported next to the header latency for transparency.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field

__all__ = [
    "EchoServerHandle",
    "HttpGetResult",
    "http_get",
    "http_request_bytes",
    "sha256_hex",
    "start_echo_server",
]

_READ_CHUNK = 64 * 1024
_MAX_HEADER_BYTES = 32 * 1024
_MAX_BODY_BYTES = 64 * 1024 * 1024
_USER_AGENT = "aegis-thor-lab/0.1 (research measurement; not a browser)"


async def _echo_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(_READ_CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


@dataclass(slots=True)
class EchoServerHandle:
    server: asyncio.AbstractServer
    host: str
    port: int

    async def close(self) -> None:
        self.server.close()
        await self.server.wait_closed()


async def start_echo_server(host: str = "127.0.0.1", port: int = 0) -> EchoServerHandle:
    """Start the loopback echo destination used by every local arm."""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("the THOR lab echo destination is loopback-only")
    server = await asyncio.start_server(_echo_handler, host, port, limit=_READ_CHUNK * 2)
    bound_port = int(server.sockets[0].getsockname()[1])
    return EchoServerHandle(server=server, host=host, port=bound_port)


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def http_request_bytes(host: str, path: str, *, extra_headers: dict[str, str] | None = None) -> bytes:
    if not isinstance(host, str) or not host or any(char in host for char in "\r\n"):
        raise ValueError("host must be a non-empty host name without CR/LF")
    if not path.startswith("/"):
        raise ValueError("path must start with '/'")
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}",
        f"User-Agent: {_USER_AGENT}",
        "Accept: */*",
        "Accept-Encoding: identity",
        "Connection: close",
    ]
    for name, value in (extra_headers or {}).items():
        if any(char in name + value for char in "\r\n"):
            raise ValueError("header names and values must not contain CR/LF")
        lines.append(f"{name}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


@dataclass(slots=True)
class HttpGetResult:
    status: int
    reason: str
    ttfb_header_ms: float
    first_body_byte_ms: float | None
    total_ms: float
    body_bytes: int
    content_length: int | None
    transfer_encoding: str | None
    redirected: bool
    body_sha256: str
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "ttfb_header_ms": self.ttfb_header_ms,
            "first_body_byte_ms": self.first_body_byte_ms,
            "total_ms": self.total_ms,
            "body_bytes": self.body_bytes,
            "content_length": self.content_length,
            "transfer_encoding": self.transfer_encoding,
            "redirected": self.redirected,
            "body_sha256": self.body_sha256,
            "content_type": self.headers.get("content-type"),
            "server": self.headers.get("server"),
            "via": self.headers.get("via"),
        }


class _TimedReader:
    """Wraps a StreamReader and records when the first bytes arrived."""

    def __init__(self, reader: asyncio.StreamReader) -> None:
        self._reader = reader
        self.first_byte_ns: int | None = None
        self.bytes_read = 0

    async def read(self, size: int) -> bytes:
        data = await self._reader.read(size)
        if data and self.first_byte_ns is None:
            self.first_byte_ns = time.perf_counter_ns()
        self.bytes_read += len(data)
        return data

    async def readexactly(self, size: int) -> bytes:
        data = await self._reader.readexactly(size)
        if data and self.first_byte_ns is None:
            self.first_byte_ns = time.perf_counter_ns()
        self.bytes_read += len(data)
        return data


async def _read_chunked(reader: asyncio.StreamReader, sink: bytearray, deadline_ns: int) -> None:
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=max(0.1, (deadline_ns - time.perf_counter_ns()) / 1e9))
        if not line:
            raise ValueError("chunked body truncated before the final chunk")
        size_field = line.split(b";", 1)[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError as exc:
            raise ValueError(f"invalid chunk size line: {line[:32]!r}") from exc
        if size == 0:
            while True:
                trailer = await reader.readline()
                if trailer in (b"\r\n", b"\n", b""):
                    return
        data = await reader.readexactly(size)
        sink.extend(data)
        await reader.readexactly(2)  # trailing CRLF
        if len(sink) > _MAX_BODY_BYTES:
            raise ValueError("response body exceeds the lab limit")


async def http_get(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    host: str,
    path: str = "/",
    timeout: float = 120.0,
    extra_headers: dict[str, str] | None = None,
) -> HttpGetResult:
    """Perform one HTTP/1.1 GET and report latency and body size.

    Header latency, first body byte and total time are measured separately so a
    slow handshake cannot be hidden inside a goodput number.
    """
    request = http_request_bytes(host, path, extra_headers=extra_headers)
    timed = _TimedReader(reader)
    started_ns = time.perf_counter_ns()
    deadline_ns = started_ns + int(timeout * 1e9)
    writer.write(request)
    await writer.drain()

    header_bytes = bytearray()
    while b"\r\n\r\n" not in header_bytes:
        chunk = await asyncio.wait_for(
            timed.read(4096), timeout=max(0.1, (deadline_ns - time.perf_counter_ns()) / 1e9)
        )
        if not chunk:
            raise ValueError("connection closed before the response headers completed")
        header_bytes.extend(chunk)
        if len(header_bytes) > _MAX_HEADER_BYTES:
            raise ValueError("response headers exceed the lab limit")
    header_end = header_bytes.index(b"\r\n\r\n") + 4
    body_prefix = bytes(header_bytes[header_end:])
    header_ns = timed.first_byte_ns or started_ns

    head_text = header_bytes[:header_end].decode("iso-8859-1")
    head_lines = head_text.split("\r\n")
    status_line = head_lines[0]
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise ValueError(f"invalid HTTP status line: {status_line[:64]!r}")
    try:
        status = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"invalid HTTP status code: {parts[1]!r}") from exc
    reason = parts[2] if len(parts) > 2 else ""
    headers: dict[str, str] = {}
    for line in head_lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()

    content_length = None
    if "content-length" in headers:
        try:
            content_length = int(headers["content-length"])
        except ValueError as exc:
            raise ValueError("invalid Content-Length header") from exc
        if not 0 <= content_length <= _MAX_BODY_BYTES:
            raise ValueError("Content-Length exceeds the lab limit")
    transfer_encoding = headers.get("transfer-encoding")

    body = bytearray(body_prefix)
    first_body_ns = time.perf_counter_ns() if body_prefix else None
    if transfer_encoding and "chunked" in transfer_encoding.lower():
        if body_prefix:
            # Chunked bodies must be decoded from the beginning; re-feed the prefix.
            raise ValueError("unexpected body prefix before a chunked body")
        await _read_chunked(timed, body, deadline_ns)
    elif content_length is not None:
        remaining = content_length - len(body)
        while remaining > 0:
            chunk = await asyncio.wait_for(
                timed.read(min(_READ_CHUNK, remaining)),
                timeout=max(0.1, (deadline_ns - time.perf_counter_ns()) / 1e9),
            )
            if not chunk:
                raise ValueError("connection closed before the declared Content-Length")
            body.extend(chunk)
            remaining -= len(chunk)
    else:
        while True:
            chunk = await asyncio.wait_for(
                timed.read(_READ_CHUNK), timeout=max(0.1, (deadline_ns - time.perf_counter_ns()) / 1e9)
            )
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > _MAX_BODY_BYTES:
                raise ValueError("response body exceeds the lab limit")
    if first_body_ns is None and body:
        first_body_ns = time.perf_counter_ns()
    finished_ns = time.perf_counter_ns()
    return HttpGetResult(
        status=status,
        reason=reason,
        ttfb_header_ms=(header_ns - started_ns) / 1e6,
        first_body_byte_ms=None if first_body_ns is None else (first_body_ns - started_ns) / 1e6,
        total_ms=(finished_ns - started_ns) / 1e6,
        body_bytes=len(body),
        content_length=content_length,
        transfer_encoding=transfer_encoding,
        redirected=status in (301, 302, 303, 307, 308),
        body_sha256=sha256_hex(bytes(body)),
        headers=headers,
    )
