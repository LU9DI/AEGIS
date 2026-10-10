"""Benchmark the research-only ntor key-agreement module on loopback."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .ntor_experiment import (
    CLIENT_HANDSHAKE_BYTES,
    SERVER_HANDSHAKE_BYTES,
    NtorReplayGuard,
    client_finish,
    client_start,
    relay_respond,
)

HOST = "127.0.0.1"


def _raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * quantile
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] * (1.0 - (pos - low)) + ordered[high] * (pos - low)


async def run_ntor_benchmark(rounds: int = 100) -> dict[str, Any]:
    """Measure crypto-only handshake time and one-request loopback handshake RTT.

    This tests one relay hop and key agreement only; it does not build an onion
    path or measure anonymity, bulk transfer, WAN latency, or browser performance.
    """
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 10_000:
        raise ValueError("rounds must be an integer between 1 and 10000")

    identity = os.urandom(20)
    relay_private = X25519PrivateKey.generate()
    relay_public = _raw_public(relay_private)
    crypto_ms: list[float] = []
    for _ in range(rounds):
        started = time.perf_counter()
        state, message = client_start(identity, relay_public)
        reply, relay_keys = relay_respond(message, identity, relay_private)
        client_keys = client_finish(state, reply)
        elapsed = (time.perf_counter() - started) * 1000.0
        if client_keys != relay_keys:
            raise RuntimeError("ntor client/relay key agreement mismatch")
        crypto_ms.append(elapsed)

    replay_guard = NtorReplayGuard(max_handshakes=rounds)

    async def read_handshake(reader: asyncio.StreamReader, expected_bytes: int) -> bytes:
        return await reader.readexactly(expected_bytes)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            message = await asyncio.wait_for(
                read_handshake(reader, CLIENT_HANDSHAKE_BYTES), timeout=3.0
            )
            reply, _ = relay_respond(
                message, identity, relay_private, replay_guard=replay_guard
            )
            writer.write(reply)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError, TimeoutError, ValueError):
            # Malformed and replayed handshakes are dropped without reflecting
            # exception details onto the wire.
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    port = _free_port()
    server = await asyncio.start_server(handler, HOST, port)
    wire_ms: list[float] = []
    try:
        async with server:
            for _ in range(rounds):
                state, message = client_start(identity, relay_public)
                started = time.perf_counter()
                reader, writer = await asyncio.open_connection(HOST, port)
                try:
                    writer.write(message)
                    await writer.drain()
                    reply = await asyncio.wait_for(
                        read_handshake(reader, SERVER_HANDSHAKE_BYTES), timeout=3.0
                    )
                    client_finish(state, reply)
                    wire_ms.append((time.perf_counter() - started) * 1000.0)
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except (ConnectionError, OSError):
                        pass
    finally:
        server.close()
        await server.wait_closed()

    elapsed_s = sum(wire_ms) / 1000.0
    return {
        "schema_version": 1,
        "experiment": "AEGIS ntor-derived one-hop handshake loopback benchmark",
        "is_anonymity_test": False,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "host": HOST,
        },
        "config": {"rounds": rounds, "relay_count": 1, "new_tcp_connection_per_handshake": True},
        "protocol": {
            "handshake_basis": "Tor ntor v1 transcript; MALEBOLGE-specific HKDF context for AEAD keys",
            "client_handshake_bytes": CLIENT_HANDSHAKE_BYTES,
            "relay_handshake_bytes": SERVER_HANDSHAKE_BYTES,
            "total_handshake_payload_bytes": CLIENT_HANDSHAKE_BYTES + SERVER_HANDSHAKE_BYTES,
        },
        "results": {
            "crypto_only_ms_p50": statistics.median(crypto_ms),
            "crypto_only_ms_p95": _percentile(crypto_ms, 0.95),
            "loopback_handshake_rtt_ms_p50": statistics.median(wire_ms),
            "loopback_handshake_rtt_ms_p95": _percentile(wire_ms, 0.95),
            "loopback_handshakes_per_second": rounds / elapsed_s if elapsed_s > 0 else None,
            "all_key_agreements_verified": len(wire_ms) == rounds,
        },
        "limitations": [
            "One local hop only; this does not implement a telescoping multi-hop circuit handshake.",
            "The relay identity digest and static onion key must come from an authenticated descriptor; this harness injects them directly.",
            "The handshake follows the ntor v1 authentication transcript but retains the legacy MALEBOLGE AEAD key-expansion context; it is not Tor-wire-compatible.",
            "Python cannot guarantee zeroization of ephemeral private key objects; secure key erasure is not proven.",
            "Loopback latency is not a WAN estimate and says nothing about resistance to traffic correlation.",
            "The module has not received independent cryptographic review and must not protect real or sensitive traffic.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_ntor_benchmark(args.rounds))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
