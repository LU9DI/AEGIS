"""Opt-in SQLite-backed nonce admission for AEGIS PIR RPC.

The RPC server can use this store when explicitly configured and provisioned.
Filesystem path checks have race/platform limitations, and a local database
cannot detect restoration of an older copy of itself.
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

    def _validate_parent_directory(self) -> None:
        parent = self.path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ReplayStoreError("replay database parent must be an existing non-symlink directory")
        if os.name == "posix":
            info = parent.stat()
            if info.st_uid != os.geteuid():
                raise ReplayStoreError("replay database parent must be owned by the service identity")
            if stat.S_IMODE(info.st_mode) & 0o022:
                raise ReplayStoreError("replay database parent must not be group/world-writable")

    def initialize(self) -> None:
        """Explicitly create a new database; refuses to overwrite any existing path."""
        if self._untrusted:
            raise ReplayStoreError("replay store is untrusted; initialization disabled")
        try:
            self._validate_parent_directory()
        except ReplayStoreError:
            # Initialization and admission must agree: a path/permission
            # violation latches this instance instead of permitting a retry
            # after the filesystem is changed underneath it.
            self._untrusted = True
            raise
        except OSError as exc:
            self._untrusted = True
            raise ReplayStoreError(
                "replay database parent validation failed; initialization disabled"
            ) from exc
        # Validate the clock before creating a file: an invalid initial value
        # must not leave an unusable database that cannot be safely reset.
        try:
            initial_wall_time = float(self._clock())
        except Exception as exc:
            # The clock is an injected dependency. Any ordinary exception from
            # it must leave this instance latched, not a reusable partial store.
            self._untrusted = True
            raise ReplayStoreError("wall clock is invalid; replay store was not initialized") from exc
        if not math.isfinite(initial_wall_time):
            self._untrusted = True
            raise ReplayStoreError("wall clock is invalid; replay store was not initialized")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                # Set permissions on the file descriptor itself. chmod(path)
                # after closing fd would reopen a path-replacement window.
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
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
                db.execute("INSERT INTO metadata(key, value) VALUES('wall_high_water', ?)", (repr(initial_wall_time),))
                db.execute("COMMIT")
            finally:
                db.close()
        except FileExistsError as exc:
            # Seeing an existing database during explicit initialization is an
            # operator-recovery boundary. Do not let this object become usable
            # merely because the path is later removed or replaced.
            self._untrusted = True
            raise ReplayStoreError("replay database already exists; refusing implicit reset") from exc
        except (OSError, sqlite3.Error) as exc:
            self._untrusted = True
            raise ReplayStoreError("could not initialize replay database") from exc

    def _connect(self) -> sqlite3.Connection:
        db: sqlite3.Connection | None = None
        try:
            self._validate_parent_directory()
            if self.path.is_symlink():
                raise ReplayStoreError("replay database must not be a symlink")
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ReplayStoreError("replay database must be a regular file")
            if os.name == "posix" and info.st_uid != os.geteuid():
                raise ReplayStoreError("replay database must be owned by the service identity")
            if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o600:
                raise ReplayStoreError("replay database permissions must be 0600")
            db = sqlite3.connect(str(self.path), timeout=2.0, isolation_level=None)
            db.execute("PRAGMA busy_timeout=2000")
            db.execute("PRAGMA synchronous=FULL")
            return db
        except ReplayStoreError:
            # A path or permission violation invalidates trust in this store
            # instance; do not allow a later retry to silently resume service.
            if db is not None:
                try:
                    db.close()
                except sqlite3.Error:
                    pass
            self._untrusted = True
            raise
        except (OSError, sqlite3.Error) as exc:
            if db is not None:
                try:
                    db.close()
                except sqlite3.Error:
                    pass
            self._untrusted = True
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
        if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != nonce:
            # Require canonical Base64. Non-canonical encodings can decode to
            # identical bytes but differ as SQLite text keys, bypassing replay
            # uniqueness if the protocol accepts both representations.
            raise ReplayRejected("nonce format is invalid")
        if isinstance(issued_at, bool) or not isinstance(issued_at, int):
            raise ReplayRejected("request timestamp is invalid")

        db = self._connect()
        try:
            # Acquire SQLite's write lock before sampling wall time. Otherwise,
            # lock contention can make a request's freshness check stale while
            # it waits to enter the serialized admission transaction.
            db.execute("BEGIN IMMEDIATE")
            try:
                now = float(self._clock())
            except Exception as exc:
                # A failing clock dependency is an admission failure regardless
                # of exception type; the surrounding handler rolls back and the
                # store remains disabled for this process instance.
                self._untrusted = True
                raise ReplayStoreError("wall clock is invalid; admission disabled") from exc
            if not math.isfinite(now):
                self._untrusted = True
                raise ReplayStoreError("wall clock is invalid; admission disabled")
            version = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            high_row = db.execute(
                "SELECT value FROM metadata WHERE key='wall_high_water'"
            ).fetchone()
            if version is None or version[0] != _SCHEMA_VERSION or high_row is None:
                self._untrusted = True
                raise ReplayStoreError("replay database schema/metadata is invalid")
            try:
                high_water = float(high_row[0])
            except (OverflowError, TypeError, ValueError) as exc:
                self._untrusted = True
                raise ReplayStoreError("replay database clock metadata is invalid") from exc
            if not math.isfinite(high_water):
                self._untrusted = True
                raise ReplayStoreError("replay database clock metadata is invalid")
            if now < high_water - 1.0:
                self._untrusted = True
                raise ReplayStoreError("wall clock moved backwards; replay admission disabled")
            # Bound-check before converting issued_at to float; JSON can contain
            # arbitrarily large integers that overflow during float conversion.
            if issued_at < now - MAX_CLOCK_SKEW_SECONDS or issued_at > now + MAX_CLOCK_SKEW_SECONDS:
                raise ReplayRejected("request timestamp is outside accepted window")
            expires_at = max(now, float(issued_at)) + MAX_CLOCK_SKEW_SECONDS + 1.0
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
                try:
                    db.execute("ROLLBACK")
                except Exception as exc:
                    self._untrusted = True
                    raise ReplayStoreError(
                        "replay admission rollback failed; admission disabled"
                    ) from exc
            raise
        except ReplayStoreError:
            if db.in_transaction:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error as exc:
                    self._untrusted = True
                    raise ReplayStoreError(
                        "replay admission rollback failed; admission disabled"
                    ) from exc
            raise
        except Exception as exc:
            if db.in_transaction:
                try:
                    db.execute("ROLLBACK")
                except Exception:
                    self._untrusted = True
            self._untrusted = True
            raise ReplayStoreError("replay admission failed; admission disabled") from exc
        finally:
            try:
                db.close()
            except Exception as exc:
                # A close failure after COMMIT makes the outcome uncertain to
                # the caller. Latch the store so it cannot silently resume.
                self._untrusted = True
                raise ReplayStoreError(
                    "replay database connection cleanup failed; admission disabled"
                ) from exc
