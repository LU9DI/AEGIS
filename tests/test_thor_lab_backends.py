"""Transport arm tests: counting proxy, SOCKS5 client, echo arms, HTTP GET."""
from __future__ import annotations

import asyncio
import importlib.util

import pytest

from anonlab.thor_lab.appproto import http_get, start_echo_server
from anonlab.thor_lab.backends import (
    AegisTelescopeBackend,
    BackendUnavailable,
    PlainChainBackend,
    SurfaceBackend,
    TorSocksBackend,
    probe_tor,
)
from anonlab.thor_lab.counting_proxy import CountingProxy
from anonlab.thor_lab.socks5 import Socks5Error, open_socks5

HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None


def test_counting_proxy_counts_both_directions() -> None:
    async def scenario() -> dict[str, int]:
        echo = await start_echo_server()
        proxy = CountingProxy(echo.host, echo.port)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            payload = b"x" * 5000
            writer.write(payload)
            await writer.drain()
            received = await asyncio.wait_for(reader.readexactly(len(payload)), timeout=10)
            assert received == payload
            # Give the reverse pump a moment to finish draining before closing.
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()
            return proxy.counters.as_dict()
        finally:
            await proxy.close()
            await echo.close()

    counters = asyncio.run(scenario())
    assert counters["accepted_connections"] == 1
    assert counters["client_to_upstream_bytes"] == 5000
    assert counters["upstream_to_client_bytes"] == 5000


def test_counting_proxy_max_connections_is_bounded() -> None:
    async def scenario() -> dict[str, int]:
        echo = await start_echo_server()
        proxy = CountingProxy(echo.host, echo.port, max_connections=1)
        await proxy.start()
        try:
            first_reader, first_writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            await asyncio.sleep(0.05)
            second_reader, second_writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            await asyncio.sleep(0.05)
            snapshot = proxy.counters.as_dict()
            first_writer.close()
            second_writer.close()
            for reader, writer in ((first_reader, first_writer), (second_reader, second_writer)):
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
                try:
                    await asyncio.wait_for(reader.read(1), timeout=5)
                except (ConnectionError, OSError, TimeoutError):
                    pass
            return snapshot
        finally:
            await proxy.close()
            await echo.close()

    counters = asyncio.run(scenario())
    assert counters["accepted_connections"] == 1
    assert counters["failed_connections"] == 1


def test_surface_arm_round_trips_payload_and_reports_setup() -> None:
    async def full() -> None:
        echo = await start_echo_server()
        try:
            backend = SurfaceBackend(echo.host, echo.port)
            await backend.start()
            try:
                connection = await backend.connect(timeout=10)
                assert connection.setup_steps[0].step == "tcp_connect"
                assert connection.setup_ms >= 0
                payload = bytes(range(256)) * 16
                await connection.stream.write(payload)
                received = await asyncio.wait_for(connection.stream.read(len(payload)), timeout=10)
                assert received == payload
                await connection.stream.close()
                await backend.after_trial()
            finally:
                await backend.close()
        finally:
            await echo.close()

    asyncio.run(full())


def test_plain_chain_arm_round_trips_through_three_hops() -> None:
    async def full() -> None:
        echo = await start_echo_server()
        try:
            backend = PlainChainBackend(echo.host, echo.port, hop_count=3)
            await backend.start()
            try:
                connection = await backend.connect(timeout=10)
                payload = b"plain-chain" * 512
                await connection.stream.write(payload)
                received = bytearray()
                while len(received) < len(payload):
                    chunk = await asyncio.wait_for(connection.stream.read(65536), timeout=10)
                    if not chunk:
                        break
                    received.extend(chunk)
                assert bytes(received) == payload
                await connection.stream.close()
                await backend.after_trial()
            finally:
                await backend.close()
        finally:
            await echo.close()

    asyncio.run(full())


@pytest.mark.skipif(not HAS_CRYPTO, reason="the onion-lab crypto extra is not installed")
def test_aegis_arm_round_trips_through_three_aead_hops() -> None:
    async def full() -> None:
        echo = await start_echo_server()
        try:
            backend = AegisTelescopeBackend(echo.host, echo.port, hop_count=3)
            await backend.start()
            try:
                connection = await backend.connect(timeout=30)
                steps = [step.step for step in connection.setup_steps]
                assert steps == ["guard_connect", "extend_1", "extend_2", "stream_open"]
                payload = b"aead-hop" * 1024
                await connection.stream.write_bulk(payload, chunk_bytes=8192, max_in_flight=4)
                received = bytearray()
                while len(received) < len(payload):
                    chunk = await asyncio.wait_for(connection.stream.read(65536), timeout=30)
                    if not chunk:
                        break
                    received.extend(chunk)
                assert bytes(received) == payload
                await connection.stream.close()
                await backend.after_trial()
            finally:
                await backend.close()
        finally:
            await echo.close()

    asyncio.run(full())


def test_tor_arm_reports_unavailable_without_a_socks_endpoint() -> None:
    async def full() -> None:
        backend = TorSocksBackend("example.com", 80, socks_port=1)
        with pytest.raises(BackendUnavailable) as excinfo:
            await backend.start()
        assert excinfo.value.reason == "socks_port_unreachable"
        probe = await probe_tor("127.0.0.1", 1, timeout=1.0)
        assert probe["available"] is False
        assert probe["reason"] == "socks_port_unreachable"

    asyncio.run(full())


def test_socks5_client_success_against_a_fake_proxy() -> None:
    async def fake_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        greeting = await reader.readexactly(3)
        assert greeting == b"\x05\x01\x00"
        writer.write(b"\x05\x00")
        await writer.drain()
        head = await reader.readexactly(4)
        assert head[0] == 0x05 and head[1] == 0x01
        atyp = head[3]
        if atyp == 0x01:
            await reader.readexactly(4)
        elif atyp == 0x03:
            length = await reader.readexactly(1)
            await reader.readexactly(length[0])
        else:
            await reader.readexactly(16)
        await reader.readexactly(2)
        writer.write(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
        await writer.drain()
        payload = await reader.readexactly(4)
        writer.write(payload.upper())
        await writer.drain()
        writer.close()

    async def full() -> None:
        server = await asyncio.start_server(fake_proxy, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        try:
            reader, writer = await open_socks5("127.0.0.1", port, "example.com", 80, timeout=5)
            writer.write(b"ping")
            await writer.drain()
            assert await reader.readexactly(4) == b"PING"
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(full())


def test_socks5_client_surfaces_reply_codes() -> None:
    async def refusing_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readexactly(3)
        writer.write(b"\x05\x00")
        await writer.drain()
        await reader.readexactly(4)
        await reader.readexactly(6)
        writer.write(b"\x05\x05\x00\x01" + b"\x00" * 4 + b"\x00\x00")
        await writer.drain()
        writer.close()

    async def full() -> None:
        server = await asyncio.start_server(refusing_proxy, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        try:
            with pytest.raises(Socks5Error) as excinfo:
                await open_socks5("127.0.0.1", port, "127.0.0.1", 80, timeout=5)
            assert excinfo.value.reply_code == 0x05
            assert "connection refused" in str(excinfo.value)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(full())


def test_http_get_parses_content_length_and_chunked_bodies() -> None:
    body = b"0123456789" * 100

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        request_line = request.split(b"\r\n", 1)[0]
        if b"/chunked" in request_line:
            writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            for start in range(0, len(body), 128):
                piece = body[start : start + 128]
                writer.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
            writer.write(b"0\r\n\r\n")
        elif b"/missing" in request_line:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        else:
            assert request_line.startswith(b"GET /file")
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        await writer.drain()
        writer.close()

    async def full() -> None:
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        try:
            for path, expected_status in (("/file", 200), ("/file-chunked", 200), ("/missing", 404)):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                try:
                    result = await http_get(reader, writer, host="127.0.0.1", path=path, timeout=10)
                finally:
                    writer.close()
                    await writer.wait_closed()
                assert result.status == expected_status
                if expected_status == 200:
                    assert result.body_bytes == len(body)
                    assert result.first_body_byte_ms is not None
                else:
                    assert result.body_bytes == 0
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(full())


def test_http_get_rejects_a_truncated_body() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4096\r\n\r\nshort")
        await writer.drain()
        writer.close()

    async def full() -> None:
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            with pytest.raises((ValueError, ConnectionError, asyncio.IncompleteReadError)):
                await http_get(reader, writer, host="127.0.0.1", path="/truncated", timeout=5)
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(full())


def test_echo_exchange_through_surface_reports_wire_bytes() -> None:
    async def full() -> None:
        echo = await start_echo_server()
        backend = SurfaceBackend(echo.host, echo.port)
        await backend.start()
        try:
            before = backend.edge_snapshot()
            assert before is not None
            connection = await backend.connect(timeout=10)
            payload = b"z" * 4096
            await connection.stream.write(payload)
            received = await asyncio.wait_for(connection.stream.read(len(payload)), timeout=10)
            assert received == payload
            # Let the reverse pump finish accounting before sampling the counters.
            await asyncio.sleep(0.05)
            after = backend.edge_snapshot()
            assert after is not None
            await connection.stream.close()
            await backend.after_trial()
            assert after["client_to_upstream_bytes"] - before["client_to_upstream_bytes"] == len(payload)
            assert after["upstream_to_client_bytes"] - before["upstream_to_client_bytes"] == len(payload)
        finally:
            await backend.close()
            await echo.close()

    asyncio.run(full())
