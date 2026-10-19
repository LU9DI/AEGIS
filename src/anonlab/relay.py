"""Minimal TCP relay used only by the local performance testbed.

This is deliberately not an anonymity protocol: it does not encrypt traffic,
remove metadata, isolate circuits, or defend against traffic correlation. The
server binds to loopback by default and should not be exposed to the Internet.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

LOG = logging.getLogger("anonlab.relay")
CHUNK_BYTES = 64 * 1024


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(CHUNK_BYTES)
            if not data:
                break
            writer.write(data)
            await writer.drain()
        with contextlib.suppress(AttributeError, OSError, RuntimeError):
            writer.write_eof()
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        raise


async def _handle(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_host: str,
    upstream_port: int,
) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    tasks: set[asyncio.Task[None]] = set()
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(
            upstream_host, upstream_port
        )
        tasks = {
            asyncio.create_task(_pipe(client_reader, upstream_writer)),
            asyncio.create_task(_pipe(upstream_reader, client_writer)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            error = task.exception()
            if error is not None:
                raise error
        # Normal half-close is expected to finish each direction in sequence.
        if pending:
            await asyncio.gather(*pending)
    except (ConnectionError, asyncio.IncompleteReadError, OSError) as exc:
        LOG.debug("relay connection ended: %s", exc)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        client_writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await client_writer.wait_closed()
        if upstream_writer is not None:
            upstream_writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await upstream_writer.wait_closed()


async def run_server(host: str, listen_port: int, upstream_host: str, upstream_port: int) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, upstream_host, upstream_port),
        host,
        listen_port,
        limit=CHUNK_BYTES * 2,
    )
    LOG.info("relay listening on %s:%d -> %s:%d", host, listen_port, upstream_host, upstream_port)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind host (loopback only for this testbed)")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("this relay is loopback-only; do not expose it to a network")
    asyncio.run(run_server(args.host, args.listen_port, args.upstream_host, args.upstream_port))


if __name__ == "__main__":
    main()
