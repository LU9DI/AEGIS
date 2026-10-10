"""TLS transport demonstration for two-server XOR PIR over local TCP listeners."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import ssl
from pathlib import Path
from typing import Sequence

from . import __version__
from .pir_rpc import (
    DEFAULT_MAX_REQUESTS_PER_SECOND, DEFAULT_REQUEST_BURST,
    AuthenticatedPirRpcServer, PirRpcEndpoint, retrieve_two_server_pir_rpc,
)


def _server_context(cert_file: Path, key_file: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert_file), str(key_file))
    return context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis-pir-rpc-tls-demo",
        description="TLS-verified two-replica PIR demonstration (local listeners; not a remote deployment test)",
    )
    parser.add_argument("--ca-cert", type=Path, required=True, help="trusted CA certificate PEM for both replica certificates")
    parser.add_argument("--cert-a", type=Path, required=True, help="replica A certificate PEM")
    parser.add_argument("--key-a", type=Path, required=True, help="replica A private key PEM")
    parser.add_argument("--cert-b", type=Path, required=True, help="replica B certificate PEM")
    parser.add_argument("--key-b", type=Path, required=True, help="replica B private key PEM")
    parser.add_argument("--server-name-a", default="replica-a.test", help="DNS SAN expected in replica A certificate")
    parser.add_argument("--server-name-b", default="replica-b.test", help="DNS SAN expected in replica B certificate")
    parser.add_argument("--records", type=int, default=64, help="fixed-width replicated records (1..4096)")
    parser.add_argument("--index", type=int, default=17, help="client-local index to retrieve")
    parser.add_argument("--record-bytes", type=int, default=32, help="record width in bytes")
    parser.add_argument(
        "--max-requests-per-second", type=float, default=DEFAULT_MAX_REQUESTS_PER_SECOND,
        help="per-replica aggregate request rate cap (no per-client identity tracking)",
    )
    parser.add_argument(
        "--request-burst", type=int, default=DEFAULT_REQUEST_BURST,
        help="per-replica token-bucket burst capacity",
    )
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser


async def _run_demo(args: argparse.Namespace) -> dict[str, object]:
    records = tuple(
        hashlib.shake_256(f"AEGIS TLS PIR row {i}".encode("ascii")).digest(args.record_bytes)
        for i in range(args.records)
    )
    context_a = _server_context(args.cert_a, args.key_a)
    context_b = _server_context(args.cert_b, args.key_b)
    client_context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=str(args.ca_cert))
    client_context.minimum_version = ssl.TLSVersion.TLSv1_2

    async with (
        AuthenticatedPirRpcServer(
            records, server_id="replica-a", ssl_context=context_a,
            max_requests_per_second=args.max_requests_per_second, request_burst=args.request_burst,
        ) as server_a,
        AuthenticatedPirRpcServer(
            records, server_id="replica-b", ssl_context=context_b,
            max_requests_per_second=args.max_requests_per_second, request_burst=args.request_burst,
        ) as server_b,
    ):
        assert server_a.port is not None and server_b.port is not None
        endpoints = (
            PirRpcEndpoint("replica-a", "127.0.0.1", server_a.port, ssl_context=client_context,
                           server_hostname=args.server_name_a),
            PirRpcEndpoint("replica-b", "127.0.0.1", server_b.port, ssl_context=client_context,
                           server_hostname=args.server_name_b),
        )
        transfer = await retrieve_two_server_pir_rpc(
            endpoints, args.records, args.index, record_bytes=args.record_bytes
        )
        ports_distinct = server_a.port != server_b.port
        aggregate_stats_a = server_a.aggregate_stats
        aggregate_stats_b = server_b.aggregate_stats

    record_digest = hashlib.sha256(records[args.index]).hexdigest()
    obtained_digest = hashlib.sha256(transfer.record).hexdigest()
    return {
        "metadata": {
            "project": "AEGIS",
            "version": __version__,
            "protocol": "AEGIS-PIR-RPC-v1",
            "network_mode": "TLS over two separate local TCP listeners in one process",
            "transport": transfer.transport,
            "client_shared_hmac_keys_distributed": False,
            "client_certificate_required": False,
            "is_production_secure": False,
            "is_live_remote_network_test": False,
            "is_security_proof": False,
            "warning": (
                "This demonstrates server certificate and hostname verification plus TLS confidentiality/integrity. "
                "The listeners still run on one machine/process; the global endpoint rate limit is not per-client, "
                "does not prevent distributed abuse, and is not a substitute for edge protection. No remote operator "
                "independence, authenticated database update protocol, verifiable server computation, "
                "anonymous-network circuit, or protection from two-server collusion is proved."
            ),
        },
        "result": {
            "retrieval_correct": obtained_digest == record_digest,
            "record_sha256": obtained_digest,
            "client_local_target_index": args.index,
            "replica_ids": list(transfer.server_ids),
            "replica_ports_distinct": ports_distinct,
            "query_bytes_per_replica": transfer.query_bytes_per_server,
            "response_bytes_per_replica": transfer.response_bytes_per_server,
            "tls_server_identity_verified": True,
            "client_index_sent_to_servers": False,
            "two_server_collusion_can_recover_index": True,
            "replica_a_aggregate_stats": aggregate_stats_a,
            "replica_b_aggregate_stats": aggregate_stats_b,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.records <= 4096:
        parser.error("--records must be within 1..4096")
    if not 1 <= args.record_bytes <= 1_048_576:
        parser.error("--record-bytes must be within 1..1048576")
    if args.records * args.record_bytes > 64 * 1024 * 1024:
        parser.error("database exceeds the configured 64 MiB demo limit")
    if not 0 <= args.index < args.records:
        parser.error("--index must be within the record range")
    if not 0.1 <= args.max_requests_per_second <= 10_000:
        parser.error("--max-requests-per-second must be within 0.1..10000")
    if not 1 <= args.request_burst <= 10_000:
        parser.error("--request-burst must be within 1..10000")
    try:
        result = asyncio.run(_run_demo(args))
    except (OSError, RuntimeError, ValueError, ssl.SSLError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
