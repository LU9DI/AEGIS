"""Run the small two-server PIR reference demonstration."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random

from . import __version__
from .pir_two_server import PirReferenceServer, retrieve_two_server_pir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-pir-demo", description="AEGIS two-server PIR reference demo (not production PIR)")
    parser.add_argument("--items", type=int, default=16, help="number of fixed-size records (1..4096)")
    parser.add_argument("--index", type=int, default=5, help="client-local record index to retrieve")
    parser.add_argument("--record-bytes", type=int, default=64, help="fixed record size in bytes")
    parser.add_argument("--seed", type=int, default=None, help="optional reproducible non-cryptographic demo seed")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1 <= args.items <= 4096:
        raise SystemExit("--items must be within 1..4096")
    if not 1 <= args.record_bytes <= 1_048_576:
        raise SystemExit("--record-bytes must be within 1..1048576")
    if not 0 <= args.index < args.items:
        raise SystemExit("--index must be within the item range")
    records = tuple(
        hashlib.shake_256(f"AEGIS PIR demo record {index}".encode("ascii")).digest(args.record_bytes)
        for index in range(args.items)
    )
    server_a = PirReferenceServer(records)
    server_b = PirReferenceServer(records)
    rng = random.Random(args.seed) if args.seed is not None else None
    transfer = retrieve_two_server_pir(server_a, server_b, args.index, rng=rng)
    expected_digest = hashlib.sha256(records[args.index]).hexdigest()
    obtained_digest = hashlib.sha256(transfer.record).hexdigest()
    payload = {
        "metadata": {
            "project": "AEGIS",
            "version": __version__,
            "protocol": "two-server-XOR-PIR-reference-v1",
            "is_live_network_test": False,
            "is_security_proof": False,
            "seeded_rng_is_not_cryptographic": args.seed is not None,
            "warning": "Requires identical replicas and non-colluding servers. This prototype is bandwidth-inefficient and does not fetch complete websites.",
        },
        "result": {
            "retrieval_correct": obtained_digest == expected_digest,
            "record_sha256": obtained_digest,
            "client_local_target_index": args.index,
            "server_count": transfer.server_count,
            "query_bytes_per_server": transfer.query_bytes_per_server,
            "response_bytes_per_server": transfer.response_bytes_per_server,
            "total_response_bytes": transfer.response_bytes_per_server * transfer.server_count,
            "colluding_servers_can_recover_index": True,
        },
    }
    rendered = json.dumps(payload, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
