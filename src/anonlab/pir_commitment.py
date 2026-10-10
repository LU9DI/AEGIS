"""Experimental authenticated-database commitments for AEGIS PIR research.

This module provides Merkle inclusion proofs as a building block only. A proof
reveals the record index and therefore MUST NOT be attached to the private PIR
query path. It authenticates a record against a root; it does not prove that a
replica computed a PIR answer correctly.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Iterable

_HASH = hashlib.sha256
_LEAF_DOMAIN = b"AEGIS-PIR-MERKLE-v1/leaf\x00"
_NODE_DOMAIN = b"AEGIS-PIR-MERKLE-v1/node\x00"
_EMPTY_DOMAIN = b"AEGIS-PIR-MERKLE-v1/empty\x00"


def _leaf(index: int, record: bytes) -> bytes:
    if index < 0:
        raise ValueError("index must be non-negative")
    return _HASH(_LEAF_DOMAIN + index.to_bytes(8, "big") + len(record).to_bytes(8, "big") + record).digest()


def _node(left: bytes, right: bytes) -> bytes:
    if len(left) != 32 or len(right) != 32:
        raise ValueError("Merkle nodes must be SHA-256 digests")
    return _HASH(_NODE_DOMAIN + left + right).digest()


@dataclass(frozen=True)
class InclusionProof:
    index: int
    record_count: int
    record: bytes
    siblings: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class AuthenticatedSnapshot:
    """Immutable snapshot commitment and index-revealing inclusion proofs."""
    root: bytes
    record_count: int
    _levels: tuple[tuple[bytes, ...], ...]
    _records: tuple[bytes, ...]

    @classmethod
    def build(cls, records: Iterable[bytes]) -> "AuthenticatedSnapshot":
        rows = tuple(bytes(row) for row in records)
        if not rows:
            root = _HASH(_EMPTY_DOMAIN).digest()
            return cls(root, 0, ((root,),), rows)
        levels: list[tuple[bytes, ...]] = [tuple(_leaf(i, row) for i, row in enumerate(rows))]
        while len(levels[-1]) > 1:
            current = levels[-1]
            next_level = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else left
                next_level.append(_node(left, right))
            levels.append(tuple(next_level))
        return cls(levels[-1][0], len(rows), tuple(levels), rows)

    def proof(self, index: int) -> InclusionProof:
        if not 0 <= index < self.record_count:
            raise IndexError("record index out of range")
        cursor = index
        path: list[tuple[str, bytes]] = []
        for level in self._levels[:-1]:
            if cursor % 2:
                path.append(("left", level[cursor - 1]))
            else:
                sibling = cursor + 1 if cursor + 1 < len(level) else cursor
                path.append(("right", level[sibling]))
            cursor //= 2
        return InclusionProof(index, self.record_count, self._records[index], tuple(path))


def verify_inclusion(root: bytes, proof: InclusionProof) -> bool:
    """Verify inclusion using only the public root and proof; no exceptions escape."""
    try:
        if len(root) != 32 or proof.record_count <= 0 or not 0 <= proof.index < proof.record_count:
            return False
        expected_depth = 0
        width = proof.record_count
        while width > 1:
            expected_depth += 1
            width = (width + 1) // 2
        if len(proof.siblings) != expected_depth:
            return False
        digest = _leaf(proof.index, bytes(proof.record))
        cursor = proof.index
        width = proof.record_count
        for side, sibling in proof.siblings:
            if side not in ("left", "right") or len(sibling) != 32:
                return False
            # An odd final node is duplicated; its supplied sibling must be itself.
            if cursor == width - 1 and width % 2 == 1 and side == "right" and sibling != digest:
                return False
            digest = _node(sibling, digest) if side == "left" else _node(digest, sibling)
            cursor //= 2
            width = (width + 1) // 2
        return hmac.compare_digest(digest, root)
    except (TypeError, ValueError, OverflowError):
        return False
