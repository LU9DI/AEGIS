"""Loopback-only authenticated onion relay for the REA research lab."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from pathlib import Path

from cryptography.exceptions import InvalidTag

from .onion_protocol import CircuitReplayGuard, MAX_FRAME_BYTES, frame, parse_request_layer, wrap_response

LOG = logging.getLogger("anonlab.onion_relay")
_REPLAY_GUARD = CircuitReplayGuard()


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = int.from_bytes(header, "big")
    if length > MAX_FRAME_BYTES:
        raise ValueError("incoming frame exceeds maximum permitted size")
    return await reader.readexactly(length)


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    relay_id: str,
    key: bytes,
    allowed_next_port: int,
    terminal_relay: bool,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    upstream_reader: asyncio.StreamReader | None = None
    active_circuit_id: bytes | None = None
    expected_sequence = 0
    try:
        # A circuit keeps the next-hop TCP connection open and handles multiple
        # request/response frames. This lab's terminal destination is an echo
        # service, so response length equals request length.
        while True:
            try:
                encrypted_layer = await asyncio.wait_for(_read_frame(reader), timeout=60)
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    raise ValueError("truncated circuit frame") from exc
                break
            layer = parse_request_layer(key, relay_id, encrypted_layer)
            circuit_id = layer["circuit_id"]
            sequence = layer["sequence"]
            if not isinstance(circuit_id, bytes) or not isinstance(sequence, int):
                raise ValueError("request circuit metadata is invalid")
            if active_circuit_id is None:
                if sequence != 0:
                    raise ValueError("new circuit must begin with sequence zero")
                _REPLAY_GUARD.claim(circuit_id)
                active_circuit_id = circuit_id
            elif circuit_id != active_circuit_id:
                raise ValueError("circuit identifier changed on a live connection")
            if sequence != expected_sequence:
                raise ValueError("request sequence mismatch (replay, reordering, or circuit desynchronization)")
            if expected_sequence >= (1 << 64) - 1:
                raise ValueError("sequence exhausted; circuit must be replaced")
            if layer["next_port"] != allowed_next_port or layer["terminal"] is not terminal_relay:
                raise ValueError("request route does not match this relay's configured next hop")
            if upstream_writer is None:
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(layer["next_host"], layer["next_port"]), timeout=5
                )

            payload = layer["payload"]
            if not isinstance(payload, bytes):
                raise ValueError("decoded payload is not bytes")
            if terminal_relay:
                upstream_writer.write(payload)
                await upstream_writer.drain()
                response = await asyncio.wait_for(upstream_reader.readexactly(len(payload)), timeout=30)
            else:
                upstream_writer.write(frame(payload))
                await upstream_writer.drain()
                response = await asyncio.wait_for(_read_frame(upstream_reader), timeout=30)
            # Each hop adds a response layer. The client removes them in route order.
            writer.write(frame(wrap_response(
                key, relay_id, response, circuit_id=circuit_id, sequence=sequence
            )))
            await writer.drain()
            expected_sequence += 1
    except (asyncio.IncompleteReadError, ConnectionError, OSError, TimeoutError, ValueError, InvalidTag) as exc:
        LOG.debug("request rejected/ended: %s", type(exc).__name__)
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()
        if upstream_writer is not None:
            upstream_writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await upstream_writer.wait_closed()


async def run_server(
    host: str, port: int, relay_id: str, key: bytes, allowed_next_port: int, terminal_relay: bool
) -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle(reader, writer, relay_id, key, allowed_next_port, terminal_relay)

    server = await asyncio.start_server(handler, host, port, limit=64 * 1024)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--relay-id", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--allowed-next-port", type=int, required=True)
    parser.add_argument("--terminal-relay", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("experimental onion relay is loopback-only")
    if not 1 <= args.port <= 65535:
        parser.error("port must be within 1..65535")
    if not 1 <= args.allowed_next_port <= 65535:
        parser.error("allowed next-hop port must be within 1..65535")
    key = args.key_file.read_bytes()
    if len(key) != 32:
        parser.error("key file must contain exactly 32 raw bytes")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run_server(args.host, args.port, args.relay_id, key, args.allowed_next_port, args.terminal_relay))


if __name__ == "__main__":
    main()
