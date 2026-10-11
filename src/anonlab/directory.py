"""Signed relay descriptors and revocation snapshots for the AEGIS lab.

This module deliberately supports only literal IPv4 loopback endpoints. It is a
research directory primitive, not a public-network directory protocol. A
trusted authority public key must be pinned out-of-band; verification state
for descriptor and revocation rollback protection is process-local unless the
caller persists it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import tempfile
import threading
import time
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - unavailable on non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError as exc:  # pragma: no cover - optional research dependency
    raise RuntimeError(
        "The signed-directory experiment requires: "
        "python -m pip install 'rea-anon-lab[onion-lab]'"
    ) from exc

SCHEMA_VERSION = 1
IDENTITY_DIGEST_BYTES = 20
IDENTITY_PUBLIC_KEY_BYTES = 32
ONION_PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64
MAX_DESCRIPTOR_LIFETIME_SECONDS = 24 * 60 * 60
MAX_REVOCATION_LIFETIME_SECONDS = 6 * 60 * 60
MAX_STATE_BYTES = 4 * 1024 * 1024
STATE_SCHEMA_VERSION = 1
CLOCK_SKEW_SECONDS = 30
PROTOCOL = "malebolge-lab-ntor-v1"

_RELAY_DOMAIN = b"MALEBOLGE/relay-descriptor/v1\x00"
_AUTHORITY_DOMAIN = b"MALEBOLGE/authority-descriptor/v1\x00"
_REVOCATION_DOMAIN = b"MALEBOLGE/revocations/v1\x00"
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_32 = re.compile(r"^[0-9a-f]{64}$")
_HEX_64 = re.compile(r"^[0-9a-f]{128}$")
_DESCRIPTOR_KEYS = {
    "schema_version", "relay_id", "identity_public_key", "onion_public_key",
    "host", "port", "not_before", "expires_at", "sequence", "serial", "protocol",
}
_UNSIGNED_DESCRIPTOR_KEYS = _DESCRIPTOR_KEYS | {"relay_signature"}
_SIGNED_DESCRIPTOR_KEYS = _UNSIGNED_DESCRIPTOR_KEYS | {"authority_signature"}
_REVOCATION_BODY_KEYS = {"schema_version", "epoch", "issued_at", "expires_at", "revoked_relay_ids"}
_REVOCATION_KEYS = _REVOCATION_BODY_KEYS | {"authority_signature"}


def _canonical(value: Mapping[str, Any]) -> bytes:
    """Canonical JSON used only for this lab's signed data structures."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _now_seconds(now: int | None) -> int:
    value = int(time.time()) if now is None else now
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("time must be a non-negative integer Unix timestamp")
    return value


def _validate_private_state_parent(path: Path) -> None:
    """Reject symlinked ancestors and unsafe immediate state directories."""
    for ancestor in (path.parent, *path.parent.parents):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("directory state path ancestors must not be symbolic links")
    if os.name == "posix":
        parent_info = path.parent.stat()
        if parent_info.st_uid != os.geteuid() or parent_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError("directory state directory must be owned by the current user and not group/world-writable")


def _public_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def relay_identity_digest(identity_public_key: bytes) -> bytes:
    """Return the lab's 20-byte relay ID digest (identifier, not a signature)."""
    if not isinstance(identity_public_key, bytes) or len(identity_public_key) != IDENTITY_PUBLIC_KEY_BYTES:
        raise ValueError("relay identity public key must be exactly 32 bytes")
    return hashlib.sha256(b"MALEBOLGE/relay-identity/v1\x00" + identity_public_key).digest()[:IDENTITY_DIGEST_BYTES]


def _hex_field(value: Any, label: str, pattern: re.Pattern[str]) -> bytes:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} must be canonical lowercase hexadecimal")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:  # regex should already prevent this
        raise ValueError(f"{label} is invalid hexadecimal") from exc


def _validate_endpoint(host: Any, port: Any) -> None:
    if not isinstance(host, str) or not host:
        raise ValueError("relay host must be a literal IPv4 loopback address")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("relay host must be a literal IPv4 loopback address; DNS names are forbidden") from exc
    if ip.version != 4 or not ip.is_loopback:
        raise ValueError("directory lab accepts only IPv4 loopback endpoints")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("relay port must be an integer within 1..65535")


def _validate_times(not_before: Any, expires_at: Any, now: int, *, max_lifetime: int) -> None:
    for name, value in (("not_before", not_before), ("expires_at", expires_at)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer Unix timestamp")
    if expires_at <= not_before:
        raise ValueError("descriptor expiry must be after not_before")
    if expires_at - not_before > max_lifetime:
        raise ValueError("validity interval exceeds the configured maximum")
    if not_before > now + CLOCK_SKEW_SECONDS:
        raise ValueError("descriptor is not valid yet")
    if expires_at <= now:
        raise ValueError("descriptor has expired")


def _descriptor_body(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    if set(descriptor) not in (_DESCRIPTOR_KEYS, _UNSIGNED_DESCRIPTOR_KEYS, _SIGNED_DESCRIPTOR_KEYS):
        raise ValueError("descriptor has missing or unknown fields")
    body = {key: descriptor[key] for key in _DESCRIPTOR_KEYS}
    if (
        not isinstance(body["schema_version"], int)
        or isinstance(body["schema_version"], bool)
        or body["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("unsupported descriptor schema version")
    if body["protocol"] != PROTOCOL:
        raise ValueError("unsupported relay protocol")
    relay_id = body["relay_id"]
    if not isinstance(relay_id, str) or not _HEX_40.fullmatch(relay_id):
        raise ValueError("relay_id must be 40 lowercase hexadecimal characters")
    identity_public = _hex_field(body["identity_public_key"], "identity_public_key", _HEX_32)
    if not hmac.compare_digest(relay_identity_digest(identity_public).hex(), relay_id):
        raise ValueError("relay_id does not match identity_public_key")
    _hex_field(body["onion_public_key"], "onion_public_key", _HEX_32)
    _validate_endpoint(body["host"], body["port"])
    for name in ("not_before", "expires_at", "sequence"):
        value = body[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if body["sequence"] < 1:
        raise ValueError("descriptor sequence must be positive")
    serial = body["serial"]
    if not isinstance(serial, str) or not re.fullmatch(r"^[0-9a-f]{32}$", serial):
        raise ValueError("serial must be 32 lowercase hexadecimal characters")
    _validate_times(
        body["not_before"], body["expires_at"], int(body["not_before"]),
        max_lifetime=MAX_DESCRIPTOR_LIFETIME_SECONDS,
    )
    return body


def _descriptor_relay_signed_payload(descriptor: Mapping[str, Any]) -> bytes:
    body = _descriptor_body(descriptor)
    return _RELAY_DOMAIN + _canonical(body)


def _authority_descriptor_payload(descriptor: Mapping[str, Any]) -> bytes:
    if set(descriptor) != _UNSIGNED_DESCRIPTOR_KEYS:
        raise ValueError("authority certification expects a relay-signed descriptor without authority_signature")
    signed = {key: descriptor[key] for key in _UNSIGNED_DESCRIPTOR_KEYS}
    return _AUTHORITY_DOMAIN + _canonical(signed)


def _verify_signature(public_key: bytes, signature_hex: Any, payload: bytes, label: str) -> None:
    signature = _hex_field(signature_hex, f"{label} signature", _HEX_64)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError(f"{label} signature verification failed") from exc


def create_relay_descriptor(
    identity_private_key: Ed25519PrivateKey,
    onion_public_key: bytes,
    host: str,
    port: int,
    *,
    now: int | None = None,
    valid_for_seconds: int = 3600,
    sequence: int = 1,
    serial: str | None = None,
) -> dict[str, Any]:
    """Create a relay-signed descriptor; a trusted authority must certify it."""
    current = _now_seconds(now)
    if not isinstance(valid_for_seconds, int) or isinstance(valid_for_seconds, bool):
        raise ValueError("valid_for_seconds must be an integer")
    if not 1 <= valid_for_seconds <= MAX_DESCRIPTOR_LIFETIME_SECONDS:
        raise ValueError("valid_for_seconds must be within 1 second and 24 hours")
    _validate_endpoint(host, port)
    if not isinstance(onion_public_key, bytes) or len(onion_public_key) != ONION_PUBLIC_KEY_BYTES:
        raise ValueError("onion public key must be exactly 32 bytes")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise ValueError("descriptor sequence must be a positive integer")
    serial_value = secrets.token_hex(16) if serial is None else serial
    identity_public_key = _public_bytes(identity_private_key.public_key())
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "relay_id": relay_identity_digest(identity_public_key).hex(),
        "identity_public_key": identity_public_key.hex(),
        "onion_public_key": onion_public_key.hex(),
        "host": host,
        "port": port,
        "not_before": current,
        "expires_at": current + valid_for_seconds,
        "sequence": sequence,
        "serial": serial_value,
        "protocol": PROTOCOL,
    }
    validated = _descriptor_body(body)
    relay_signature = identity_private_key.sign(_RELAY_DOMAIN + _canonical(validated)).hex()
    return {**validated, "relay_signature": relay_signature}


@dataclass(slots=True)
class DirectoryAuthority:
    """Signer for the local directory lab.

    Without state_path this is a compatibility-only stateless signer and MUST
    NOT be used as an authoritative directory. With state_path, SQLite
    serializes writers across processes and durably reserves each relay sequence
    and serial before a descriptor is returned. Local storage cannot prevent
    rollback if an attacker restores an older database backup.
    """

    private_key: Ed25519PrivateKey
    state_path: str | os.PathLike[str] | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @classmethod
    def generate(cls, *, state_path: str | os.PathLike[str] | None = None) -> "DirectoryAuthority":
        return cls(Ed25519PrivateKey.generate(), state_path=state_path)

    @property
    def public_key_bytes(self) -> bytes:
        return _public_bytes(self.private_key.public_key())

    def _connect_state(self) -> sqlite3.Connection:
        if self.state_path is None:
            raise ValueError("durable authority state is not configured")
        path = Path(self.state_path)
        # Reject pre-existing symlink ancestors before mkdir/stat/open can follow
        # them. Repeat after creating missing parents to catch static replacement
        # during setup. This is defense in depth, not a race-free defense against
        # an attacker who can rename ancestors concurrently under the same UID.
        for ancestor in (path.parent, *path.parent.parents):
            try:
                ancestor_info = ancestor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(ancestor_info.st_mode):
                raise ValueError("authority state path ancestors must not be symbolic links")
        path.parent.mkdir(parents=True, exist_ok=True)
        for ancestor in (path.parent, *path.parent.parents):
            try:
                ancestor_info = ancestor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(ancestor_info.st_mode):
                raise ValueError("authority state path ancestors must not be symbolic links")
        if os.name == "posix":
            # A pathname check alone is vulnerable to a symlink/rename race.
            # Require a private, user-owned parent so another local user cannot
            # replace the database between validation and SQLite opening it.
            parent_info = path.parent.stat()
            if parent_info.st_uid != os.geteuid() or parent_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ValueError("authority state directory must be owned by the current user and not group/world-writable")
            flags = os.O_RDWR | os.O_CREAT
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                state_fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
            except OSError as exc:
                if path.is_symlink():
                    raise ValueError("authority state path must not be a symbolic link") from exc
                raise ValueError("authority state path could not be opened safely") from exc
            try:
                state_info = os.fstat(state_fd)
                if not stat.S_ISREG(state_info.st_mode):
                    raise ValueError("authority state path must be a regular file")
                if state_info.st_nlink != 1:
                    raise ValueError("authority state file must not have multiple hard links")
                os.fchmod(state_fd, stat.S_IRUSR | stat.S_IWUSR)
            finally:
                os.close(state_fd)
            # The private parent directory prevents an untrusted local user
            # from swapping this validated path before SQLite opens it.
        else:
            if path.is_symlink():
                raise ValueError("authority state path must not be a symbolic link")
        connection = sqlite3.connect(path, timeout=10.0, isolation_level=None)
        try:
            if os.name == "posix":
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA journal_mode = DELETE")
            # Serialize first-open schema and key binding too, not only issuance.
            # Otherwise two fresh processes can both observe missing metadata.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS authority_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS issued_descriptors (relay_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, descriptor_digest TEXT NOT NULL, serial TEXT NOT NULL UNIQUE)")
            connection.execute("CREATE TABLE IF NOT EXISTS issued_serials (serial TEXT PRIMARY KEY, relay_id TEXT NOT NULL, sequence INTEGER NOT NULL, descriptor_digest TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS issued_revocation_snapshots (epoch INTEGER PRIMARY KEY, revoked_ids_json TEXT NOT NULL, snapshot_json TEXT NOT NULL, digest TEXT NOT NULL)")
            fingerprint = hashlib.sha256(self.public_key_bytes).hexdigest()
            row = connection.execute("SELECT value FROM authority_meta WHERE key='authority_key_fingerprint'").fetchone()
            if row is None:
                # Never silently re-bind a populated database to a new key if
                # metadata was deleted or partially lost. That would let an
                # attacker with file access reset the authority's trust identity.
                existing_state = sum(
                    int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in (
                        "issued_descriptors",
                        "issued_serials",
                        "issued_revocation_snapshots",
                    )
                )
                if existing_state:
                    raise ValueError("authority state is missing its key fingerprint")
                connection.execute("INSERT INTO authority_meta(key, value) VALUES(?, ?)", ("authority_key_fingerprint", fingerprint))
            elif not hmac.compare_digest(str(row[0]), fingerprint):
                raise ValueError("authority state belongs to a different authority key")
            connection.execute("COMMIT")
            return connection
        except Exception:
            connection.close()
            raise

    def certify(self, relay_signed_descriptor: Mapping[str, Any], *, now: int | None = None) -> dict[str, Any]:
        if set(relay_signed_descriptor) != _UNSIGNED_DESCRIPTOR_KEYS:
            raise ValueError("expected a relay-signed descriptor without authority_signature")
        body = _descriptor_body(relay_signed_descriptor)
        current = _now_seconds(now)
        _validate_times(body["not_before"], body["expires_at"], current, max_lifetime=MAX_DESCRIPTOR_LIFETIME_SECONDS)
        identity_public = bytes.fromhex(body["identity_public_key"])
        _verify_signature(identity_public, relay_signed_descriptor["relay_signature"], _RELAY_DOMAIN + _canonical(body), "relay")
        to_sign = {**body, "relay_signature": relay_signed_descriptor["relay_signature"]}
        authority_signature = self.private_key.sign(_AUTHORITY_DOMAIN + _canonical(to_sign)).hex()
        certified = {**to_sign, "authority_signature": authority_signature}
        if self.state_path is None:
            return certified

        digest = hashlib.sha256(_AUTHORITY_DOMAIN + _canonical(to_sign) + bytes.fromhex(authority_signature)).hexdigest()
        # BEGIN IMMEDIATE serializes writers across processes. Commit reservation
        # before returning the certificate; any error rolls back the transaction.
        with self._lock:
            connection = self._connect_state()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT sequence, descriptor_digest, serial FROM issued_descriptors WHERE relay_id=?",
                    (body["relay_id"],),
                ).fetchone()
                if row is not None:
                    latest_sequence, latest_digest, latest_serial = int(row[0]), str(row[1]), str(row[2])
                    if body["sequence"] < latest_sequence:
                        raise ValueError("authority descriptor sequence rollback rejected")
                    if body["sequence"] == latest_sequence:
                        if not hmac.compare_digest(digest, latest_digest):
                            raise ValueError("authority conflicting descriptors share the same sequence")
                        if body["serial"] != latest_serial:
                            raise ValueError("authority same-sequence descriptor serial conflict")
                        connection.execute("COMMIT")
                        return certified
                prior_serial = connection.execute(
                    "SELECT relay_id, sequence, descriptor_digest FROM issued_serials WHERE serial=?",
                    (body["serial"],),
                ).fetchone()
                if prior_serial is not None:
                    raise ValueError("authority descriptor serial has already been used")
                connection.execute(
                    "INSERT INTO issued_serials(serial, relay_id, sequence, descriptor_digest) VALUES(?, ?, ?, ?)",
                    (body["serial"], body["relay_id"], body["sequence"], digest),
                )
                connection.execute(
                    "INSERT INTO issued_descriptors(relay_id, sequence, descriptor_digest, serial) VALUES(?, ?, ?, ?) "
                    "ON CONFLICT(relay_id) DO UPDATE SET sequence=excluded.sequence, descriptor_digest=excluded.descriptor_digest, serial=excluded.serial",
                    (body["relay_id"], body["sequence"], digest, body["serial"]),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ValueError("authority state rejected a duplicate issuance record") from exc
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return certified

    def sign_revocations(
        self,
        revoked_relay_ids: list[str] | tuple[str, ...] | set[str],
        *,
        epoch: int,
        now: int | None = None,
        valid_for_seconds: int = 3600,
    ) -> dict[str, Any]:
        current = _now_seconds(now)
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ValueError("revocation epoch must be a positive integer")
        if not isinstance(valid_for_seconds, int) or isinstance(valid_for_seconds, bool):
            raise ValueError("valid_for_seconds must be an integer")
        if not 1 <= valid_for_seconds <= MAX_REVOCATION_LIFETIME_SECONDS:
            raise ValueError("revocation snapshot validity must be between 1 second and 6 hours")
        if not isinstance(revoked_relay_ids, (list, tuple, set)):
            raise ValueError("revoked relay IDs must be a list, tuple, or set")
        values = list(revoked_relay_ids)
        if any(not isinstance(relay_id, str) or not _HEX_40.fullmatch(relay_id) for relay_id in values):
            raise ValueError("revoked relay IDs must be 40 lowercase hexadecimal characters")
        ids = sorted(set(values))

        # Stateless mode remains for compatibility-only local demos.
        if self.state_path is None:
            body = {
                "schema_version": SCHEMA_VERSION,
                "epoch": epoch,
                "issued_at": current,
                "expires_at": current + valid_for_seconds,
                "revoked_relay_ids": ids,
            }
            signature = self.private_key.sign(_REVOCATION_DOMAIN + _canonical(body)).hex()
            return {**body, "authority_signature": signature}

        # The durable authority keeps one immutable signed snapshot per epoch.
        # Re-publishing an epoch returns the original bytes; a changed list must
        # use a higher epoch and include every previously revoked relay.
        with self._lock:
            connection = self._connect_state()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT epoch, revoked_ids_json, snapshot_json, digest FROM issued_revocation_snapshots "
                    "ORDER BY epoch DESC LIMIT 1"
                ).fetchone()
                if row is not None:
                    latest_epoch = row[0]
                    if not isinstance(latest_epoch, int) or isinstance(latest_epoch, bool) or latest_epoch < 1:
                        raise ValueError("authority stored revocation epoch is invalid")
                    try:
                        latest_ids = json.loads(str(row[1]))
                        snapshot = json.loads(str(row[2]))
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise ValueError("authority stored revocation snapshot is malformed") from exc
                    if (
                        not isinstance(latest_ids, list)
                        or any(not isinstance(relay_id, str) or not _HEX_40.fullmatch(relay_id) for relay_id in latest_ids)
                        or latest_ids != sorted(set(latest_ids))
                    ):
                        raise ValueError("authority stored revocation IDs are invalid")
                    if not isinstance(snapshot, dict) or set(snapshot) != _REVOCATION_KEYS:
                        raise ValueError("authority stored revocation snapshot has invalid fields")
                    stored_body = {key: snapshot[key] for key in _REVOCATION_BODY_KEYS}
                    stored_signature = snapshot["authority_signature"]
                    if (
                        not isinstance(stored_body["schema_version"], int)
                        or isinstance(stored_body["schema_version"], bool)
                        or stored_body["schema_version"] != SCHEMA_VERSION
                        or not isinstance(stored_body["epoch"], int)
                        or isinstance(stored_body["epoch"], bool)
                        or stored_body["epoch"] != latest_epoch
                        or not isinstance(stored_body["issued_at"], int)
                        or isinstance(stored_body["issued_at"], bool)
                        or stored_body["issued_at"] < 0
                        or not isinstance(stored_body["expires_at"], int)
                        or isinstance(stored_body["expires_at"], bool)
                        or stored_body["expires_at"] <= stored_body["issued_at"]
                        or stored_body["expires_at"] - stored_body["issued_at"] > MAX_REVOCATION_LIFETIME_SECONDS
                        or stored_body["revoked_relay_ids"] != latest_ids
                    ):
                        raise ValueError("authority stored revocation snapshot is inconsistent")
                    try:
                        signature_bytes = _hex_field(stored_signature, "authority signature", _HEX_64)
                        computed_digest = hashlib.sha256(
                            _REVOCATION_DOMAIN + _canonical(stored_body) + signature_bytes
                        ).hexdigest()
                        Ed25519PublicKey.from_public_bytes(self.public_key_bytes).verify(
                            signature_bytes, _REVOCATION_DOMAIN + _canonical(stored_body)
                        )
                    except (ValueError, InvalidSignature) as exc:
                        raise ValueError("authority stored revocation snapshot signature is invalid") from exc
                    if (
                        not isinstance(row[3], str)
                        or not _HEX_32.fullmatch(row[3])
                        or not hmac.compare_digest(computed_digest, row[3])
                    ):
                        raise ValueError("authority stored revocation snapshot digest is invalid")
                    if epoch < latest_epoch:
                        raise ValueError("authority revocation epoch rollback rejected")
                    if epoch == latest_epoch:
                        if ids != latest_ids:
                            raise ValueError("authority conflicting revocation snapshots share the same epoch")
                        connection.execute("COMMIT")
                        return snapshot
                    if not set(latest_ids).issubset(set(ids)):
                        raise ValueError("authority revocations must be cumulative; relays cannot be un-revoked")

                body = {
                    "schema_version": SCHEMA_VERSION,
                    "epoch": epoch,
                    "issued_at": current,
                    "expires_at": current + valid_for_seconds,
                    "revoked_relay_ids": ids,
                }
                signature = self.private_key.sign(_REVOCATION_DOMAIN + _canonical(body)).hex()
                snapshot = {**body, "authority_signature": signature}
                encoded_ids = json.dumps(ids, sort_keys=True, separators=(",", ":"))
                encoded_snapshot = _canonical(snapshot).decode("ascii")
                digest = hashlib.sha256(_REVOCATION_DOMAIN + _canonical(body) + bytes.fromhex(signature)).hexdigest()
                connection.execute(
                    "INSERT INTO issued_revocation_snapshots(epoch, revoked_ids_json, snapshot_json, digest) "
                    "VALUES(?, ?, ?, ?)",
                    (epoch, encoded_ids, encoded_snapshot, digest),
                )
                connection.execute("COMMIT")
                return snapshot
            except sqlite3.IntegrityError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ValueError("authority state rejected a duplicate revocation epoch") from exc
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


@dataclass(frozen=True, slots=True)
class VerifiedRelayDescriptor:
    relay_id: str
    identity_digest: bytes
    identity_public_key: bytes
    onion_public_key: bytes
    host: str
    port: int
    sequence: int
    serial: str
    not_before: int
    expires_at: int
    protocol: str
    signed_descriptor_json: bytes

    def to_telescoping_descriptor(self) -> Any:
        """Convert verified metadata to the loopback-only circuit descriptor.

        Callers should obtain this object only from DirectoryVerifier after
        signature, validity, rollback, and revocation checks succeed.
        """
        from .telescoping import RelayDescriptor

        return RelayDescriptor(
            host=self.host,
            port=self.port,
            identity_digest=self.identity_digest,
            onion_public_key=self.onion_public_key,
            identity_public_key=self.identity_public_key,
            signed_descriptor_json=self.signed_descriptor_json,
        )


_ROUTE_VERIFICATION_TOKEN = object()


@dataclass(frozen=True, slots=True)
class VerifiedCircuitRoute:
    """Opaque-by-convention route returned only by a DirectoryVerifier.

    This is an application safety boundary, not a Python sandbox: callers must
    still treat the package as trusted code. The route expires when either a
    relay descriptor or the verified revocation snapshot expires.
    """

    _descriptors: tuple[Any, ...]
    authority_key_fingerprint: str
    revocation_epoch: int
    expires_at: int
    _relay_sequences: tuple[tuple[str, int], ...]
    _verifier: Any
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _ROUTE_VERIFICATION_TOKEN:
            raise ValueError("verified routes must be created by DirectoryVerifier")
        if not self._descriptors:
            raise ValueError("verified route cannot be empty")

    @property
    def descriptors(self) -> tuple[Any, ...]:
        return self._descriptors

    def assert_usable(self, *, now: int | None = None) -> None:
        if self._token is not _ROUTE_VERIFICATION_TOKEN:
            raise ValueError("route verification token is invalid")
        current = _now_seconds(now)
        if current >= self.expires_at:
            raise ValueError("verified route has expired; refresh directory and revocations")
        verifier = self._verifier
        if not isinstance(verifier, DirectoryVerifier):
            raise ValueError("verified route is detached from its directory verifier")
        verifier._assert_route_current(self, current)


class DirectoryVerifier:
    """Validate relay descriptors and revocations, with optional durable state.

    ``state_path`` enables crash-safe persistence of observed descriptor
    sequences and revocation epoch. The atomic local file protects against
    accidental rollback across ordinary process restarts, but cannot defeat an
    attacker who can restore an older copy of that file or modify the running
    process. Strong rollback resistance needs an OS monotonic store, transparency
    log, or independent quorum. ``require_persistent_state`` refuses operation
    without a configured state file.
    """

    def __init__(
        self,
        trusted_authority_public_key: bytes,
        *,
        state_path: str | os.PathLike[str] | None = None,
        require_persistent_state: bool = False,
    ) -> None:
        if not isinstance(trusted_authority_public_key, bytes) or len(trusted_authority_public_key) != 32:
            raise ValueError("trusted authority public key must be exactly 32 bytes")
        if require_persistent_state and state_path is None:
            raise ValueError("persistent directory state is required but state_path is not configured")
        self._authority_public_key = trusted_authority_public_key
        Ed25519PublicKey.from_public_bytes(trusted_authority_public_key)
        self._authority_fingerprint = hashlib.sha256(trusted_authority_public_key).hexdigest()
        self._state_path = Path(state_path) if state_path is not None else None
        self._require_persistent_state = require_persistent_state
        self._lock = threading.RLock()
        self._state_lock_depth = 0
        self._state_lock_fd: int | None = None
        self._revocation_epoch = 0
        self._revocation_digest: bytes | None = None
        self._revocation_expires_at: int | None = None
        self._revocation_snapshot: dict[str, Any] | None = None
        self._revoked_relay_ids: set[str] = set()
        self._latest_descriptor_sequence: dict[str, int] = {}
        self._descriptor_sequence_digest: dict[tuple[str, int], bytes] = {}
        if self._state_path is not None and os.path.lexists(self._state_path):
            # lexists() also detects dangling symlinks; following exists() would
            # silently treat one as absent and defer rejection until a write.
            self._load_state()

    @property
    def state_path(self) -> Path | None:
        return self._state_path

    @property
    def has_persistent_state(self) -> bool:
        return self._state_path is not None

    @property
    def revocation_epoch(self) -> int:
        return self._revocation_epoch

    @property
    def revocation_expires_at(self) -> int | None:
        return self._revocation_expires_at

    @property
    def revoked_relay_ids(self) -> frozenset[str]:
        return frozenset(self._revoked_relay_ids)

    def _state_object(
        self,
        *,
        revocation_epoch: int | None = None,
        revocation_digest: bytes | None | object = ...,
        revocation_expires_at: int | None | object = ...,
        revocation_snapshot: dict[str, Any] | None | object = ...,
        revoked_relay_ids: set[str] | None = None,
        latest_descriptor_sequence: dict[str, int] | None = None,
        descriptor_sequence_digest: dict[tuple[str, int], bytes] | None = None,
    ) -> dict[str, Any]:
        epoch = self._revocation_epoch if revocation_epoch is None else revocation_epoch
        digest = self._revocation_digest if revocation_digest is ... else revocation_digest
        expires = self._revocation_expires_at if revocation_expires_at is ... else revocation_expires_at
        snapshot = self._revocation_snapshot if revocation_snapshot is ... else revocation_snapshot
        revoked = self._revoked_relay_ids if revoked_relay_ids is None else revoked_relay_ids
        sequences = self._latest_descriptor_sequence if latest_descriptor_sequence is None else latest_descriptor_sequence
        digests = self._descriptor_sequence_digest if descriptor_sequence_digest is None else descriptor_sequence_digest
        latest_entries = []
        for relay_id, sequence in sorted(sequences.items()):
            item_digest = digests.get((relay_id, sequence))
            if item_digest is None:
                raise ValueError("directory state is missing the latest descriptor digest")
            latest_entries.append({"relay_id": relay_id, "sequence": sequence, "digest": item_digest.hex()})
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "authority_key_fingerprint": self._authority_fingerprint,
            "revocation_epoch": epoch,
            "revocation_digest": digest.hex() if isinstance(digest, bytes) else None,
            "revocation_expires_at": expires,
            "revocation_snapshot": snapshot,
            "revoked_relay_ids": sorted(revoked),
            "latest_descriptors": latest_entries,
        }

    @contextmanager
    def _state_operation(self) -> Iterator[None]:
        """Serialize durable state operations across threads and processes.

        A stable sidecar lock file is never replaced. After acquiring its
        advisory exclusive lock, reload the latest state before any decision or
        write. Platforms without fcntl locking fail closed for durable state.
        """
        with self._lock:
            path = self._state_path
            if path is None:
                yield
                return
            if fcntl is None:
                raise ValueError("durable directory state requires a supported cross-process file lock")
            if self._state_lock_depth:
                self._state_lock_depth += 1
                try:
                    yield
                finally:
                    self._state_lock_depth -= 1
                return

            path.parent.mkdir(parents=True, exist_ok=True)
            _validate_private_state_parent(path)
            lock_path = path.with_name(path.name + ".lock")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                lock_fd = os.open(lock_path, flags, stat.S_IRUSR | stat.S_IWUSR)
            except OSError as exc:
                raise ValueError("directory state lock file could not be opened safely") from exc
            locked = False
            try:
                lock_info = os.fstat(lock_fd)
                if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
                    raise ValueError("directory state lock must be a regular file without hard links")
                if os.name == "posix" and lock_info.st_uid != os.geteuid():
                    raise ValueError("directory state lock must be owned by the current user")
                if os.name == "posix":
                    os.fchmod(lock_fd, stat.S_IRUSR | stat.S_IWUSR)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                locked = True
                # Detect a lock pathname that was swapped while this process
                # waited for the inode it originally opened. This narrows the
                # split-lock window; it cannot defeat a same-UID attacker that
                # can rename the pathname again after this check.
                try:
                    current_lock_info = os.stat(lock_path, follow_symlinks=False)
                except OSError as exc:
                    raise ValueError("directory state lock path changed while acquiring lock") from exc
                if (current_lock_info.st_dev, current_lock_info.st_ino) != (lock_info.st_dev, lock_info.st_ino):
                    raise ValueError("directory state lock path changed while acquiring lock")
                self._state_lock_fd = lock_fd
                self._state_lock_depth = 1
                if os.path.lexists(path):
                    self._load_state()
                elif (
                    self._revocation_epoch
                    or self._latest_descriptor_sequence
                    or self._revocation_snapshot is not None
                ):
                    raise ValueError("persistent directory state disappeared while verifier was active")
                yield
            finally:
                self._state_lock_depth = 0
                self._state_lock_fd = None
                try:
                    if locked:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    def _persist_candidate(self, state: Mapping[str, Any]) -> None:
        path = self._state_path
        if path is None:
            if self._require_persistent_state:
                raise ValueError("persistent directory state is required")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _validate_private_state_parent(path)
        if path.is_symlink():
            raise ValueError("directory state path must not be a symbolic link")
        encoded = _canonical(state)
        if len(encoded) > MAX_STATE_BYTES:
            raise ValueError("directory state exceeds the configured size limit")
        fd = -1
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            if hasattr(os, "fchmod"):
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                fd = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            if os.name == "posix":
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _load_state(self) -> None:
        assert self._state_path is not None
        path = self._state_path
        _validate_private_state_parent(path)
        if path.is_symlink():
            raise ValueError("directory state must be a regular non-symlink file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise ValueError("directory state must be a regular non-symlink file") from exc
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("directory state must be a regular non-symlink file")
            if metadata.st_nlink != 1:
                raise ValueError("directory state file must not have multiple hard links")
            if os.name == "posix" and metadata.st_uid != os.geteuid():
                raise ValueError("directory state file must be owned by the current user")
            if metadata.st_size > MAX_STATE_BYTES:
                raise ValueError("directory state exceeds the configured size limit")
            if os.name == "posix" and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ValueError("directory state permissions are too broad; require mode 0600")
            with os.fdopen(fd, "rb", closefd=True) as stream:
                fd = -1
                raw = stream.read(MAX_STATE_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("directory state exceeds the configured size limit")
        def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("directory state contains duplicate fields")
                result[key] = value
            return result
        try:
            state = json.loads(raw.decode("ascii"), object_pairs_hook=strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("directory state is malformed") from exc
        keys = {"schema_version", "authority_key_fingerprint", "revocation_epoch", "revocation_digest", "revocation_expires_at", "revocation_snapshot", "revoked_relay_ids", "latest_descriptors"}
        if not isinstance(state, dict) or set(state) != keys:
            raise ValueError("directory state has missing or unknown fields")
        if (not isinstance(state["schema_version"], int)
                or isinstance(state["schema_version"], bool)
                or state["schema_version"] != STATE_SCHEMA_VERSION):
            raise ValueError("unsupported directory state schema version")
        fingerprint = state["authority_key_fingerprint"]
        if not isinstance(fingerprint, str) or not hmac.compare_digest(fingerprint, self._authority_fingerprint):
            raise ValueError("directory state belongs to a different authority key")
        epoch = state["revocation_epoch"]
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
            raise ValueError("directory state revocation epoch is invalid")
        digest_text = state["revocation_digest"]
        expires = state["revocation_expires_at"]
        snapshot = state["revocation_snapshot"]
        if epoch == 0:
            if digest_text is not None or expires is not None or snapshot is not None or state["revoked_relay_ids"]:
                raise ValueError("directory state has inconsistent empty revocation state")
            digest = None
        else:
            if not isinstance(digest_text, str) or not re.fullmatch(r"^[0-9a-f]{64}$", digest_text):
                raise ValueError("directory state revocation digest is invalid")
            if not isinstance(expires, int) or isinstance(expires, bool) or expires < 0:
                raise ValueError("directory state revocation expiry is invalid")
            if not isinstance(snapshot, dict) or set(snapshot) != _REVOCATION_KEYS:
                raise ValueError("directory state signed revocation snapshot is missing or malformed")
            body = {key: snapshot[key] for key in _REVOCATION_BODY_KEYS}
            if (not isinstance(body["schema_version"], int)
                    or isinstance(body["schema_version"], bool)
                    or body["schema_version"] != SCHEMA_VERSION):
                raise ValueError("directory state revocation schema is unsupported")
            if (not isinstance(body["epoch"], int) or isinstance(body["epoch"], bool)
                    or body["epoch"] != epoch):
                raise ValueError("directory state revocation epoch does not match signed snapshot")
            if (not isinstance(body["expires_at"], int) or isinstance(body["expires_at"], bool)
                    or body["expires_at"] != expires):
                raise ValueError("directory state revocation expiry does not match signed snapshot")
            issued_at, expires_at = body["issued_at"], body["expires_at"]
            if (not isinstance(issued_at, int) or isinstance(issued_at, bool) or issued_at < 0
                    or not isinstance(expires_at, int) or isinstance(expires_at, bool)
                    or expires_at <= issued_at
                    or expires_at - issued_at > MAX_REVOCATION_LIFETIME_SECONDS):
                raise ValueError("directory state signed revocation validity is invalid")
            snapshot_ids = body["revoked_relay_ids"]
            if not isinstance(snapshot_ids, list) or any(
                not isinstance(item, str) or not _HEX_40.fullmatch(item) for item in snapshot_ids
            ):
                raise ValueError("directory state signed revocation IDs are invalid")
            if snapshot_ids != sorted(set(snapshot_ids)):
                raise ValueError("directory state signed revocation IDs are invalid")
            signature = _hex_field(snapshot["authority_signature"], "authority signature", _HEX_64)
            try:
                Ed25519PublicKey.from_public_bytes(self._authority_public_key).verify(
                    signature, _REVOCATION_DOMAIN + _canonical(body)
                )
            except InvalidSignature as exc:
                raise ValueError("directory state signed revocation snapshot signature is invalid") from exc
            calculated_digest = hashlib.sha256(_REVOCATION_DOMAIN + _canonical(body) + signature).digest()
            if not hmac.compare_digest(calculated_digest.hex(), digest_text):
                raise ValueError("directory state revocation digest does not match signed snapshot")
            digest = bytes.fromhex(digest_text)
        revoked = state["revoked_relay_ids"]
        if not isinstance(revoked, list) or any(
            not isinstance(item, str) or not _HEX_40.fullmatch(item) for item in revoked
        ):
            raise ValueError("directory state revocations are invalid")
        if revoked != sorted(set(revoked)):
            raise ValueError("directory state revocations are invalid")
        if epoch > 0 and revoked != snapshot["revoked_relay_ids"]:
            raise ValueError("directory state revocations do not match signed snapshot")
        entries = state["latest_descriptors"]
        if not isinstance(entries, list):
            raise ValueError("directory state latest_descriptors must be a list")
        latest: dict[str, int] = {}
        latest_digests: dict[tuple[str, int], bytes] = {}
        previous_id = ""
        for item in entries:
            if not isinstance(item, dict) or set(item) != {"relay_id", "sequence", "digest"}:
                raise ValueError("directory state descriptor entry has invalid fields")
            relay_id, sequence, digest_value = item["relay_id"], item["sequence"], item["digest"]
            if not isinstance(relay_id, str) or not _HEX_40.fullmatch(relay_id) or relay_id <= previous_id:
                raise ValueError("directory state relay IDs must be unique and sorted")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
                raise ValueError("directory state descriptor sequence is invalid")
            if not isinstance(digest_value, str) or not re.fullmatch(r"^[0-9a-f]{64}$", digest_value):
                raise ValueError("directory state descriptor digest is invalid")
            latest[relay_id] = sequence
            latest_digests[(relay_id, sequence)] = bytes.fromhex(digest_value)
            previous_id = relay_id
        self._revocation_epoch = epoch
        self._revocation_digest = digest
        self._revocation_expires_at = expires
        self._revocation_snapshot = snapshot
        self._revoked_relay_ids = set(revoked)
        self._latest_descriptor_sequence = latest
        self._descriptor_sequence_digest = latest_digests

    def _ensure_fresh_revocations(self, now: int) -> None:
        if self._revocation_epoch < 1 or self._revocation_expires_at is None:
            raise ValueError("no verified revocation snapshot; fail closed before building a circuit")
        if now >= self._revocation_expires_at:
            raise ValueError("revocation snapshot expired; refresh directory and revocations")

    def apply_revocations(self, snapshot: Mapping[str, Any], *, now: int | None = None) -> None:
        with self._state_operation():
            if set(snapshot) != _REVOCATION_KEYS:
                raise ValueError("revocation snapshot has missing or unknown fields")
            body = {key: snapshot[key] for key in _REVOCATION_BODY_KEYS}
            if (
                not isinstance(body["schema_version"], int)
                or isinstance(body["schema_version"], bool)
                or body["schema_version"] != SCHEMA_VERSION
            ):
                raise ValueError("unsupported revocation schema version")
            epoch = body["epoch"]
            if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
                raise ValueError("revocation epoch must be a positive integer")
            current = _now_seconds(now)
            _validate_times(
                body["issued_at"], body["expires_at"], current,
                max_lifetime=MAX_REVOCATION_LIFETIME_SECONDS,
            )
            ids = body["revoked_relay_ids"]
            if not isinstance(ids, list):
                raise ValueError("revoked relay IDs must be a sorted list without duplicates")
            if any(not isinstance(relay_id, str) or not _HEX_40.fullmatch(relay_id) for relay_id in ids):
                raise ValueError("revoked relay IDs must be 40 lowercase hexadecimal characters")
            if ids != sorted(set(ids)):
                raise ValueError("revoked relay IDs must be a sorted list without duplicates")
            signature = _hex_field(snapshot["authority_signature"], "authority signature", _HEX_64)
            try:
                Ed25519PublicKey.from_public_bytes(self._authority_public_key).verify(
                    signature, _REVOCATION_DOMAIN + _canonical(body)
                )
            except InvalidSignature as exc:
                raise ValueError("revocation authority signature verification failed") from exc

            digest = hashlib.sha256(_REVOCATION_DOMAIN + _canonical(body) + signature).digest()
            if epoch < self._revocation_epoch:
                raise ValueError("revocation snapshot rollback detected")
            if epoch == self._revocation_epoch and self._revocation_digest is not None:
                if not hmac.compare_digest(digest, self._revocation_digest):
                    raise ValueError("conflicting revocation snapshots share the same epoch")
                return
            if not self._revoked_relay_ids.issubset(set(ids)):
                raise ValueError("revocation snapshots must be cumulative; relays cannot be un-revoked")
            candidate_revoked = set(ids)
            candidate_snapshot = dict(snapshot)
            candidate = self._state_object(
                revocation_epoch=epoch, revocation_digest=digest,
                revocation_expires_at=body["expires_at"],
                revocation_snapshot=candidate_snapshot, revoked_relay_ids=candidate_revoked,
            )
            self._persist_candidate(candidate)
            self._revocation_epoch = epoch
            self._revocation_digest = digest
            self._revocation_expires_at = body["expires_at"]
            self._revocation_snapshot = candidate_snapshot
            self._revoked_relay_ids = candidate_revoked

    def verify_circuit_descriptors(
        self,
        descriptors: list[Mapping[str, Any]],
        *,
        now: int | None = None,
        max_hops: int = 5,
    ) -> list[Any]:
        """Verify a full route and require a current signed revocation feed."""
        with self._state_operation():
            current = _now_seconds(now)
            self._ensure_fresh_revocations(current)
            if not isinstance(descriptors, list) or not descriptors:
                raise ValueError("a circuit must contain a non-empty descriptor list")
            if not isinstance(max_hops, int) or isinstance(max_hops, bool) or not 1 <= max_hops <= 5:
                raise ValueError("max_hops must be within 1..5 in the research lab")
            if len(descriptors) > max_hops:
                raise ValueError("circuit exceeds the configured maximum hop count")

            verified = [self.verify_descriptor(item, now=current) for item in descriptors]
            relay_ids = [item.relay_id for item in verified]
            endpoints = [(item.host, item.port) for item in verified]
            if len(set(relay_ids)) != len(relay_ids):
                raise ValueError("circuit contains duplicate relay identities")
            if len(set(endpoints)) != len(endpoints):
                raise ValueError("circuit contains duplicate relay endpoints")
            return [item.to_telescoping_descriptor() for item in verified]

    def verify_circuit_route(
        self,
        descriptors: list[Mapping[str, Any]],
        *,
        now: int | None = None,
        max_hops: int = 5,
    ) -> VerifiedCircuitRoute:
        """Return a short-lived route object for the high-level client API."""
        with self._state_operation():
            if self._state_path is None:
                raise ValueError("persistent directory state is required to issue a verified circuit route")
            current = _now_seconds(now)
            circuit_descriptors = self.verify_circuit_descriptors(descriptors, now=current, max_hops=max_hops)
            expiry = min([self._revocation_expires_at or 0] + [int(item["expires_at"]) for item in descriptors])
            if expiry <= current:
                raise ValueError("verified route has no remaining validity window")
            return VerifiedCircuitRoute(
                _descriptors=tuple(circuit_descriptors),
                authority_key_fingerprint=self._authority_fingerprint,
                revocation_epoch=self._revocation_epoch,
                expires_at=expiry,
                _relay_sequences=tuple((str(item["relay_id"]), int(item["sequence"])) for item in descriptors),
                _verifier=self,
                _token=_ROUTE_VERIFICATION_TOKEN,
            )

    def _assert_route_current(self, route: VerifiedCircuitRoute, now: int) -> None:
        with self._state_operation():
            self._ensure_fresh_revocations(now)
            if route.authority_key_fingerprint != self._authority_fingerprint:
                raise ValueError("verified route trust anchor no longer matches")
            if route.revocation_epoch != self._revocation_epoch:
                raise ValueError("verified route invalidated by a newer revocation snapshot; rebuild circuit")
            for relay_id, sequence in route._relay_sequences:
                if relay_id in self._revoked_relay_ids:
                    raise ValueError("verified route contains a revoked relay; rebuild circuit")
                if self._latest_descriptor_sequence.get(relay_id, 0) != sequence:
                    raise ValueError("verified route superseded by a newer relay descriptor; rebuild circuit")

    def verify_peer_descriptor(
        self, descriptor: Mapping[str, Any], *, now: int | None = None
    ) -> VerifiedRelayDescriptor:
        """Authorize a live relay peer using its authority-certified descriptor.

        Unlike the general descriptor parser, peer authorization always requires
        a current signed revocation snapshot. Descriptor signature, validity,
        sequence and revocation checks are then performed by ``verify_descriptor``.
        The caller should additionally compare the returned identity with the
        identity claimed in the authenticated transport transcript.
        """
        with self._state_operation():
            current = _now_seconds(now)
            self._ensure_fresh_revocations(current)
            return self.verify_descriptor(descriptor, now=current)

    def verify_descriptor(self, descriptor: Mapping[str, Any], *, now: int | None = None) -> VerifiedRelayDescriptor:
        with self._state_operation():
            if set(descriptor) != _SIGNED_DESCRIPTOR_KEYS:
                raise ValueError("descriptor must include exactly the relay and authority signatures")
            body = _descriptor_body(descriptor)
            current = _now_seconds(now)
            _validate_times(
                body["not_before"], body["expires_at"], current,
                max_lifetime=MAX_DESCRIPTOR_LIFETIME_SECONDS,
            )
            identity_public = bytes.fromhex(body["identity_public_key"])
            _verify_signature(identity_public, descriptor["relay_signature"],
                              _RELAY_DOMAIN + _canonical(body), "relay")
            authority_payload = {**body, "relay_signature": descriptor["relay_signature"]}
            _verify_signature(self._authority_public_key, descriptor["authority_signature"],
                              _AUTHORITY_DOMAIN + _canonical(authority_payload), "authority")

            relay_id = body["relay_id"]
            if relay_id in self._revoked_relay_ids:
                raise ValueError("relay identity is revoked")
            sequence = body["sequence"]
            digest = hashlib.sha256(_AUTHORITY_DOMAIN + _canonical(authority_payload)
                                    + bytes.fromhex(descriptor["authority_signature"])).digest()
            latest = self._latest_descriptor_sequence.get(relay_id, 0)
            if sequence < latest:
                raise ValueError("descriptor sequence rollback detected")
            prior_digest = self._descriptor_sequence_digest.get((relay_id, sequence))
            if prior_digest is not None and not hmac.compare_digest(prior_digest, digest):
                raise ValueError("conflicting descriptors share the same sequence")
            if sequence > latest:
                candidate_sequences = dict(self._latest_descriptor_sequence)
                candidate_sequences[relay_id] = sequence
                candidate_digests = {
                    key: value for key, value in self._descriptor_sequence_digest.items()
                    if key[0] != relay_id
                }
                candidate_digests[(relay_id, sequence)] = digest
                self._persist_candidate(self._state_object(
                    latest_descriptor_sequence=candidate_sequences,
                    descriptor_sequence_digest=candidate_digests,
                ))
                self._latest_descriptor_sequence = candidate_sequences
                self._descriptor_sequence_digest = candidate_digests

            return VerifiedRelayDescriptor(
                relay_id=relay_id,
                identity_digest=relay_identity_digest(identity_public),
                identity_public_key=identity_public,
                onion_public_key=bytes.fromhex(body["onion_public_key"]),
                host=body["host"],
                port=body["port"],
                sequence=sequence,
                serial=body["serial"],
                not_before=body["not_before"],
                expires_at=body["expires_at"],
                protocol=body["protocol"],
                signed_descriptor_json=_canonical(descriptor),
            )


def descriptor_to_json(descriptor: Mapping[str, Any]) -> str:
    """Serialize signed descriptor for storage/transmission in the lab."""
    return _canonical(descriptor).decode("ascii")


def descriptor_from_json(encoded: str) -> dict[str, Any]:
    """Parse strict JSON; signature verification remains the caller's job."""
    if not isinstance(encoded, str) or len(encoded) > 16_384:
        raise ValueError("descriptor JSON must be text no larger than 16 KiB")
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("descriptor JSON contains a duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(encoded, object_pairs_hook=strict_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("descriptor JSON is malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("descriptor JSON must contain an object")
    # Round-trip through canonical encoding to reject NaN and unsupported values.
    try:
        _canonical(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("descriptor JSON contains invalid JSON values") from exc
    return value