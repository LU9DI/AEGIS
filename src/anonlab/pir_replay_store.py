"""Durable nonce admission primitives for AEGIS PIR RPC.

This module is deliberately not wired into the RPC server yet. Deployments must
review the storage-path trust model and integrate it only with explicit config.
A local database cannot detect restoration of an older copy of itself.
"""
from __future__ import annotations

import base64
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Callable

MAX_CLOCK_SKEW_SECONDS = 60
_NONCE_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")
_SCHEMA_VERSION = "1"


class ReplayStoreError(RuntimeError):
    """Storage is unavailable or cannot safely establish replay state."""


class ReplayRejected(ReplayStoreError):
    """Request must be rejected because its timestamp or nonce is invalid/replayed."""


class DurablePirReplayStore:
    """SQLite-backed atomic nonce store; callers must commit admission before work.

    The parent directory must be provisioned and writable only by the service
    identity. Existing databases are never initialized implicitly. The database
    is local durable state, not a defense against privileged snapshot rollback.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        server_id: str,
        max_entries: int = 65_536,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("replay database path must be absolute")
        if not server_id or len(server_id) > 128:
            raise ValueError("server_id must be non-empty and at most 128 characters")
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.server_id = server_id
        self.max_entries = max_entries
        self._clock = clock
        self._untrusted = False

    def initialize(self) -> None:
        """Explicitly create a new database; refuses to overwrite any existing path."""
        parent = self.path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ReplayStoreError("replay database parent must be an existing non-symlink directory")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
            db = self._connect()
            try:
                db.execute("PRAGMA journal_mode=DELETE")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute(
                    "CREATE TABLE seen_nonces ("
                    "server_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at REAL NOT NULL, "
                    "PRIMARY KEY (server_id, nonce))"
                )
                db.execute("INSERT INTO metadata(key, value) VALUES('schema_version', ?)", (_SCHEMA_VERSION,))
                db.execute("INSERT INTO metadata(key, value) VALUES('wall_high_water', ?)", (repr(self._clock()),))
                db.execute("COMMIT")
            finally:
                db.close()
        except FileExistsError as exc:
            raise ReplayStoreError("replay database already exists; refusing implicit reset") from exc
        except (OSError, sqlite3.Error) as exc:
            self._untrusted = True
            raise ReplayStoreError("could not initialize replay database") from exc

    def _connect(self) -> sqlite3.Connection:
        try:
            if self.path.is_symlink():
                raise ReplayStoreError("replay database must not be a symlink")
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ReplayStoreError("replay database must be a regular file")
            if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
                raise ReplayStoreError("replay database permissions must be 0600")
            db = sqlite3.connect(str(self.path), timeout=2.0, isolation_level=None)
            db.execute("PRAGMA busy_timeout=2000")
            db.execute("PRAGMA synchronous=FULL")
            return db
        except ReplayStoreError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ReplayStoreError("replay database is unavailable") from exc

    def admit(self, nonce: str, issued_at: int) -> None:
        """Atomically validate timestamp and consume nonce, or raise fail-closed."""
        if self._untrusted:
            raise ReplayStoreError("replay store is untrusted; admission disabled")
        if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
            raise ReplayRejected("nonce format is invalid")
        try:
            decoded = base64.b64decode(nonce, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ReplayRejected("nonce format is invalid") from exc
        if len(decoded) != 32:
            raise ReplayRejected("nonce format is invalid")
        if isinstance(issued_at, bool) or not isinstance(issued_at, int):
            raise ReplayRejected("request timestamp is invalid")

        now = float(self._clock())
        if not math.isfinite(now):
            self._untrusted = True
            raise ReplayStoreError("wall clock is invalid; admission disabled")
        # Bound-check before converting issued_at to float; JSON can contain
        # arbitrarily large integers that overflow during float conversion.
        if issued_at < now - MAX_CLOCK_SKEW_SECONDS or issued_at > now + MAX_CLOCK_SKEW_SECONDS:
            raise ReplayRejected("request timestamp is outside accepted window")
        expires_at = max(now, float(issued_at)) + MAX_CLOCK_SKEW_SECONDS + 1.0

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            high_row = db.execute(
                "SELECT value FROM metadata WHERE key='wall_high_water'"
            ).fetchone()
            if version is None or version[0] != _SCHEMA_VERSION or high_row is None:
                raise ReplayStoreError("replay database schema/metadata is invalid")
            high_water = float(high_row[0])
            if not math.isfinite(high_water):
                self._untrusted = True
                raise ReplayStoreError("replay database clock metadata is invalid")
            if now < high_water - 1.0:
                self._untrusted = True
                raise ReplayStoreError("wall clock moved backwards; replay admission disabled")
            db.execute(
                "UPDATE metadata SET value=? WHERE key='wall_high_water'",
                (repr(max(now, high_water)),),
            )
            db.execute("DELETE FROM seen_nonces WHERE expires_at < ?", (now,))
            duplicate = db.execute(
                "SELECT 1 FROM seen_nonces WHERE server_id=? AND nonce=?",
                (self.server_id, nonce),
            ).fetchone()
            if duplicate is not None:
                raise ReplayRejected("request replay detected")
            count = db.execute(
                "SELECT COUNT(*) FROM seen_nonces WHERE server_id=?", (self.server_id,)
            ).fetchone()[0]
            if count >= self.max_entries:
                raise ReplayStoreError("replay store is full; admission disabled")
            db.execute(
                "INSERT INTO seen_nonces(server_id, nonce, expires_at) VALUES(?, ?, ?)",
                (self.server_id, nonce, expires_at),
            )
            db.execute("COMMIT")
        except ReplayRejected:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        except ReplayStoreError:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        except (sqlite3.Error, OSError, ValueError) as exc:
            if db.in_transaction:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            self._untrusted = True
            raise ReplayStoreError("replay admission failed; admission disabled") from exc
        finally:
            db.close()
