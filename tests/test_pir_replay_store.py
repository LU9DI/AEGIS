from __future__ import annotations

import base64
import multiprocessing
import os
import secrets
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anonlab.pir_replay_store import DurablePirReplayStore, ReplayRejected, ReplayStoreError


def _admit_in_process(path: str, nonce: str, issued_at: int, queue, start_barrier) -> None:
    # Hold both independent processes at the same point so this test exercises
    # overlapping admission attempts rather than merely sequential replays.
    start_barrier.wait(timeout=15)
    store = DurablePirReplayStore(path, server_id="multiprocess-replica", max_entries=16)
    try:
        store.admit(nonce, issued_at)
        queue.put(True)
    except (ReplayRejected, ReplayStoreError):
        queue.put(False)


def _crash_with_uncommitted_nonce(path: str, server_id: str, nonce: str, expires_at: float) -> None:
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        "INSERT INTO seen_nonces(server_id, nonce, expires_at) VALUES(?, ?, ?)",
        (server_id, nonce, expires_at),
    )
    # Simulate abrupt process death after the row write but before COMMIT.
    os._exit(0)


class DurablePirReplayStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "replay.sqlite3"
        self.now = [1_800_000_000.0]
        self.store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        self.store.initialize()

    @staticmethod
    def nonce():
        return base64.b64encode(secrets.token_bytes(32)).decode("ascii")

    def test_noncanonical_base64_nonce_is_rejected(self):
        nonce = self.nonce()
        self.store.admit(nonce, int(self.now[0]))
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        index = alphabet.index(nonce[-2])
        # For a 32-byte value, the final Base64 symbol has two unused low
        # bits. Set one padding bit to create a non-canonical alias that still
        # decodes to the same 32 bytes.
        alternate_index = index | 1
        alternate = nonce[:-2] + alphabet[alternate_index] + "="
        self.assertNotEqual(nonce, alternate)
        self.assertEqual(base64.b64decode(nonce), base64.b64decode(alternate))
        with self.assertRaisesRegex(ReplayRejected, "nonce format"):
            self.store.admit(alternate, int(self.now[0]))

    def test_high_water_persists_when_timestamp_is_rejected(self):
        advanced = self.now[0] + 300
        self.now[0] = advanced
        with self.assertRaisesRegex(ReplayRejected, "outside accepted window"):
            self.store.admit(self.nonce(), int(advanced - 120))

        with sqlite3.connect(self.path) as db:
            persisted = float(db.execute(
                "SELECT value FROM metadata WHERE key='wall_high_water'"
            ).fetchone()[0])
        self.assertGreaterEqual(persisted, advanced)

        reopened = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        self.now[0] = advanced - 10
        with self.assertRaisesRegex(ReplayStoreError, "moved backwards"):
            reopened.admit(self.nonce(), int(self.now[0]))

    def test_rejected_admission_persists_clock_sample_taken_inside_admission_transaction(self):
        base = self.now[0]
        samples = iter((base + 10, base + 200, base + 200))
        self.store._clock = lambda: next(samples)

        # The first sample is committed by the preliminary transaction. The
        # second sample occurs after the admission lock is acquired and causes
        # this timestamp to be rejected. That newer observation must survive
        # the admission rollback via the rejection-path persistence step.
        with self.assertRaisesRegex(ReplayRejected, "outside accepted window"):
            self.store.admit(self.nonce(), int(base + 10))

        with sqlite3.connect(self.path) as db:
            persisted = float(db.execute(
                "SELECT value FROM metadata WHERE key='wall_high_water'"
            ).fetchone()[0])
        self.assertGreaterEqual(persisted, base + 200)

    def test_high_water_persists_when_duplicate_nonce_is_rejected(self):
        nonce = self.nonce()
        self.store.admit(nonce, int(self.now[0]))
        self.now[0] += 120
        # The nonce has expired by this time, so use a fresh request timestamp
        # but move the clock only a fraction to preserve the original nonce.
        self.now[0] -= 119
        with self.assertRaisesRegex(ReplayRejected, "replay"):
            self.store.admit(nonce, int(self.now[0]))

        with sqlite3.connect(self.path) as db:
            persisted = float(db.execute(
                "SELECT value FROM metadata WHERE key='wall_high_water'"
            ).fetchone()[0])
        self.assertGreaterEqual(persisted, self.now[0])

    def test_replay_is_rejected_after_store_reopen(self):
        nonce = self.nonce()
        self.store.admit(nonce, int(self.now[0]))
        reopened = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with self.assertRaisesRegex(ReplayRejected, "replay"):
            reopened.admit(nonce, int(self.now[0]))

    def test_two_store_instances_admit_same_nonce_exactly_once(self):
        nonce = self.nonce()
        stores = [
            DurablePirReplayStore(self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0])
            for _ in range(8)
        ]

        def attempt(store):
            try:
                store.admit(nonce, int(self.now[0]))
                return True
            except (ReplayRejected, ReplayStoreError):
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, stores))
        self.assertEqual(sum(outcomes), 1)

    def test_clock_is_sampled_after_write_transaction_lock(self):
        def clock_while_locked():
            probe = sqlite3.connect(self.path, timeout=0)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    probe.execute("BEGIN IMMEDIATE")
            finally:
                probe.close()
            return self.now[0]

        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=clock_while_locked
        )
        store.admit(self.nonce(), int(self.now[0]))

    def test_uncommitted_nonce_is_rolled_back_after_process_crash(self):
        nonce = self.nonce()
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_crash_with_uncommitted_nonce,
            args=(str(self.path), "replica-a", nonce, self.now[0] + 121),
        )
        process.start()
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        self.assertFalse(process.is_alive(), "crash simulation process timed out")
        self.assertEqual(process.exitcode, 0)
        # SQLite recovery must discard the uncommitted write; admission can
        # then consume the nonce normally without accepting a phantom success.
        self.store.admit(nonce, int(self.now[0]))

    def test_two_processes_admit_same_nonce_exactly_once(self):
        path = Path(self.tmp.name) / "multiprocess.sqlite3"
        store = DurablePirReplayStore(path, server_id="multiprocess-replica", max_entries=16)
        store.initialize()
        nonce = self.nonce()
        issued = int(time.time())
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        start_barrier = context.Barrier(2)
        processes = [
            context.Process(
                target=_admit_in_process,
                args=(str(path), nonce, issued, queue, start_barrier),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
        try:
            self.assertTrue(all(not process.is_alive() for process in processes), "worker process timed out")
            self.assertEqual([process.exitcode for process in processes], [0, 0])
            outcomes = [queue.get(timeout=2) for _ in processes]
            self.assertEqual(sum(outcomes), 1)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
            queue.close()

    def test_live_capacity_fails_closed_without_eviction(self):
        small = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=1, clock=lambda: self.now[0]
        )
        first = self.nonce()
        small.admit(first, int(self.now[0]))
        with self.assertRaisesRegex(ReplayStoreError, "full"):
            small.admit(self.nonce(), int(self.now[0]))
        with self.assertRaisesRegex(ReplayRejected, "replay"):
            small.admit(first, int(self.now[0]))

    def test_durable_nonce_is_retained_after_validity_window_without_trusted_time(self):
        nonce = self.nonce()
        issued = int(self.now[0])
        self.store.admit(nonce, issued)
        self.now[0] += 122
        # Durable mode must not delete replay history based on an unchecked
        # wall clock. The old nonce remains rejected even after freshness ends.
        with self.assertRaisesRegex(ReplayRejected, "replay"):
            self.store.admit(nonce, int(self.now[0]))

    def test_timestamp_freshness_window_boundaries(self):
        now = int(self.now[0])
        self.store.admit(self.nonce(), now - 60)
        self.store.admit(self.nonce(), now + 60)
        with self.assertRaisesRegex(ReplayRejected, "timestamp"):
            self.store.admit(self.nonce(), now - 61)
        with self.assertRaisesRegex(ReplayRejected, "timestamp"):
            self.store.admit(self.nonce(), now + 61)

    def test_future_edge_nonce_is_retained_without_wall_clock_expiry(self):
        nonce = self.nonce()
        now = int(self.now[0])
        self.store.admit(nonce, now + 60)
        self.now[0] += 120
        # The timestamp is still at the accepted boundary, but replay history
        # is retained independently of the wall-clock cleanup horizon.
        with self.assertRaisesRegex(ReplayRejected, "replay"):
            self.store.admit(nonce, int(self.now[0]))
        self.now[0] += 2
        self.store.admit(self.nonce(), int(self.now[0]))
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT nonce FROM seen_nonces WHERE server_id=?", ("replica-a",)
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIn(nonce, [row[0] for row in rows])

    def test_extreme_timestamp_integer_is_rejected_without_overflow(self):
        with self.assertRaisesRegex(ReplayRejected, "timestamp"):
            self.store.admit(self.nonce(), 10**10_000)

    def test_unexpected_clock_exception_latches_admission_store(self):
        def broken_clock():
            raise RuntimeError("clock provider crashed")

        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=broken_clock
        )
        with self.assertRaisesRegex(ReplayStoreError, "wall clock is invalid"):
            store.admit(self.nonce(), int(self.now[0]))
        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_unexpected_clock_exception_latches_initialization(self):
        path = Path(self.tmp.name) / "broken-clock.sqlite3"

        def broken_clock():
            raise RuntimeError("clock provider crashed")

        store = DurablePirReplayStore(path, server_id="replica-clock", clock=broken_clock)
        with self.assertRaisesRegex(ReplayStoreError, "wall clock is invalid"):
            store.initialize()
        self.assertTrue(store._untrusted)
        self.assertFalse(path.exists())
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.initialize()

    def test_full_store_persists_clock_observed_in_rolled_back_admission(self):
        # Fill the store, then advance the clock separately for the preliminary
        # observation, admission transaction, and post-rollback persistence.
        self.store.max_entries = 1
        self.store.admit(self.nonce(), int(self.now[0]))
        observed = [self.now[0] + 1, self.now[0] + 2, self.now[0] + 3]
        self.store._clock = lambda: observed.pop(0)

        with self.assertRaisesRegex(ReplayStoreError, "store is full"):
            self.store.admit(self.nonce(), int(self.now[0] + 2))

        with sqlite3.connect(self.path) as db:
            high_water = float(db.execute(
                "SELECT value FROM metadata WHERE key='wall_high_water'"
            ).fetchone()[0])
        self.assertEqual(high_water, self.now[0] + 3)

    def test_backward_clock_step_fails_closed(self):
        self.store.admit(self.nonce(), int(self.now[0]))
        self.now[0] -= 5
        with self.assertRaisesRegex(ReplayStoreError, "backwards"):
            self.store.admit(self.nonce(), int(self.now[0]))
        self.now[0] += 10
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            self.store.admit(self.nonce(), int(self.now[0]))

    def test_initialization_refuses_to_reset_existing_database_and_latches(self):
        with self.assertRaisesRegex(ReplayStoreError, "already exists"):
            self.store.initialize()
        self.assertTrue(self.store._untrusted)

        # Removing/replacing the path after this failed initialization attempt
        # must not make the same object eligible to admit requests.
        self.path.unlink()
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            self.store.admit(self.nonce(), int(self.now[0]))

    def test_initialization_sets_permissions_on_open_file_descriptor(self):
        path = Path(self.tmp.name) / "fchmod.sqlite3"
        store = DurablePirReplayStore(
            path, server_id="replica-fchmod", clock=lambda: self.now[0]
        )
        with patch("anonlab.pir_replay_store.os.chmod", side_effect=AssertionError("path chmod must not be used")):
            store.initialize()
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_initial_clock_does_not_create_database(self):
        path = Path(self.tmp.name) / "invalid-clock.sqlite3"
        store = DurablePirReplayStore(
            path, server_id="replica-clock", clock=lambda: float("nan")
        )
        with self.assertRaisesRegex(ReplayStoreError, "clock is invalid"):
            store.initialize()
        self.assertFalse(path.exists())

    def test_invalid_initialization_clock_latches_and_blocks_retry(self):
        path = Path(self.tmp.name) / "retry-clock.sqlite3"
        clock_value = [float("nan")]
        store = DurablePirReplayStore(
            path, server_id="replica-clock-retry", clock=lambda: clock_value[0]
        )
        with self.assertRaisesRegex(ReplayStoreError, "clock is invalid"):
            store.initialize()
        self.assertTrue(store._untrusted)
        self.assertFalse(path.exists())

        clock_value[0] = self.now[0]
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.initialize()
        self.assertFalse(path.exists())

    def test_initialize_parent_oserror_latches_instance(self):
        path = Path(self.tmp.name) / "init-oserror.sqlite3"
        store = DurablePirReplayStore(
            path, server_id="replica-init-oserror", clock=lambda: self.now[0]
        )
        with patch.object(store, "_validate_parent_directory", side_effect=PermissionError("simulated")):
            with self.assertRaisesRegex(ReplayStoreError, "parent validation failed"):
                store.initialize()
        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.initialize()
        self.assertFalse(path.exists())

    def test_initialize_parent_permission_failure_latches_instance(self):
        if os.name != "posix":
            self.skipTest("POSIX directory permissions are required")
        parent = Path(self.tmp.name)
        original_mode = parent.stat().st_mode & 0o777
        path = parent / "init-permission.sqlite3"
        store = DurablePirReplayStore(
            path, server_id="replica-init-permission", clock=lambda: self.now[0]
        )
        try:
            parent.chmod(0o777)
            with self.assertRaisesRegex(ReplayStoreError, "group/world-writable"):
                store.initialize()
            self.assertTrue(store._untrusted)
            parent.chmod(original_mode)
            with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
                store.initialize()
            self.assertFalse(path.exists())
        finally:
            parent.chmod(original_mode)

    def test_group_or_world_writable_parent_is_rejected_and_latched(self):
        import os

        if os.name != "posix":
            self.skipTest("POSIX directory permissions are required")
        parent = Path(self.tmp.name)
        original_mode = parent.stat().st_mode & 0o777
        try:
            parent.chmod(0o777)
            store = DurablePirReplayStore(
                self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
            )
            with self.assertRaisesRegex(ReplayStoreError, "group/world-writable"):
                store.admit(self.nonce(), int(self.now[0]))
            with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
                store.admit(self.nonce(), int(self.now[0]))
        finally:
            parent.chmod(original_mode)

    def test_symlink_database_is_rejected(self):
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlinks unsupported")
        link = Path(self.tmp.name) / "replay-link.sqlite3"
        link.symlink_to(self.path)
        store = DurablePirReplayStore(
            link, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with self.assertRaisesRegex(ReplayStoreError, "symlink"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_database_owned_by_another_identity_is_rejected(self):
        if os.name != "posix":
            self.skipTest("POSIX ownership is required")
        from types import SimpleNamespace

        actual = self.path.lstat()
        fake_info = SimpleNamespace(st_mode=actual.st_mode, st_uid=os.geteuid() + 1)
        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with patch.object(Path, "lstat", return_value=fake_info):
            with self.assertRaisesRegex(ReplayStoreError, "owned by the service identity"):
                store._connect()
        self.assertTrue(store._untrusted)

    def test_rollback_failure_latches_store_untrusted(self):
        current_time = self.now[0]

        class RollbackFailConnection:
            def __init__(self):
                self.in_transaction = False
                self.row = None

            def execute(self, sql, _params=()):
                if sql == "BEGIN IMMEDIATE":
                    self.in_transaction = True
                elif "key='schema_version'" in sql:
                    self.row = ("1",)
                elif "key='wall_high_water'" in sql:
                    self.row = (repr(current_time),)
                elif "SELECT 1 FROM seen_nonces" in sql:
                    self.row = (1,)
                elif sql == "ROLLBACK":
                    raise sqlite3.OperationalError("simulated rollback failure")
                return self

            def fetchone(self):
                return self.row

            def close(self):
                pass

        connection = RollbackFailConnection()
        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with patch.object(store, "_persist_wall_high_water", return_value=self.now[0]), patch.object(store, "_connect", return_value=connection):
            with self.assertRaisesRegex(ReplayStoreError, "rollback failed"):
                store.admit(self.nonce(), int(self.now[0]))

        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_commit_failure_rolls_back_and_latches_store_untrusted(self):
        real_connect = sqlite3.connect

        class CommitFailConnection:
            def __init__(self, connection):
                self.connection = connection
                self.closed = False
                self.transaction_was_open_at_close = None

            @property
            def in_transaction(self):
                if self.closed:
                    return False
                return self.connection.in_transaction

            def execute(self, sql, *args, **kwargs):
                if sql == "COMMIT":
                    raise sqlite3.OperationalError("simulated commit failure")
                return self.connection.execute(sql, *args, **kwargs)

            def close(self):
                self.connection.close()

        nonce = self.nonce()
        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        connection = CommitFailConnection(real_connect(self.path, timeout=2.0, isolation_level=None))
        with patch.object(store, "_persist_wall_high_water", return_value=self.now[0]), patch.object(store, "_connect", return_value=connection):
            with self.assertRaisesRegex(ReplayStoreError, "admission failed"):
                store.admit(nonce, int(self.now[0]))

        self.assertTrue(store._untrusted)
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT nonce FROM seen_nonces WHERE server_id=?", ("replica-a",)
            ).fetchall()
        self.assertNotIn(nonce, [row[0] for row in rows])
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_connection_close_failure_latches_store_untrusted(self):
        real_connect = sqlite3.connect

        class CloseFailConnection:
            def __init__(self, connection):
                self.connection = connection

            @property
            def in_transaction(self):
                return self.connection.in_transaction

            def execute(self, *args, **kwargs):
                return self.connection.execute(*args, **kwargs)

            def close(self):
                self.connection.close()
                raise sqlite3.OperationalError("simulated close failure")

        nonce = self.nonce()
        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )

        connections = 0

        def connect_with_close_failure(*args, **kwargs):
            nonlocal connections
            connections += 1
            connection = real_connect(*args, **kwargs)
            if connections == 1:
                return connection
            return CloseFailConnection(connection)

        with patch("anonlab.pir_replay_store.sqlite3.connect", side_effect=connect_with_close_failure):
            with self.assertRaisesRegex(ReplayStoreError, "connection cleanup failed"):
                store.admit(nonce, int(self.now[0]))

        self.assertTrue(store._untrusted)
        # The connection may have committed before close reported an error.
        # Verify the ambiguous outcome is treated conservatively: the nonce
        # remains consumed, and a newly constructed store rejects its replay.
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT nonce FROM seen_nonces WHERE server_id=?", ("replica-a",)
            ).fetchall()
        self.assertIn(nonce, [row[0] for row in rows])
        reopened = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with self.assertRaisesRegex(ReplayRejected, "replay"):
            reopened.admit(nonce, int(self.now[0]))
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_connection_is_closed_when_initial_pragma_fails(self):
        class FailingConnection:
            closed = False

            def execute(self, _sql):
                raise sqlite3.OperationalError("simulated PRAGMA failure")

            def close(self):
                self.closed = True

        connection = FailingConnection()
        with patch("anonlab.pir_replay_store.sqlite3.connect", return_value=connection):
            with self.assertRaisesRegex(ReplayStoreError, "unavailable"):
                self.store._connect()

        self.assertTrue(connection.closed)
        self.assertTrue(self.store._untrusted)

    def test_unexpected_connection_setup_exception_closes_and_latches(self):
        class FailingConnection:
            closed = False

            def execute(self, _sql):
                raise RuntimeError("simulated unexpected PRAGMA failure")

            def close(self):
                self.closed = True

        connection = FailingConnection()
        store = DurablePirReplayStore(
            self.path, server_id="replica-connect-runtime", clock=lambda: self.now[0]
        )
        with patch("anonlab.pir_replay_store.sqlite3.connect", return_value=connection):
            with self.assertRaisesRegex(ReplayStoreError, "unavailable"):
                store._connect()

        self.assertTrue(connection.closed)
        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_partial_initialization_is_latched_and_never_reset_implicitly(self):
        class FailingInitializationConnection:
            def execute(self, _sql, _params=()):
                raise sqlite3.OperationalError("simulated schema creation failure")

            def close(self):
                pass

        store = DurablePirReplayStore(
            Path(self.tmp.name) / "partial.sqlite3",
            server_id="replica-partial",
            clock=lambda: self.now[0],
        )
        with patch.object(store, "_connect", return_value=FailingInitializationConnection()):
            with self.assertRaisesRegex(ReplayStoreError, "could not initialize"):
                store.initialize()

        # Preserve the incomplete artifact for explicit operator inspection;
        # automatic deletion could remove a replaced or otherwise valuable file.
        self.assertTrue(store.path.exists())
        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.initialize()
        self.assertTrue(store.path.exists())
        self.assertTrue(store._untrusted)

    def test_unexpected_transaction_exception_rolls_back_and_latches(self):
        real_connect = sqlite3.connect

        class UnexpectedExecuteConnection:
            def __init__(self, connection):
                self.connection = connection

            @property
            def in_transaction(self):
                return self.connection.in_transaction

            def execute(self, sql, *args, **kwargs):
                if "key='schema_version'" in sql:
                    raise RuntimeError("simulated adapter failure")
                return self.connection.execute(sql, *args, **kwargs)

            def close(self):
                self.transaction_was_open_at_close = self.connection.in_transaction
                self.connection.close()
                self.closed = True

        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        connection = UnexpectedExecuteConnection(
            real_connect(self.path, timeout=2.0, isolation_level=None)
        )
        with patch.object(store, "_persist_wall_high_water", return_value=self.now[0]), patch.object(store, "_connect", return_value=connection):
            with self.assertRaisesRegex(ReplayStoreError, "admission failed"):
                store.admit(self.nonce(), int(self.now[0]))

        self.assertTrue(connection.closed)
        self.assertFalse(connection.transaction_was_open_at_close)
        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_unexpected_initialization_exception_latches_partial_store(self):
        class UnexpectedInitializationConnection:
            def execute(self, _sql, _params=()):
                raise RuntimeError("simulated adapter failure during initialization")

            def close(self):
                pass

        path = Path(self.tmp.name) / "unexpected-partial.sqlite3"
        store = DurablePirReplayStore(
            path, server_id="replica-unexpected-init", clock=lambda: self.now[0]
        )
        with patch.object(store, "_connect", return_value=UnexpectedInitializationConnection()):
            with self.assertRaisesRegex(ReplayStoreError, "could not initialize"):
                store.initialize()

        self.assertTrue(path.exists())
        self.assertTrue(store._untrusted)
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.initialize()

    def test_corrupt_database_fails_closed(self):
        self.path.write_bytes(b"not a sqlite database")
        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with self.assertRaises(ReplayStoreError):
            store.admit(self.nonce(), int(self.now[0]))
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))

    def test_schema_mismatch_latches_store_untrusted(self):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE metadata SET value='999' WHERE key='schema_version'"
            )
        store = DurablePirReplayStore(
            self.path, server_id="replica-a", max_entries=8, clock=lambda: self.now[0]
        )
        with self.assertRaisesRegex(ReplayStoreError, "schema/metadata"):
            store.admit(self.nonce(), int(self.now[0]))
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            store.admit(self.nonce(), int(self.now[0]))


if __name__ == "__main__":
    unittest.main()
