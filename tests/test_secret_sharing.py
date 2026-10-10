from __future__ import annotations

import unittest

from anonlab.secret_sharing import SecretShare, reconstruct_payload, run_demo, split_payload


class SecretSharingTests(unittest.TestCase):
    def test_payload_reconstructs_for_empty_partial_and_multichunk_values(self):
        cases = [b"", b"a", b"abcd", b"abcde", bytes(range(251)) * 7]
        for payload in cases:
            with self.subTest(length=len(payload)):
                a, b, manifest = split_payload(payload, chunk_size=17)
                self.assertEqual(reconstruct_payload(a, b, manifest), payload)
                self.assertTrue(run_demo(payload, chunk_size=17).integrity_verified)

    def test_share_chunks_are_fixed_width_and_manifest_stays_local(self):
        payload = b"sensitive-looking-sample" * 4
        a, b, manifest = split_payload(payload, chunk_size=16, random_bytes=lambda n: bytes((i * 19 + 3) % 256 for i in range(n)))
        self.assertEqual(len(a.chunks), len(b.chunks))
        self.assertTrue(all(len(chunk) == 16 for chunk in a.chunks + b.chunks))
        self.assertEqual(a.padded_bytes, b.padded_bytes)
        self.assertEqual(manifest.original_length, len(payload))

    def test_corrupt_share_fails_integrity_check(self):
        a, b, manifest = split_payload(b"not safe to return if corrupted", chunk_size=8)
        altered = bytearray(b.chunks[0])
        altered[0] ^= 1
        damaged = SecretShare((bytes(altered),) + b.chunks[1:], b.chunk_size)
        with self.assertRaisesRegex(ValueError, "integrity check"):
            reconstruct_payload(a, damaged, manifest)

    def test_invalid_inputs_and_mismatched_share_shapes_fail_closed(self):
        with self.assertRaises(ValueError):
            split_payload("not bytes")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            split_payload(b"payload", chunk_size=0)
        a, b, manifest = split_payload(b"payload", chunk_size=4)
        with self.assertRaises(ValueError):
            reconstruct_payload(a, SecretShare((), b.chunk_size), manifest)

    def test_demo_only_reports_integrity_and_coarse_size(self):
        result = run_demo(b"payload" * 13, chunk_size=16).to_dict()
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["is_networked_demo"])
        self.assertIn("global observer", result["warning"])
        self.assertNotIn("payload", result)


if __name__ == "__main__":
    unittest.main()
