from dataclasses import replace

import pytest

from anonlab.pir_commitment import AuthenticatedSnapshot, InclusionProof, verify_inclusion


def test_inclusion_proofs_verify_for_varied_tree_sizes():
    for count in range(1, 18):
        snapshot = AuthenticatedSnapshot.build([f"record-{i}".encode() for i in range(count)])
        assert len(snapshot.root) == 32
        for index in range(count):
            proof = snapshot.proof(index)
            assert verify_inclusion(snapshot.root, proof)


def test_tampered_record_and_root_are_rejected():
    snapshot = AuthenticatedSnapshot.build([b"alpha", b"beta", b"gamma"])
    proof = snapshot.proof(1)
    assert not verify_inclusion(snapshot.root, replace(proof, record=b"evil"))
    assert not verify_inclusion(bytes([snapshot.root[0] ^ 1]) + snapshot.root[1:], proof)


def test_wrong_index_path_and_malformed_proofs_are_rejected():
    snapshot = AuthenticatedSnapshot.build([b"a", b"b", b"c", b"d"])
    proof = snapshot.proof(2)
    assert not verify_inclusion(snapshot.root, replace(proof, index=1))
    assert not verify_inclusion(snapshot.root, replace(proof, siblings=proof.siblings[:-1]))
    assert not verify_inclusion(snapshot.root, replace(proof, siblings=(("sideways", b"x" * 32),) + proof.siblings[1:]))


def test_empty_snapshot_has_stable_root_but_no_proofs():
    empty = AuthenticatedSnapshot.build([])
    assert empty.record_count == 0
    assert len(empty.root) == 32
    with pytest.raises(IndexError):
        empty.proof(0)
    assert not verify_inclusion(empty.root, InclusionProof(0, 0, b"", ()))


def test_snapshot_is_bound_to_record_order_and_position():
    first = AuthenticatedSnapshot.build([b"a", b"b"])
    reordered = AuthenticatedSnapshot.build([b"b", b"a"])
    assert first.root != reordered.root
    assert not verify_inclusion(reordered.root, first.proof(0))
