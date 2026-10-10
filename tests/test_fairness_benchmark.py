from __future__ import annotations

import math
import unittest

from anonlab.fairness_benchmark import _parse_stream_counts, run_fairness_matrix
from anonlab.network_impairment_benchmark import _jain_index


class JainFairnessIndexTests(unittest.TestCase):
    def test_equal_rates_have_perfect_index(self) -> None:
        self.assertEqual(_jain_index([10.0, 10.0, 10.0, 10.0]), 1.0)

    def test_unequal_rates_lower_the_index(self) -> None:
        self.assertLess(_jain_index([1.0, 1.0, 1.0, 10.0]), 1.0)

    def test_zero_rates_are_defined(self) -> None:
        self.assertEqual(_jain_index([0.0, 0.0]), 1.0)
        self.assertEqual(_jain_index([]), 1.0)

    def test_nonfinite_and_negative_rates_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            _jain_index([1.0, math.nan])
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            _jain_index([1.0, -0.1])

    def test_cli_stream_count_parser_rejects_duplicates_and_bounds(self) -> None:
        self.assertEqual(_parse_stream_counts("1, 2,4"), [1, 2, 4])
        with self.assertRaises(Exception):
            _parse_stream_counts("1,1")
        with self.assertRaises(Exception):
            _parse_stream_counts("33")


class FairnessMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_matrix_reports_per_stream_and_cleanup_results(self) -> None:
        result = await run_fairness_matrix(
            profile_name="loopback",
            stream_counts=[1, 2],
            trials=1,
            payload_bytes=1024,
            seed=20261021,
        )
        self.assertTrue(result["metadata"]["is_loopback_only"])
        self.assertFalse(result["metadata"]["is_real_wan_measurement"])
        self.assertEqual(result["config"]["trial_order_by_trial"], [[1, 2]])
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual([row["stream_count"] for row in result["summary"]], [1, 2])
        for run in result["runs"]:
            self.assertTrue(run["integrity_verified"])
            self.assertTrue(run["relay_observability_check"])
            self.assertTrue(run["all_relay_connections_closed"])
            self.assertEqual(run["active_proxy_connections_after_close"], [0, 0, 0, 0])
            self.assertGreaterEqual(run["circuit_completion_rate_jain_index"], 1 / run["stream_count"] - 1e-9)
            self.assertLessEqual(run["circuit_completion_rate_jain_index"], 1.0 + 1e-9)

    async def test_invalid_matrix_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stream_counts"):
            await run_fairness_matrix(stream_counts=[1, 1], trials=1, payload_bytes=1024)
        with self.assertRaisesRegex(ValueError, "trials"):
            await run_fairness_matrix(stream_counts=[1], trials=0, payload_bytes=1024)
        with self.assertRaisesRegex(ValueError, "payload_bytes"):
            await run_fairness_matrix(stream_counts=[1], trials=1, payload_bytes=1)
