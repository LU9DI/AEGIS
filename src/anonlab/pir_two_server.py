"""Small, transparent two-server information-theoretic PIR reference prototype.

Two servers hold identical fixed-length records and are assumed not to collude.
Each server receives an individually uniform random bitmask; XORing the two
masked-XOR answers yields the requested record. This is intentionally a small
reference algorithm, not an efficient single-server PIR, encrypted protocol, or
website-fetch implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Sequence
import random

MAX_RECORDS = 4096
MAX_RECORD_BYTES = 1_048_576
MAX_DATABASE_BYTES = 64 * 1024 * 1024


def _mask_size(item_count: int) -> int:
    if not isinstance(item_count, int) or isinstance(item_count, bool) or not 1 <= item_count <= MAX_RECORDS:
        raise ValueError(f"item_count must be an integer in [1, {MAX_RECORDS}]")
    return (item_count + 7) // 8


def make_query_pair(
    item_count: int,
    target_index: int,
    *,
    rng: random.Random | random.SystemRandom | None = None,
) -> tuple[bytes, bytes]:
    """Create two fixed-size queries whose XOR is the target's one-hot mask.

    With no injected RNG, use the OS-backed SystemRandom. The optional RNG is
    useful for reproducible tests only and must not be used for secret queries.
    """
    mask_size = _mask_size(item_count)
    if not isinstance(target_index, int) or isinstance(target_index, bool) or not 0 <= target_index < item_count:
        raise ValueError("target_index must be within the database")
    chooser = rng if rng is not None else secrets.SystemRandom()
    first = bytearray(chooser.randbytes(mask_size))
    remainder = item_count % 8
    if remainder:
        first[-1] &= (1 << remainder) - 1
    second = bytearray(first)
    second[target_index // 8] ^= 1 << (target_index % 8)
    return bytes(first), bytes(second)


def _is_bit_set(mask: bytes, index: int) -> bool:
    return bool(mask[index // 8] & (1 << (index % 8)))


def _validate_records(records: Sequence[bytes]) -> tuple[bytes, ...]:
    if not isinstance(records, (tuple, list)) or not records:
        raise ValueError("records must be a non-empty tuple or list")
    _mask_size(len(records))
    item_count = len(records)
    normalized: list[bytes] = []
    for index, item in enumerate(records):
        if not isinstance(item, bytes):
            raise ValueError(f"record {index} must be bytes")
        if not 1 <= len(item) <= MAX_RECORD_BYTES:
            raise ValueError(f"record {index} length must be within 1..{MAX_RECORD_BYTES} bytes")
        normalized.append(item)
    record_length = len(normalized[0])
    if any(len(item) != record_length for item in normalized):
        raise ValueError("all records must have the same fixed length")
    if item_count * record_length > MAX_DATABASE_BYTES:
        raise ValueError(f"database exceeds {MAX_DATABASE_BYTES} bytes")
    return tuple(normalized)


class PirReferenceServer:
    """Stateless server side for the two-server PIR demo; never receives an index."""

    def __init__(self, records: Sequence[bytes]) -> None:
        self._records = _validate_records(records)
        self.item_count = len(self._records)
        self.record_bytes = len(self._records[0])
        self.query_bytes = _mask_size(self.item_count)

    def validate_query_mask(self, query_mask: bytes) -> None:
        """Validate query shape without doing database work or mutating server state."""
        if not isinstance(query_mask, bytes) or len(query_mask) != self.query_bytes:
            raise ValueError(f"query mask must be exactly {self.query_bytes} bytes")
        remainder = self.item_count % 8
        if remainder and query_mask[-1] & ~((1 << remainder) - 1):
            raise ValueError("query mask sets bits beyond the database size")

    def answer(self, query_mask: bytes) -> bytes:
        self.validate_query_mask(query_mask)
        result = bytearray(self.record_bytes)
        for index, record in enumerate(self._records):
            if _is_bit_set(query_mask, index):
                for offset, value in enumerate(record):
                    result[offset] ^= value
        return bytes(result)


@dataclass(frozen=True, slots=True)
class PirTransfer:
    record: bytes
    query_bytes_per_server: int
    response_bytes_per_server: int
    server_count: int = 2


def retrieve_two_server_pir(
    server_a: PirReferenceServer,
    server_b: PirReferenceServer,
    target_index: int,
    *,
    rng: random.Random | random.SystemRandom | None = None,
) -> PirTransfer:
    """Retrieve a record from two replicated, non-colluding servers.

    Correctness requires the databases at A and B to be identical. The servers
    do not receive target_index; only the client uses it to make the masks.
    If servers collude, XORing their masks directly reveals the requested index.
    """
    if server_a.item_count != server_b.item_count or server_a.record_bytes != server_b.record_bytes:
        raise ValueError("PIR replicas must have the same shape")
    query_a, query_b = make_query_pair(server_a.item_count, target_index, rng=rng)
    response_a = server_a.answer(query_a)
    response_b = server_b.answer(query_b)
    record = bytes(a ^ b for a, b in zip(response_a, response_b, strict=True))
    return PirTransfer(
        record=record,
        query_bytes_per_server=len(query_a),
        response_bytes_per_server=len(response_a),
    )
