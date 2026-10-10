"""Chunk-level 2-of-2 XOR secret-sharing prototype for independent paths.

Each share is individually uniformly random when the random source is secure.
This module does not provide a transport, path independence, traffic-analysis
resistance, or an authentication channel. A global observer that sees both
shares can reconstruct the payload; a share corruption is detected after
reconstruction using a client-side digest.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
from typing import Callable, Sequence

from . import __version__

_DEFAULT_CHUNK_SIZE = 4096
_MAX_CHUNK_SIZE = 1024 * 1024
_MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SecretShare:
    chunks: tuple[bytes, ...]
    chunk_size: int

    @property
    def padded_bytes(self) -> int:
        return sum(len(chunk) for chunk in self.chunks)


@dataclass(frozen=True, slots=True)
class ShareManifest:
    """Client-local metadata; do not send this plaintext manifest to a relay."""
    original_length: int
    chunk_count: int
    chunk_size: int
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class SplitSummary:
    original_bytes: int
    padded_bytes_per_path: int
    chunk_count: int
    chunk_size: int
    reconstructed_sha256: str
    integrity_verified: bool
    warning: str = (
        "Prototype only: any relay/common guard or global observer seeing both shares can reconstruct; "
        "size bucket and timing leak, and path independence is not implemented."
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": __version__,
            "original_bytes": self.original_bytes,
            "padded_bytes_per_path": self.padded_bytes_per_path,
            "chunk_count": self.chunk_count,
            "chunk_size": self.chunk_size,
            "reconstructed_sha256": self.reconstructed_sha256,
            "integrity_verified": self.integrity_verified,
            "is_networked_demo": False,
            "warning": self.warning,
        }


def split_payload(
    payload: bytes,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    random_bytes: Callable[[int], bytes] = secrets.token_bytes,
) -> tuple[SecretShare, SecretShare, ShareManifest]:
    """Split payload into fixed-width XOR shares; manifest remains client-local."""
    if not isinstance(payload, bytes):
        raise ValueError("payload must be bytes")
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds the configured research limit")
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or not 1 <= chunk_size <= _MAX_CHUNK_SIZE:
        raise ValueError(f"chunk_size must be within 1..{_MAX_CHUNK_SIZE}")
    chunks_a: list[bytes] = []
    chunks_b: list[bytes] = []
    for offset in range(0, len(payload), chunk_size):
        raw = payload[offset:offset + chunk_size]
        padded = raw + bytes(chunk_size - len(raw))
        share_a = random_bytes(chunk_size)
        if not isinstance(share_a, bytes) or len(share_a) != chunk_size:
            raise ValueError("random_bytes must return exactly chunk_size bytes")
        share_b = bytes(a ^ b for a, b in zip(padded, share_a))
        chunks_a.append(share_a)
        chunks_b.append(share_b)
    share_a_obj = SecretShare(tuple(chunks_a), chunk_size)
    share_b_obj = SecretShare(tuple(chunks_b), chunk_size)
    manifest = ShareManifest(
        original_length=len(payload),
        chunk_count=len(chunks_a),
        chunk_size=chunk_size,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    return share_a_obj, share_b_obj, manifest


def reconstruct_payload(share_a: SecretShare, share_b: SecretShare, manifest: ShareManifest) -> bytes:
    if share_a.chunk_size != share_b.chunk_size or share_a.chunk_size != manifest.chunk_size:
        raise ValueError("share chunk sizes do not match manifest")
    expected_count = (manifest.original_length + manifest.chunk_size - 1) // manifest.chunk_size
    if manifest.original_length < 0 or expected_count != manifest.chunk_count:
        raise ValueError("manifest length/chunk-count mismatch")
    if len(share_a.chunks) != manifest.chunk_count or len(share_b.chunks) != manifest.chunk_count:
        raise ValueError("share count does not match manifest")
    output = bytearray()
    for a, b in zip(share_a.chunks, share_b.chunks):
        if len(a) != manifest.chunk_size or len(b) != manifest.chunk_size:
            raise ValueError("share contains a malformed chunk")
        output.extend(x ^ y for x, y in zip(a, b))
    payload = bytes(output[:manifest.original_length])
    digest = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(digest, manifest.payload_sha256):
        raise ValueError("reconstructed payload integrity check failed")
    return payload


def run_demo(payload: bytes, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> SplitSummary:
    a, b, manifest = split_payload(payload, chunk_size=chunk_size)
    recovered = reconstruct_payload(a, b, manifest)
    digest = hashlib.sha256(recovered).hexdigest()
    return SplitSummary(
        original_bytes=len(payload),
        padded_bytes_per_path=a.padded_bytes,
        chunk_count=len(a.chunks),
        chunk_size=chunk_size,
        reconstructed_sha256=digest,
        integrity_verified=(recovered == payload),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS local XOR-share demo (no network transport)")
    parser.add_argument("--payload-bytes", type=int, default=65537)
    parser.add_argument("--chunk-size", type=int, default=_DEFAULT_CHUNK_SIZE)
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.payload_bytes <= _MAX_PAYLOAD_BYTES:
            raise ValueError(f"--payload-bytes must be within 0..{_MAX_PAYLOAD_BYTES}")
        demo_payload = bytes((idx * 31 + 7) % 256 for idx in range(args.payload_bytes))
        print(json.dumps(run_demo(demo_payload, chunk_size=args.chunk_size).to_dict(), indent=2, sort_keys=True))
        return 0
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
