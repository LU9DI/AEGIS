from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from anonlab.directory import (
        DirectoryAuthority,
        DirectoryVerifier,
        create_relay_descriptor,
        descriptor_from_json,
        descriptor_to_json,
        relay_identity_digest,
    )
except (ImportError, RuntimeError):  # optional research dependency
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]


def raw_x25519_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


@unittest.skipIf(Ed25519PrivateKey is None, "install aegis-anon-lab[onion-lab] for directory tests")
class SignedDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_800_000_000
        self.authority = DirectoryAuthority.generate()
        self.identity_private = Ed25519PrivateKey.generate()
        self.onion_private = X25519PrivateKey.generate()
        self.verifier = DirectoryVerifier(self.authority.public_key_bytes)
        self.descriptor = self.issue_descriptor()
        self.empty_revocations = self.authority.sign_revocations([], epoch=1, now=self.now)
        self.verifier.apply_revocations(self.empty_revocations, now=self.now)

    def issue_descriptor(self, *, sequence: int = 1, now: int | None = None, valid_for: int = 3600, host: str = "127.0.0.1", port: int = 9001, onion_key: bytes | None = None) -> dict:
        current = self.now if now is None else now
        unsigned = create_relay_descriptor(
            self.identity_private,
            onion_key if onion_key is not None else raw_x25519_public(self.onion_private),
            host,
            port,
            now=current,
            valid_for_seconds=valid_for,
            sequence=sequence,
        )
        return self.authority.certify(unsigned, now=current)

    def test_durable_authority_rejects_conflicting_sequence_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "authority.sqlite3"
            authority = DirectoryAuthority(self.authority.private_key, state_path=state_path)
            first = create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private), "127.0.0.1", 9001,
                now=self.now, sequence=1, serial="a" * 32,
            )
            first_certified = authority.certify(first, now=self.now)
            restarted = DirectoryAuthority(self.authority.private_key, state_path=state_path)
            self.assertEqual(first_certified, restarted.certify(first, now=self.now))
            conflict = create_relay_descriptor(
                self.identity_private, raw_x25519_public(X25519PrivateKey.generate()), "127.0.0.1", 9001,
                now=self.now, sequence=1, serial="b" * 32,
            )
            with self.assertRaisesRegex(ValueError, "conflicting descriptors share the same sequence"):
                restarted.certify(conflict, now=self.now)
            next_sequence = create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private), "127.0.0.1", 9001,
                now=self.now, sequence=2, serial="c" * 32,
            )
            restarted.certify(next_sequence, now=self.now)
            with self.assertRaisesRegex(ValueError, "sequence rollback"):
                restarted.certify(first, now=self.now)

    def test_durable_authority_rejects_serial_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = DirectoryAuthority(self.authority.private_key, state_path=Path(directory) / "authority.sqlite3")
            first = create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private), "127.0.0.1", 9001,
                now=self.now, sequence=1, serial="d" * 32,
            )
            authority.certify(first, now=self.now)
            other_identity = Ed25519PrivateKey.generate()
            second = create_relay_descriptor(
                other_identity, raw_x25519_public(X25519PrivateKey.generate()), "127.0.0.1", 9002,
                now=self.now, sequence=1, serial="d" * 32,
            )
            with self.assertRaisesRegex(ValueError, "already been used"):
                authority.certify(second, now=self.now)

    def test_durable_authority_concurrent_identical_issuance_is_idempotent(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "authority.sqlite3"
            descriptor = create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private), "127.0.0.1", 9001,
                now=self.now, sequence=1, serial="e" * 32,
            )
            authorities = [
                DirectoryAuthority(self.authority.private_key, state_path=state_path)
                for _ in range(8)
            ]
            with ThreadPoolExecutor(max_workers=len(authorities)) as executor:
                results = list(executor.map(
                    lambda authority: authority.certify(descriptor, now=self.now),
                    authorities,
                ))
            self.assertTrue(all(result == results[0] for result in results))

    def test_durable_authority_state_is_bound_to_authority_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "authority.sqlite3"
            first = DirectoryAuthority(self.authority.private_key, state_path=state_path)
            descriptor = create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private), "127.0.0.1", 9001,
                now=self.now, sequence=1, serial="f" * 32,
            )
            first.certify(descriptor, now=self.now)
            other = DirectoryAuthority(Ed25519PrivateKey.generate(), state_path=state_path)
            with self.assertRaisesRegex(ValueError, "different authority key"):
                other.certify(descriptor, now=self.now)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_durable_authority_rejects_symlink_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real.sqlite3"
            link = Path(directory) / "authority.sqlite3"
            target.touch()
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic-link creation is not permitted")
            authority = DirectoryAuthority(self.authority.private_key, state_path=link)
            descriptor = create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private), "127.0.0.1", 9001,
                now=self.now, sequence=1, serial="1" * 32,
            )
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                authority.certify(descriptor, now=self.now)

    def test_durable_authority_revocation_epochs_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "authority.sqlite3"
            authority = DirectoryAuthority(self.authority.private_key, state_path=state_path)
            revoked = "a" * 40
            first = authority.sign_revocations([revoked], epoch=1, now=self.now)
            # Same epoch is immutable and idempotent, even if called later.
            repeated = authority.sign_revocations([revoked], epoch=1, now=self.now + 10)
            self.assertEqual(repeated, first)
            second_id = "b" * 40
            next_snapshot = authority.sign_revocations([revoked, second_id], epoch=2, now=self.now + 20)
            restarted = DirectoryAuthority(self.authority.private_key, state_path=state_path)
            self.assertEqual(
                restarted.sign_revocations([revoked, second_id], epoch=2, now=self.now + 30),
                next_snapshot,
            )

    def test_durable_authority_rejects_revocation_rollback_and_equivocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = DirectoryAuthority(
                self.authority.private_key, state_path=Path(directory) / "authority.sqlite3"
            )
            first_id = "a" * 40
            second_id = "b" * 40
            authority.sign_revocations([first_id], epoch=4, now=self.now)
            with self.assertRaisesRegex(ValueError, "epoch rollback"):
                authority.sign_revocations([first_id], epoch=3, now=self.now + 1)
            with self.assertRaisesRegex(ValueError, "same epoch"):
                authority.sign_revocations([second_id], epoch=4, now=self.now + 1)
            with self.assertRaisesRegex(ValueError, "cumulative"):
                authority.sign_revocations([], epoch=5, now=self.now + 2)

    def test_valid_descriptor_round_trips_and_verifies(self) -> None:
        encoded = descriptor_to_json(self.descriptor)
        parsed = descriptor_from_json(encoded)
        verified = self.verifier.verify_descriptor(parsed, now=self.now + 1)
        identity_public = self.identity_private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.assertEqual(verified.identity_public_key, identity_public)
        self.assertEqual(verified.identity_digest, relay_identity_digest(identity_public))
        self.assertEqual(verified.host, "127.0.0.1")
        self.assertEqual(verified.port, 9001)
        self.assertEqual(verified.sequence, 1)

    def test_endpoint_tampering_fails_relay_signature(self) -> None:
        altered = copy.deepcopy(self.descriptor)
        altered["port"] = 9002
        with self.assertRaisesRegex(ValueError, "relay signature verification failed"):
            self.verifier.verify_descriptor(altered, now=self.now + 1)

    def test_onion_key_tampering_fails_signatures(self) -> None:
        altered = copy.deepcopy(self.descriptor)
        altered["onion_public_key"] = raw_x25519_public(X25519PrivateKey.generate()).hex()
        with self.assertRaisesRegex(ValueError, "relay signature verification failed"):
            self.verifier.verify_descriptor(altered, now=self.now + 1)

    def test_wrong_trust_anchor_fails_authority_signature(self) -> None:
        wrong = DirectoryVerifier(DirectoryAuthority.generate().public_key_bytes)
        with self.assertRaisesRegex(ValueError, "authority signature verification failed"):
            wrong.verify_descriptor(self.descriptor, now=self.now + 1)

    def test_expired_and_not_yet_valid_descriptors_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "expired"):
            self.verifier.verify_descriptor(self.descriptor, now=self.now + 3600)
        future = self.issue_descriptor(now=self.now + 600)
        with self.assertRaisesRegex(ValueError, "not valid yet"):
            self.verifier.verify_descriptor(future, now=self.now)

    def test_descriptor_lifetime_cap_is_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "within 1 second and 24 hours"):
            create_relay_descriptor(
                self.identity_private, raw_x25519_public(self.onion_private),
                "127.0.0.1", 9001, now=self.now, valid_for_seconds=86401,
            )

    def test_non_loopback_endpoint_and_dns_are_rejected(self) -> None:
        for host in ("example.com", "192.0.2.1", "::1", "0.0.0.0"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    create_relay_descriptor(
                        self.identity_private, raw_x25519_public(self.onion_private),
                        host, 9001, now=self.now,
                    )

    def test_descriptor_sequence_rotation_and_rollback(self) -> None:
        self.verifier.verify_descriptor(self.descriptor, now=self.now + 1)
        rotated = self.issue_descriptor(sequence=2, onion_key=raw_x25519_public(X25519PrivateKey.generate()))
        verified = self.verifier.verify_descriptor(rotated, now=self.now + 1)
        self.assertEqual(verified.sequence, 2)
        with self.assertRaisesRegex(ValueError, "sequence rollback"):
            self.verifier.verify_descriptor(self.descriptor, now=self.now + 1)

    def test_conflicting_descriptors_same_sequence_rejected(self) -> None:
        self.verifier.verify_descriptor(self.descriptor, now=self.now + 1)
        conflict = self.issue_descriptor(sequence=1, port=9002)
        with self.assertRaisesRegex(ValueError, "conflicting descriptors"):
            self.verifier.verify_descriptor(conflict, now=self.now + 1)

    def test_revoked_relay_is_rejected(self) -> None:
        relay_id = self.descriptor["relay_id"]
        snapshot = self.authority.sign_revocations([relay_id], epoch=2, now=self.now + 10)
        self.verifier.apply_revocations(snapshot, now=self.now + 10)
        with self.assertRaisesRegex(ValueError, "identity is revoked"):
            self.verifier.verify_descriptor(self.descriptor, now=self.now + 11)

    def test_revocation_snapshot_tampering_rejected(self) -> None:
        altered = copy.deepcopy(self.empty_revocations)
        altered["revoked_relay_ids"] = ["a" * 40]
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.verifier.apply_revocations(altered, now=self.now + 1)

    def test_revocation_expiry_and_rollback_rejected(self) -> None:
        expired = self.authority.sign_revocations([], epoch=2, now=self.now, valid_for_seconds=10)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.verifier.apply_revocations(expired, now=self.now + 10)
        newer = self.authority.sign_revocations([], epoch=3, now=self.now + 1)
        self.verifier.apply_revocations(newer, now=self.now + 1)
        with self.assertRaisesRegex(ValueError, "rollback detected"):
            self.verifier.apply_revocations(self.empty_revocations, now=self.now + 2)

    def test_revocation_snapshots_are_cumulative(self) -> None:
        revoked_id = "a" * 40
        one = self.authority.sign_revocations([revoked_id], epoch=2, now=self.now + 1)
        self.verifier.apply_revocations(one, now=self.now + 1)
        removal = self.authority.sign_revocations([], epoch=3, now=self.now + 2)
        with self.assertRaisesRegex(ValueError, "cannot be un-revoked"):
            self.verifier.apply_revocations(removal, now=self.now + 2)

    def test_duplicate_and_unsorted_revocations_rejected(self) -> None:
        body = {
            "schema_version": 1, "epoch": 2, "issued_at": self.now + 1,
            "expires_at": self.now + 100, "revoked_relay_ids": ["b" * 40, "a" * 40],
        }
        sig = self.authority.private_key.sign(
            b"MALEBOLGE/revocations/v1\x00" + __import__("json").dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
        ).hex()
        snapshot = {**body, "authority_signature": sig}
        with self.assertRaisesRegex(ValueError, "sorted list"):
            self.verifier.apply_revocations(snapshot, now=self.now + 1)

    def test_strict_schema_rejects_unknown_fields(self) -> None:
        altered = copy.deepcopy(self.descriptor)
        altered["extra"] = "untrusted"
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.verifier.verify_descriptor(altered, now=self.now + 1)

    def test_json_parser_rejects_malformed_non_object_and_oversized(self) -> None:
        for value in ("{", "[]", " " * 16385):
            with self.subTest(value=value[:10]):
                with self.assertRaises(ValueError):
                    descriptor_from_json(value)

    def test_json_parser_rejects_duplicate_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate field"):
            descriptor_from_json('{"relay_id":"a","relay_id":"b"}')

    def test_schema_version_requires_integer_not_boolean_or_float(self) -> None:
        altered = copy.deepcopy(self.descriptor)
        altered["schema_version"] = 1.0
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.verifier.verify_descriptor(altered, now=self.now + 1)
        altered["schema_version"] = True
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.verifier.verify_descriptor(altered, now=self.now + 1)

    def test_verified_descriptor_can_convert_to_loopback_circuit_descriptor(self) -> None:
        verified = self.verifier.verify_descriptor(self.descriptor, now=self.now + 1)
        circuit_descriptor = verified.to_telescoping_descriptor()
        self.assertEqual(circuit_descriptor.host, "127.0.0.1")
        self.assertEqual(circuit_descriptor.port, 9001)
        self.assertEqual(circuit_descriptor.identity_digest, verified.identity_digest)
        self.assertEqual(circuit_descriptor.onion_public_key, verified.onion_public_key)

    def test_persistent_state_survives_restart_and_rejects_descriptor_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "trust-state.json"
            verifier = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            verifier.apply_revocations(self.empty_revocations, now=self.now)
            verifier.verify_descriptor(self.descriptor, now=self.now + 1)
            rotated = self.issue_descriptor(sequence=2, onion_key=raw_x25519_public(X25519PrivateKey.generate()))
            verifier.verify_descriptor(rotated, now=self.now + 1)
            self.assertTrue(state_path.exists())
            if os.name == "posix":
                self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)

            restarted = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            self.assertEqual(restarted.revocation_epoch, 1)
            restarted.apply_revocations(self.empty_revocations, now=self.now + 2)
            with self.assertRaisesRegex(ValueError, "sequence rollback"):
                restarted.verify_descriptor(self.descriptor, now=self.now + 2)
            self.assertEqual(restarted.verify_descriptor(rotated, now=self.now + 2).sequence, 2)

    def test_persistent_state_is_bound_to_trust_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "trust-state.json"
            verifier = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            verifier.apply_revocations(self.empty_revocations, now=self.now)
            verifier.verify_descriptor(self.descriptor, now=self.now + 1)
            with self.assertRaisesRegex(ValueError, "different authority key"):
                DirectoryVerifier(DirectoryAuthority.generate().public_key_bytes, state_path=state_path)

    def test_malformed_or_permissive_persistent_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "trust-state.json"
            state_path.write_text('{"schema_version":1,', encoding="ascii")
            if os.name == "posix":
                state_path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "malformed"):
                DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            state_path.write_text("{}", encoding="ascii")
            if os.name == "posix":
                state_path.chmod(0o644)
                with self.assertRaisesRegex(ValueError, "permissions are too broad"):
                    DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)

    def test_persisted_revocation_snapshot_cannot_be_edited_without_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            relay_id = self.descriptor["relay_id"]
            snapshot = self.authority.sign_revocations([relay_id], epoch=1, now=self.now)
            verifier = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            verifier.apply_revocations(snapshot, now=self.now)
            state = json.loads(state_path.read_text(encoding="ascii"))
            state["revoked_relay_ids"] = []
            state["revocation_snapshot"]["revoked_relay_ids"] = []
            state_path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="ascii")
            if os.name == "posix":
                state_path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "signed revocation snapshot signature is invalid"):
                DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)

    def test_persistent_state_rejects_non_string_revocation_ids_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            relay_id = self.descriptor["relay_id"]
            snapshot = self.authority.sign_revocations([relay_id], epoch=1, now=self.now)
            verifier = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            verifier.apply_revocations(snapshot, now=self.now)
            state = json.loads(state_path.read_text(encoding="ascii"))
            state["revoked_relay_ids"] = [{}]
            state["revocation_snapshot"]["revoked_relay_ids"] = [{}]
            state_path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="ascii")
            if os.name == "posix":
                state_path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "signed revocation IDs are invalid"):
                DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)

    def test_state_write_failure_does_not_advance_revocation_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            verifier = DirectoryVerifier(
                self.authority.public_key_bytes, state_path=Path(directory) / "state.json"
            )
            with patch.object(verifier, "_persist_candidate", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    verifier.apply_revocations(self.empty_revocations, now=self.now)
            self.assertEqual(verifier.revocation_epoch, 0)
            self.assertEqual(verifier.revoked_relay_ids, frozenset())

    def test_route_materialization_requires_fresh_revocations(self) -> None:
        verifier = DirectoryVerifier(self.authority.public_key_bytes)
        with self.assertRaisesRegex(ValueError, "no verified revocation snapshot"):
            verifier.verify_circuit_descriptors([self.descriptor], now=self.now + 1)

    def test_verified_route_requires_persistent_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "persistent directory state is required"):
            self.verifier.verify_circuit_route([self.descriptor], now=self.now + 1)

    def test_new_revocation_snapshot_invalidates_existing_verified_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            persistent = DirectoryVerifier(
                self.authority.public_key_bytes, state_path=Path(directory) / "state.json"
            )
            persistent.apply_revocations(self.empty_revocations, now=self.now)
            route = persistent.verify_circuit_route([self.descriptor], now=self.now + 1)
            newer_snapshot = self.authority.sign_revocations([], epoch=2, now=self.now + 2)
            persistent.apply_revocations(newer_snapshot, now=self.now + 2)
            with self.assertRaisesRegex(ValueError, "invalidated by a newer revocation snapshot"):
                route.assert_usable(now=self.now + 2)

    def test_newer_descriptor_invalidates_existing_verified_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            persistent = DirectoryVerifier(
                self.authority.public_key_bytes, state_path=Path(directory) / "state.json"
            )
            persistent.apply_revocations(self.empty_revocations, now=self.now)
            route = persistent.verify_circuit_route([self.descriptor], now=self.now + 1)
            rotated = self.issue_descriptor(sequence=2, onion_key=raw_x25519_public(X25519PrivateKey.generate()))
            persistent.verify_descriptor(rotated, now=self.now + 2)
            with self.assertRaisesRegex(ValueError, "superseded by a newer relay descriptor"):
                route.assert_usable(now=self.now + 2)

    def test_expired_persisted_revocation_feed_fails_closed_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            short_feed = self.authority.sign_revocations([], epoch=1, now=self.now, valid_for_seconds=5)
            verifier = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            verifier.apply_revocations(short_feed, now=self.now)
            restarted = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            with self.assertRaisesRegex(ValueError, "revocation snapshot expired"):
                restarted.verify_circuit_descriptors([self.descriptor], now=self.now + 5)

    def test_revoked_id_persists_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            relay_id = self.descriptor["relay_id"]
            snapshot = self.authority.sign_revocations([relay_id], epoch=1, now=self.now)
            verifier = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            verifier.apply_revocations(snapshot, now=self.now)
            restarted = DirectoryVerifier(self.authority.public_key_bytes, state_path=state_path)
            self.assertIn(relay_id, restarted.revoked_relay_ids)
            with self.assertRaisesRegex(ValueError, "identity is revoked"):
                restarted.verify_descriptor(self.descriptor, now=self.now + 1)

    def test_verified_route_is_expiry_bound_and_not_manually_constructible(self) -> None:
        from anonlab.directory import VerifiedCircuitRoute

        with tempfile.TemporaryDirectory() as directory:
            persistent = DirectoryVerifier(
                self.authority.public_key_bytes, state_path=Path(directory) / "state.json"
            )
            persistent.apply_revocations(self.empty_revocations, now=self.now)
            route = persistent.verify_circuit_route([self.descriptor], now=self.now + 1)
        self.assertEqual(len(route.descriptors), 1)
        with self.assertRaisesRegex(ValueError, "has expired"):
            route.assert_usable(now=route.expires_at)
        with self.assertRaisesRegex(ValueError, "created by DirectoryVerifier"):
            VerifiedCircuitRoute(
                _descriptors=(), authority_key_fingerprint="0" * 64,
                revocation_epoch=1, expires_at=self.now + 10,
                _relay_sequences=(), _verifier=persistent, _token=object(),
            )

    def test_directory_demo_exercises_rotation_and_revocation(self) -> None:
        from anonlab.directory_demo import run_demo

        result = run_demo()
        self.assertFalse(result["is_live_network_test"])
        self.assertTrue(result["descriptor_v1_verified"])
        self.assertTrue(result["descriptor_v2_onion_key_rotation_verified"])
        self.assertTrue(result["persistent_state_reloaded"])
        self.assertTrue(result["descriptor_rollback_rejected_after_restart"])
        self.assertTrue(result["revoked_descriptor_rejected"])
        self.assertTrue(result["verified_route_invalidated_after_revocation_update"])

    def test_circuit_verification_rejects_duplicates_and_excess_hops(self) -> None:
        verified = self.verifier.verify_circuit_descriptors([self.descriptor], now=self.now + 1)
        self.assertEqual(len(verified), 1)
        with self.assertRaisesRegex(ValueError, "duplicate relay identities"):
            self.verifier.verify_circuit_descriptors(
                [self.descriptor, self.descriptor], now=self.now + 1
            )
        descriptors = [self.descriptor]
        with self.assertRaisesRegex(ValueError, "maximum hop count"):
            self.verifier.verify_circuit_descriptors(descriptors * 2, now=self.now + 1, max_hops=1)


if __name__ == "__main__":
    unittest.main()