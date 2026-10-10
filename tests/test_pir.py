from __future__ import annotations

import unittest

from anonlab.pir import _pack_queries_from_mask, answer_query, create_queries, recover_record, retrieve_for_demo


class TwoServerPIRTests(unittest.TestCase):
    def setUp(self):
        self.records = [bytes([i, i ^ 0xA5, (i * 7) & 255, 0xCC]) for i in range(16)]

    def test_end_to_end_recovers_requested_fixed_width_record(self):
        for index, record in enumerate(self.records):
            with self.subTest(index=index):
                result = retrieve_for_demo(self.records, index)
                self.assertEqual(result.record, record)
                self.assertEqual(result.query_bytes_per_server, 2)
                self.assertEqual(result.response_bytes_per_server, len(record))

    def test_each_single_server_query_distribution_is_index_independent(self):
        # Exhaustive proof for a tiny toy DB: flipping the requested bit is a
        # permutation over all masks, so either server's query is uniform.
        n = 4
        universe = 1 << n
        for index in range(n):
            server_a = []
            server_b = []
            for mask in range(universe):
                a, b = _pack_queries_from_mask(n, index, mask)
                server_a.append(a)
                server_b.append(b)
            self.assertEqual(set(server_a), {x.to_bytes(1, "little") for x in range(universe)})
            self.assertEqual(set(server_b), {x.to_bytes(1, "little") for x in range(universe)})
            self.assertEqual(len(set(server_a)), universe)
            self.assertEqual(len(set(server_b)), universe)

    def test_real_query_pair_has_same_length_and_no_index_field(self):
        query = create_queries(19, 13)
        self.assertEqual(len(query.server_a), len(query.server_b))
        self.assertFalse(hasattr(query, "index"))
        self.assertEqual(query.record_count, 19)

    def test_reconstruction_and_query_canonicality_validation(self):
        self.assertEqual(recover_record(b"\x01\x02", b"\x03\x01"), b"\x02\x03")
        with self.assertRaises(ValueError):
            answer_query(b"\xff", self.records[:3])  # unused high bits set
        with self.assertRaises(ValueError):
            answer_query(b"", self.records)
        with self.assertRaises(ValueError):
            create_queries(3, 3)

    def test_database_rows_must_be_equal_width_nonempty_bytes(self):
        with self.assertRaises(ValueError):
            answer_query(b"\x00", [b"a", b"bb"])
        with self.assertRaises(ValueError):
            answer_query(b"\x00", [b"", b""])

    def test_command_demo_is_marked_local_and_non_fhe(self):
        result = retrieve_for_demo(self.records, 0).to_dict()
        self.assertFalse(result["uses_fhe"])
        self.assertFalse(result["is_networked_demo"])
        self.assertIn("colluding", result["warning"])


if __name__ == "__main__":
    unittest.main()
