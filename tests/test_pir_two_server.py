from __future__ import annotations
from collections import Counter
import random
import unittest

from anonlab.pir_two_server import PirReferenceServer, make_query_pair, retrieve_two_server_pir


def mask_bytes(value: int, item_count: int) -> bytes:
    return value.to_bytes((item_count + 7) // 8, "little")


class TwoServerPirTests(unittest.TestCase):
    def test_retrieves_each_record_correctly(self):
        records = tuple(bytes([i, i ^ 0x55, i ^ 0xAA, 255 - i]) for i in range(32))
        a, b = PirReferenceServer(records), PirReferenceServer(records)
        for index, expected in enumerate(records):
            transfer = retrieve_two_server_pir(a, b, index, rng=random.Random(index))
            self.assertEqual(transfer.record, expected)
            self.assertEqual(transfer.query_bytes_per_server, 4)
            self.assertEqual(transfer.response_bytes_per_server, len(expected))

    def test_each_servers_query_mask_distribution_is_independent_of_target(self):
        n = 4
        masks = [mask_bytes(mask, n) for mask in range(1 << n)]
        per_target_a = []
        per_target_b = []
        for target in range(n):
            pairs = [make_query_pair(n, target, rng=FakeMaskRng(mask)) for mask in range(1 << n)]
            per_target_a.append(Counter(a for a, _ in pairs))
            per_target_b.append(Counter(b for _, b in pairs))
        for counts in per_target_a[1:]:
            self.assertEqual(counts, per_target_a[0])
        for counts in per_target_b[1:]:
            self.assertEqual(counts, per_target_b[0])
        self.assertEqual(set(per_target_a[0]), set(masks))
        self.assertEqual(set(per_target_b[0]), set(masks))

    def test_collusion_recovers_one_hot_target_mask(self):
        n = 13
        target = 9
        q_a, q_b = make_query_pair(n, target, rng=random.Random(7))
        xor = bytes(a ^ b for a, b in zip(q_a, q_b, strict=True))
        self.assertEqual(xor, (1 << target).to_bytes((n + 7) // 8, "little"))

    def test_query_lengths_and_responses_are_fixed_for_all_indices(self):
        records = tuple(bytes([idx]) * 64 for idx in range(11))
        a, b = PirReferenceServer(records), PirReferenceServer(records)
        observations = [retrieve_two_server_pir(a, b, index, rng=random.Random(index)) for index in range(11)]
        self.assertEqual({r.query_bytes_per_server for r in observations}, {2})
        self.assertEqual({r.response_bytes_per_server for r in observations}, {64})

    def test_rejects_invalid_records_masks_and_indexes(self):
        with self.assertRaises(ValueError):
            PirReferenceServer([])
        with self.assertRaises(ValueError):
            PirReferenceServer([b"a", b"ab"])
        with self.assertRaises(ValueError):
            PirReferenceServer([b"a", "b"])  # type: ignore[list-item]
        server = PirReferenceServer([b"aa", b"bb", b"cc"])
        with self.assertRaises(ValueError):
            server.answer(b"")
        with self.assertRaises(ValueError):
            server.answer(b"\xf8")
        with self.assertRaises(ValueError):
            make_query_pair(3, 3)
        with self.assertRaises(ValueError):
            retrieve_two_server_pir(server, PirReferenceServer([b"xx", b"yy"]), 0)

    def test_rejects_unbounded_database_size(self):
        with self.assertRaises(ValueError):
            PirReferenceServer([b"x" * 1_048_576 for _ in range(65)])


class FakeMaskRng:
    """Exhaustively expose every q1 mask; never used outside privacy tests."""
    def __init__(self, value: int) -> None:
        self.value = value
    def randbytes(self, n: int) -> bytes:
        return self.value.to_bytes(n, "little")


if __name__ == "__main__":
    unittest.main()
