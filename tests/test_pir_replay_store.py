from __future__ import annotations

import base64
import multiprocessing
import secrets
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anonlab.pir_replay_store import DurablePirReplayStore, ReplayRejected, ReplayStoreError


def _admit_in_process(path: str, nonce: str, issued_at: int, queue) -> None:
    store = DurablePirReplayStore(path, server_id="multiprocess-replica", max_entries=16)
    try:
        store.admit(nonce, issued_at)
        queue.put(True)
    except (ReplayRejected, ReplayStoreError):
        queue.put(False)


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

    def test_two_processes_admit_same_nonce_exactly_once(self):
        path = Path(self.tmp.name) / "multiprocess.sqlite3"
        store = DurablePirReplayStore(path, server_id="multiprocess-replica", max_entries=16)
        store.initialize()
        nonce = self.nonce()
        issued = int(time.time())
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        processes = [
            context.Process(target=_admit_in_process, args=(str(path), nonce, issued, queue))
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

    def test_expired_nonce_can_be_removed_only_after_validity_window(self):
        nonce = self.nonce()
        issued = int(self.now[0])
        self.store.admit(nonce, issued)
        self.now[0] += 122
        self.store.admit(nonce, int(self.now[0]))

    def test_extreme_timestamp_integer_is_rejected_without_overflow(self):
        with self.assertRaisesRegex(ReplayRejected, "timestamp"):
            self.store.admit(self.nonce(), 10**10_000)

    def test_backward_clock_step_fails_closed(self):
        self.store.admit(self.nonce(), int(self.now[0]))
        self.now[0] -= 5
        with self.assertRaisesRegex(ReplayStoreError, "backwards"):
            self.store.admit(self.nonce(), int(self.now[0]))
        self.now[0] += 10
        with self.assertRaisesRegex(ReplayStoreError, "untrusted"):
            self.store.admit(self.nonce(), int(self.now[0]))

    def test_initialization_refuses_to_reset_existing_database(self):
        with self.assertRaisesRegex(ReplayStoreError, "already exists"):
            self.store.initialize()

    def test_invalid_initial_clock_does_not_create_database(self):
        path = Path(self.tmp.name) / "invalid-clock.sqlite3"
        store = DurablePirReplayStore(
            path, server_id="replica-clock", clock=lambda: float("nan")
        )
        with self.assertRaisesRegex(ReplayStoreError, "clock is invalid"):
            store.initialize()
        self.assertFalse(path.exists())

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
