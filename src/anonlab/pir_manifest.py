"""Signed snapshot manifests and anti-rollback checkpoints for AEGIS PIR.

This authenticates *which database snapshot* a client expects. It does not prove
that a PIR replica evaluated a query correctly. Public keys must be provisioned
out of band; deployments must persist checkpoints durably to resist rollback
across process restarts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except ImportError as exc:  # pragma: no cover - depends on optional extra
    raise ImportError("Signed PIR manifests require the optional 'cryptography' package") from exc

_MANIFEST_DOMAIN = b"AEGIS-PIR-SNAPSHOT-MANIFEST-v1\x00"
SCHEMA_VERSION = 1


class ManifestError(ValueError):
    """A manifest is malformed, unauthenticated, stale, or rolled back."""


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True)
class SnapshotManifest:
    schema_version: int
    snapshot_id: str
    sequence: int
    created_at: int
    record_count: int
    merkle_root: bytes
    signature: bytes

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "sequence": self.sequence,
            "created_at": self.created_at,
            "record_count": self.record_count,
            "merkle_root": self.merkle_root.hex(),
        }

    def digest(self) -> bytes:
        """Stable digest used to pin an accepted manifest in a checkpoint."""
        return hashlib.sha256(_MANIFEST_DOMAIN + _canonical(self.payload()) + self.signature).digest()


def _validate_fields(
    schema_version: int, snapshot_id: str, sequence: int, created_at: int,
    record_count: int, merkle_root: bytes,
) -> None:
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise ManifestError("unsupported manifest schema")
    if not isinstance(snapshot_id, str) or not snapshot_id or len(snapshot_id) > 128:
        raise ManifestError("snapshot_id must contain 1..128 characters")
    if any(ord(ch) < 0x20 for ch in snapshot_id):
        raise ManifestError("snapshot_id contains control characters")
    if type(sequence) is not int or sequence < 0:
        raise ManifestError("sequence must be a non-negative integer")
    if type(created_at) is not int or created_at <= 0:
        raise ManifestError("created_at must be a positive Unix timestamp")
    if type(record_count) is not int or record_count < 0:
        raise ManifestError("record_count must be a non-negative integer")
    if not isinstance(merkle_root, bytes) or len(merkle_root) != 32:
        raise ManifestError("merkle_root must be a 32-byte SHA-256 digest")


def sign_snapshot_manifest(
    *, private_key: Ed25519PrivateKey, snapshot_id: str, sequence: int,
    created_at: int, record_count: int, merkle_root: bytes,
) -> SnapshotManifest:
    """Sign snapshot metadata; keep the signing key with the dataset authority."""
    _validate_fields(SCHEMA_VERSION, snapshot_id, sequence, created_at, record_count, merkle_root)
    unsigned = SnapshotManifest(SCHEMA_VERSION, snapshot_id, sequence, created_at,
                                record_count, bytes(merkle_root), b"")
    signature = private_key.sign(_MANIFEST_DOMAIN + _canonical(unsigned.payload()))
    return SnapshotManifest(**{**unsigned.__dict__, "signature": signature})


def verify_snapshot_manifest(
    manifest: SnapshotManifest, public_key: Ed25519PublicKey, *,
    now: int | None = None, max_age_seconds: int | None = None,
    allowed_future_skew_seconds: int = 60,
) -> None:
    """Verify signature, schema and optional freshness; raises ManifestError on failure."""
    try:
        _validate_fields(manifest.schema_version, manifest.snapshot_id, manifest.sequence,
                         manifest.created_at, manifest.record_count, manifest.merkle_root)
        if not isinstance(manifest.signature, bytes) or len(manifest.signature) != 64:
            raise ManifestError("invalid Ed25519 signature length")
        public_key.verify(manifest.signature, _MANIFEST_DOMAIN + _canonical(manifest.payload()))
    except InvalidSignature as exc:
        raise ManifestError("snapshot manifest signature verification failed") from exc
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError("malformed snapshot manifest") from exc

    current = int(time.time()) if now is None else now
    if type(current) is not int or type(allowed_future_skew_seconds) is not int or allowed_future_skew_seconds < 0:
        raise ManifestError("invalid time policy")
    if manifest.created_at > current + allowed_future_skew_seconds:
        raise ManifestError("snapshot manifest is dated in the future")
    if max_age_seconds is not None:
        if type(max_age_seconds) is not int or max_age_seconds < 0:
            raise ManifestError("max_age_seconds must be a non-negative integer")
        if current - manifest.created_at > max_age_seconds:
            raise ManifestError("snapshot manifest is stale")


@dataclass
class SnapshotCheckpoint:
    """In-memory anti-rollback state; persist sequence and digest durably in deployments."""
    sequence: int = -1
    manifest_digest: bytes | None = None

    def verify_and_advance(
        self, manifest: SnapshotManifest, public_key: Ed25519PublicKey, *,
        now: int | None = None, max_age_seconds: int | None = None,
    ) -> None:
        verify_snapshot_manifest(manifest, public_key, now=now, max_age_seconds=max_age_seconds)
        digest = manifest.digest()
        if manifest.sequence < self.sequence:
            raise ManifestError("snapshot rollback rejected")
        if manifest.sequence == self.sequence:
            if self.manifest_digest is None or digest != self.manifest_digest:
                raise ManifestError("manifest equivocation at an already-seen sequence")
            return
        self.sequence = manifest.sequence
        self.manifest_digest = digest


def save_checkpoint(path: str | os.PathLike[str], checkpoint: SnapshotCheckpoint) -> None:
    """Atomically persist a checkpoint for a single-writer deployment.

    The parent directory must be trusted and protected from untrusted writers.
    This function does not provide inter-process locking or protect against an
    attacker who can replace both the checkpoint and its parent directory.
    """
    target = Path(path)
    if checkpoint.sequence < -1:
        raise ManifestError("checkpoint sequence is invalid")
    if checkpoint.sequence == -1:
        if checkpoint.manifest_digest is not None:
            raise ManifestError("empty checkpoint must not contain a digest")
    elif not isinstance(checkpoint.manifest_digest, bytes) or len(checkpoint.manifest_digest) != 32:
        raise ManifestError("checkpoint digest must be a 32-byte SHA-256 digest")

    payload = {
        "schema_version": 1,
        "sequence": checkpoint.sequence,
        "manifest_digest": checkpoint.manifest_digest.hex() if checkpoint.manifest_digest else None,
    }
    encoded = (_canonical(payload) + b"\n")
    parent = target.parent
    if not parent.is_dir():
        raise ManifestError("checkpoint parent directory must already exist")

    fd = -1
    temp_name = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(parent))
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        temp_name = None
        # Persist the directory entry on POSIX where directory fsync is supported.
        if os.name == "posix":
            dir_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except OSError as exc:
        raise ManifestError("failed to persist checkpoint atomically") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def load_checkpoint(path: str | os.PathLike[str]) -> SnapshotCheckpoint:
    """Load a persisted checkpoint, rejecting malformed or unknown schemas."""
    target = Path(path)
    try:
        raw = target.read_bytes()
        if len(raw) > 4096:
            raise ManifestError("checkpoint file is unexpectedly large")
        payload = json.loads(raw.decode("ascii"))
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "sequence", "manifest_digest"}:
            raise ManifestError("checkpoint fields are invalid")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ManifestError("unsupported checkpoint schema")
        sequence = payload["sequence"]
        digest_hex = payload["manifest_digest"]
        if type(sequence) is not int or sequence < -1:
            raise ManifestError("checkpoint sequence is invalid")
        if sequence == -1:
            if digest_hex is not None:
                raise ManifestError("empty checkpoint must not contain a digest")
            digest = None
        else:
            if not isinstance(digest_hex, str) or len(digest_hex) != 64:
                raise ManifestError("checkpoint digest is invalid")
            try:
                digest = bytes.fromhex(digest_hex)
            except ValueError as exc:
                raise ManifestError("checkpoint digest is invalid") from exc
            if len(digest) != 32:
                raise ManifestError("checkpoint digest is invalid")
        return SnapshotCheckpoint(sequence=sequence, manifest_digest=digest)
    except ManifestError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ManifestError("failed to load checkpoint") from exc
