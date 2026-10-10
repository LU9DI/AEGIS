from __future__ import annotations

import asyncio
import unittest

from anonlab.local_benchmark import run_local_benchmark


class LocalRelayBenchmarkTests(unittest.TestCase):
    def test_three_hop_loopback_chain_forwards_bytes_and_reports_limitations(self) -> None:
        result = asyncio.run(
            run_local_benchmark(
                hop_count=3,
                payload_bytes=128_000,
                trials=1,
                latency_samples=3,
                seed=123,
            )
        )
        self.assertEqual(result["topology"]["relay_count"], 3)
        self.assertFalse(result["is_anonymity_test"])
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertGreater(result["results"]["rtt_p50_ms"], 0)
        self.assertGreater(result["results"]["echo_goodput_mbps_median"], 0)
        self.assertEqual(len(result["results"]["transfer_trials"]), 1)
        self.assertTrue(any("plaintext" in item for item in result["limitations"]))

    def test_invalid_hop_count_rejected(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(run_local_benchmark(hop_count=0, payload_bytes=4096, trials=1, latency_samples=3))


if __name__ == "__main__":
    unittest.main()
