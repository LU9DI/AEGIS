"""Run two authenticated PIR replicas on separate loopback TCP ports."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
from pathlib import Path
from typing import Sequence

from . import __version__
from .pir_rpc import AuthenticatedPirRpcServer, PirRpcEndpoint, retrieve_two_server_pir_rpc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis-pir-rpc-demo",
        description="AEGIS two-endpoint HMAC-authenticated loopback PIR demonstration (not production transport)",
    )
    parser.add_argument("--records", type=int, default=64, help="fixed-width replicated records (1..4096)")
    parser.add_argument("--index", type=int, default=17, help="client-local index to retrieve")
    parser.add_argument("--record-bytes", type=int, default=32, help="record width in bytes")
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser


async def _run_demo(records_count: int, index: int, record_bytes: int) -> dict[str, object]:
    records = tuple(
        hashlib.shake_256(f"AEGIS authenticated PIR row {i}".encode("ascii")).digest(record_bytes)
        for i in range(records_count)
    )
    key_a, key_b = secrets.token_bytes(32), secrets.token_bytes(32)
    if key_a == key_b:
        key_b = secrets.token_bytes(32)

    async with (
        AuthenticatedPirRpcServer(records, server_id="replica-a", shared_key=key_a) as server_a,
        AuthenticatedPirRpcServer(records, server_id="replica-b", shared_key=key_b) as server_b,
    ):
        assert server_a.port is not None and server_b.port is not None
        endpoints = (
            PirRpcEndpoint("replica-a", "127.0.0.1", server_a.port, key_a),
            PirRpcEndpoint("replica-b", "127.0.0.1", server_b.port, key_b),
        )
        ports_distinct = server_a.port != server_b.port
        transfer = await retrieve_two_server_pir_rpc(endpoints, records_count, index, record_bytes=record_bytes)

    expected_digest = hashlib.sha256(records[index]).hexdigest()
    obtained_digest = hashlib.sha256(transfer.record).hexdigest()
    return {
        "metadata": {
            "project": "AEGIS",
            "version": __version__,
            "protocol": "AEGIS-PIR-RPC-v1",
            "network_mode": "loopback TCP; two separate listening endpoints in one process",
            "authentication": "per-endpoint HMAC-SHA256 with independent demo pre-shared keys",
            "encrypted_transport": False,
            "is_production_secure": False,
            "is_live_remote_network_test": False,
            "is_security_proof": False,
            "warning": (
                "Loopback-only transport. HMAC authenticates message possession of a shared key but does not encrypt traffic; "
                "the shared key is unsuitable for untrusted public clients. Deployments need authenticated confidential transport, "
                "independent operators, identical database snapshots, and a separate anonymity layer. Two colluding replicas recover the index."
            ),
        },
        "result": {
            "retrieval_correct": obtained_digest == expected_digest,
            "record_sha256": obtained_digest,
            "client_local_target_index": index,
            "replica_ids": list(transfer.server_ids),
            "replica_ports_distinct": ports_distinct,
            "query_bytes_per_replica": transfer.query_bytes_per_server,
            "response_bytes_per_replica": transfer.response_bytes_per_server,
            "authenticated_messages": transfer.authenticated_messages,
            "collusion_recovers_index": True,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.records <= 4096:
        parser.error("--records must be within 1..4096")
    if not 1 <= args.record_bytes <= 1_048_576:
        parser.error("--record-bytes must be within 1..1048576")
    if not 0 <= args.index < args.records:
        parser.error("--index must be within the record range")
    try:
        result = asyncio.run(_run_demo(args.records, args.index, args.record_bytes))
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
