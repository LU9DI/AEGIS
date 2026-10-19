"""Two-server XOR PIR reference implementation for fixed-width replicated records.

This is an educational, information-theoretic two-server construction. The
servers must hold identical databases and must not collude. The prototype is
not an encrypted database service and does not hide the client's network
identity, timing, or total query size. Query cost is O(number of rows).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import secrets
from typing import Sequence

from . import __version__


@dataclass(frozen=True, slots=True)
class PIRQueryPair:
    """Two masked queries; intentionally contains no selected row index."""
    server_a: bytes
    server_b: bytes
    record_count: int

    @property
    def query_bytes_per_server(self) -> int:
        return len(self.server_a)


@dataclass(frozen=True, slots=True)
class PIRResult:
    record: bytes
    record_count: int
    query_bytes_per_server: int
    response_bytes_per_server: int
    computation_rows_per_server: int
    security_model: str = "single-server query privacy if two replicated servers do not collude"

    def to_dict(self) -> dict[str, object]:
        return {
            "version": __version__,
            "record_hex": self.record.hex(),
            "record_count": self.record_count,
            "query_bytes_per_server": self.query_bytes_per_server,
            "response_bytes_per_server": self.response_bytes_per_server,
            "computation_rows_per_server": self.computation_rows_per_server,
            "security_model": self.security_model,
            "uses_fhe": False,
            "uses_zero_knowledge_proofs": False,
            "is_networked_demo": False,
            "warning": "Both servers colluding can XOR their queries and recover the requested index. Traffic metadata is not hidden by PIR.",
        }


def _query_len(record_count: int) -> int:
    if not isinstance(record_count, int) or isinstance(record_count, bool) or record_count < 1:
        raise ValueError("record_count must be an integer >= 1")
    return (record_count + 7) // 8


def _pack_queries_from_mask(record_count: int, index: int, mask_value: int) -> tuple[bytes, bytes]:
    length = _query_len(record_count)
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < record_count:
        raise ValueError("index is outside the database")
    if not isinstance(mask_value, int) or isinstance(mask_value, bool) or mask_value < 0 or mask_value >= (1 << record_count):
        raise ValueError("mask_value must fit the query bit-vector")
    query_a = mask_value
    query_b = mask_value ^ (1 << index)
    return query_a.to_bytes(length, "little"), query_b.to_bytes(length, "little")


def create_queries(record_count: int, index: int, *, _mask_value_for_testing: int | None = None) -> PIRQueryPair:
    """Create a uniform mask and its one-bit-flipped twin for two servers.

    `_mask_value_for_testing` is intentionally underscored and exists only for
    exhaustive tests. Production calls use a cryptographically secure RNG.
    """
    length = _query_len(record_count)
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < record_count:
        raise ValueError("index is outside the database")
    if _mask_value_for_testing is None:
        mask = int.from_bytes(secrets.token_bytes(length), "little") & ((1 << record_count) - 1)
    else:
        mask = _mask_value_for_testing
    query_a, query_b = _pack_queries_from_mask(record_count, index, mask)
    return PIRQueryPair(query_a, query_b, record_count)


def answer_query(query: bytes, records: Sequence[bytes]) -> bytes:
    """Compute XOR of the rows selected by one query vector."""
    if not records:
        raise ValueError("database must contain at least one record")
    if not all(isinstance(row, bytes) for row in records):
        raise ValueError("all database records must be bytes")
    row_size = len(records[0])
    if row_size < 1 or any(len(row) != row_size for row in records):
        raise ValueError("database rows must have a common positive byte length")
    length = _query_len(len(records))
    if not isinstance(query, bytes) or len(query) != length:
        raise ValueError("query length does not match database size")
    if len(records) % 8 and query[-1] >> (len(records) % 8):
        raise ValueError("query has non-zero unused high bits")
    answer = bytearray(row_size)
    for idx, row in enumerate(records):
        if query[idx >> 3] & (1 << (idx & 7)):
            for pos, byte in enumerate(row):
                answer[pos] ^= byte
    return bytes(answer)


def recover_record(answer_a: bytes, answer_b: bytes) -> bytes:
    if not isinstance(answer_a, bytes) or not isinstance(answer_b, bytes) or not answer_a or len(answer_a) != len(answer_b):
        raise ValueError("server answers must have the same positive byte length")
    return bytes(a ^ b for a, b in zip(answer_a, answer_b))


def retrieve_for_demo(records: Sequence[bytes], index: int) -> PIRResult:
    """Run both non-colluding server computations locally; no network is used."""
    if not records or any(not isinstance(row, bytes) for row in records):
        raise ValueError("records must be a non-empty sequence of bytes")
    if any(len(row) != len(records[0]) or not row for row in records):
        raise ValueError("all records must share a positive fixed width")
    queries = create_queries(len(records), index)
    a = answer_query(queries.server_a, records)
    b = answer_query(queries.server_b, records)
    result = recover_record(a, b)
    if len(result) != len(records[index]) or result != records[index]:
        raise RuntimeError("PIR reconstruction integrity check failed")
    return PIRResult(
        record=result,
        record_count=len(records),
        query_bytes_per_server=queries.query_bytes_per_server,
        response_bytes_per_server=len(a),
        computation_rows_per_server=len(records),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS two-server XOR PIR local demonstration")
    parser.add_argument("--records", type=int, default=64)
    parser.add_argument("--index", type=int, default=17)
    args = parser.parse_args(argv)
    try:
        if args.records < 1 or args.records > 65536:
            raise ValueError("--records must be within 1..65536")
        records = [f"demo-row-{i:08d}".encode("ascii").ljust(32, b" ") for i in range(args.records)]
        result = retrieve_for_demo(records, args.index)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
