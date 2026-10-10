import time
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from anonlab.pir_commitment import AuthenticatedSnapshot
from anonlab.pir_manifest import (
    ManifestError, SnapshotCheckpoint, sign_snapshot_manifest,
    verify_snapshot_manifest,
)


def _manifest(key, sequence=1, created_at=None, rows=(b"a", b"b")):
    snapshot = AuthenticatedSnapshot.build(rows)
    return sign_snapshot_manifest(
        private_key=key, snapshot_id=f"snapshot-{sequence}", sequence=sequence,
        created_at=int(time.time()) if created_at is None else created_at,
        record_count=snapshot.record_count, merkle_root=snapshot.root,
    )


def test_signed_manifest_round_trip_and_wrong_key_rejection():
    key = Ed25519PrivateKey.generate()
    manifest = _manifest(key)
    verify_snapshot_manifest(manifest, key.public_key())
    with pytest.raises(ManifestError, match="signature"):
        verify_snapshot_manifest(manifest, Ed25519PrivateKey.generate().public_key())


def test_manifest_tampering_and_invalid_fields_are_rejected():
    key = Ed25519PrivateKey.generate()
    manifest = _manifest(key)
    with pytest.raises(ManifestError, match="signature"):
        verify_snapshot_manifest(replace(manifest, sequence=manifest.sequence + 1), key.public_key())
    with pytest.raises(ManifestError, match="sequence"):
        _manifest(key, sequence=-1)


def test_freshness_and_future_timestamp_policy():
    key = Ed25519PrivateKey.generate()
    now = 2_000_000_000
    fresh = _manifest(key, created_at=now - 30)
    verify_snapshot_manifest(fresh, key.public_key(), now=now, max_age_seconds=60)
    with pytest.raises(ManifestError, match="stale"):
        verify_snapshot_manifest(fresh, key.public_key(), now=now, max_age_seconds=10)
    future = _manifest(key, created_at=now + 500)
    with pytest.raises(ManifestError, match="future"):
        verify_snapshot_manifest(future, key.public_key(), now=now)


def test_checkpoint_rejects_rollback_and_same_sequence_equivocation():
    key = Ed25519PrivateKey.generate()
    checkpoint = SnapshotCheckpoint()
    first = _manifest(key, sequence=4)
    checkpoint.verify_and_advance(first, key.public_key())
    checkpoint.verify_and_advance(first, key.public_key())
    older = _manifest(key, sequence=3)
    with pytest.raises(ManifestError, match="rollback"):
        checkpoint.verify_and_advance(older, key.public_key())
    conflicting = _manifest(key, sequence=4, rows=(b"evil",))
    with pytest.raises(ManifestError, match="equivocation"):
        checkpoint.verify_and_advance(conflicting, key.public_key())


def test_checkpoint_advances_only_after_verification():
    key = Ed25519PrivateKey.generate()
    checkpoint = SnapshotCheckpoint()
    bad = _manifest(Ed25519PrivateKey.generate(), sequence=9)
    with pytest.raises(ManifestError):
        checkpoint.verify_and_advance(bad, key.public_key())
    assert checkpoint.sequence == -1


def test_checkpoint_atomic_persistence_round_trip(tmp_path):
    from anonlab.pir_manifest import load_checkpoint, save_checkpoint
    key = Ed25519PrivateKey.generate()
    checkpoint = SnapshotCheckpoint()
    checkpoint.verify_and_advance(_manifest(key, sequence=12), key.public_key())
    path = tmp_path / "state" / "checkpoint.json"
    path.parent.mkdir()
    save_checkpoint(path, checkpoint)
    restored = load_checkpoint(path)
    assert restored.sequence == checkpoint.sequence
    assert restored.manifest_digest == checkpoint.manifest_digest


def test_checkpoint_loader_rejects_malformed_or_unknown_schema(tmp_path):
    from anonlab.pir_manifest import load_checkpoint
    path = tmp_path / "checkpoint.json"
    path.write_text('{"schema_version":99,"sequence":1,"manifest_digest":"' + '00' * 32 + '"}')
    with pytest.raises(ManifestError, match="schema"):
        load_checkpoint(path)
    path.write_text('{broken json')
    with pytest.raises(ManifestError, match="load checkpoint"):
        load_checkpoint(path)


def test_checkpoint_save_rejects_inconsistent_state(tmp_path):
    from anonlab.pir_manifest import save_checkpoint
    path = tmp_path / "checkpoint.json"
    with pytest.raises(ManifestError, match="digest"):
        save_checkpoint(path, SnapshotCheckpoint(sequence=3, manifest_digest=b"short"))
