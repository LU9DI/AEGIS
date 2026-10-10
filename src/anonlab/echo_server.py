"""Loopback echo destination for local relay-chain measurements."""
from __future__ import annotations

import argparse
import asyncio
import contextlib


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(64 * 1024)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()


async def run_server(host: str, port: int) -> None:
    server = await asyncio.start_server(_handle, host, port, limit=128 * 1024)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("the test echo service must bind to loopback")
    asyncio.run(run_server(args.host, args.port))


if __name__ == "__main__":
    main()
