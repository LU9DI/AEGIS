from __future__ import annotations

import multiprocessing
from pathlib import Path
import tempfile
import unittest

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from anonlab.directory import DirectoryAuthority, create_relay_descriptor
except (ImportError, RuntimeError):
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]


def _certify_in_child(
    state_path: str,
    authority_private_key_pem: bytes,
    descriptor: dict[str, object],
    now: int,
    output: multiprocessing.Queue,
) -> None:
    try:
        key = serialization.load_pem_private_key(authority_private_key_pem, password=None)
        authority = DirectoryAuthority(key, state_path=state_path)
        output.put(("ok", authority.certify(descriptor, now=now)))
    except Exception as exc:
        output.put(("error", type(exc).__name__, str(exc)))


@unittest.skipIf(Ed25519PrivateKey is None, "install aegis-anon-lab[onion-lab] for directory tests")
class DirectoryAuthorityProcessConcurrencyTests(unittest.TestCase):
    def test_identical_issuance_is_idempotent_across_processes(self) -> None:
        now = 1_800_000_000
        authority_key = Ed25519PrivateKey.generate()
        identity_key = Ed25519PrivateKey.generate()
        onion_key = X25519PrivateKey.generate()
        raw_onion_public = onion_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        unsigned = create_relay_descriptor(
            identity_key,
            raw_onion_public,
            "127.0.0.1",
            9101,
            now=now,
            valid_for_seconds=3600,
            sequence=1,
            serial="a" * 32,
        )
        private_pem = authority_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "authority.sqlite3")
            context = multiprocessing.get_context("spawn")
            output = context.Queue()
            processes = [
                context.Process(
                    target=_certify_in_child,
                    args=(state_path, private_pem, unsigned, now, output),
                )
                for _ in range(4)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
            try:
                self.assertTrue(
                    all(not process.is_alive() for process in processes),
                    "child process hung while competing for authority state",
                )
                self.assertTrue(
                    all(process.exitcode == 0 for process in processes),
                    f"child process exited abnormally: {[p.exitcode for p in processes]}",
                )
                results = [output.get(timeout=3) for _ in processes]
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join()
                output.close()
                output.join_thread()

        errors = [result for result in results if result[0] != "ok"]
        self.assertEqual(errors, [], f"concurrent issuance errors: {errors}")
        certificates = [result[1] for result in results]
        self.assertTrue(all(certificate == certificates[0] for certificate in certificates))

    def test_conflicting_same_sequence_has_exactly_one_winner_across_processes(self) -> None:
        now = 1_800_000_000
        authority_key = Ed25519PrivateKey.generate()
        identity_key = Ed25519PrivateKey.generate()
        authority_pem = authority_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        def make_descriptor(serial: str, onion_key: X25519PrivateKey) -> dict[str, object]:
            raw_public = onion_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            return create_relay_descriptor(
                identity_key,
                raw_public,
                "127.0.0.1",
                9102,
                now=now,
                valid_for_seconds=3600,
                sequence=1,
                serial=serial,
            )

        first = make_descriptor("b" * 32, X25519PrivateKey.generate())
        second = make_descriptor("c" * 32, X25519PrivateKey.generate())

        with tempfile.TemporaryDirectory() as directory:
            state_path = str(Path(directory) / "authority.sqlite3")
            context = multiprocessing.get_context("spawn")
            output = context.Queue()
            processes = [
                context.Process(
                    target=_certify_in_child,
                    args=(state_path, authority_pem, descriptor, now, output),
                )
                for descriptor in (first, second)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
            try:
                self.assertTrue(all(not process.is_alive() for process in processes))
                self.assertTrue(all(process.exitcode == 0 for process in processes))
                results = [output.get(timeout=3) for _ in processes]
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join()
                output.close()
                output.join_thread()

        successes = [result for result in results if result[0] == "ok"]
        failures = [result for result in results if result[0] == "error"]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assertIn("conflicting descriptors share the same sequence", failures[0][2])
