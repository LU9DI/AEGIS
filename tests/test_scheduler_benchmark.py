from __future__ import annotations

import unittest

from anonlab.scheduler_benchmark import _parse_stream_counts, run_scheduler_comparison


class SchedulerBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_ab_benchmark_reports_both_modes_and_cleanup(self) -> None:
        result = await run_scheduler_comparison(
            profile_name="loopback",
            stream_counts=[2],
            trials=1,
            payload_bytes=2048,
            write_chunk_bytes=512,
            pipeline_depth=4,
            seed=20261022,
        )
        self.assertTrue(result["metadata"]["is_loopback_only"])
        self.assertFalse(result["metadata"]["is_real_wan_measurement"])
        self.assertEqual(len(result["runs"]), 2)
        modes = {run["scheduler"] for run in result["runs"]}
        self.assertEqual(modes, {"baseline", "round_robin"})
        self.assertTrue(all(run["integrity_verified"] for run in result["runs"]))
        self.assertTrue(all(run["relay_observability_check"] for run in result["runs"]))
        self.assertTrue(all(run["all_relay_connections_closed"] for run in result["runs"]))
        self.assertTrue(all(row["by_scheduler"][mode]["all_checks_passed"] for row in result["summary"] for mode in modes))

    async def test_invalid_ab_benchmark_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stream_counts"):
            await run_scheduler_comparison(stream_counts=[2, 2], trials=1)
        with self.assertRaisesRegex(ValueError, "pipeline_depth"):
            await run_scheduler_comparison(stream_counts=[2], trials=1, pipeline_depth=5)
        with self.assertRaisesRegex(ValueError, "payload_bytes"):
            await run_scheduler_comparison(stream_counts=[2], trials=1, payload_bytes=3)

    async def test_cli_parser_rejects_duplicates(self) -> None:
        self.assertEqual(_parse_stream_counts("2, 4,8"), [2, 4, 8])
        with self.assertRaises(Exception):
            _parse_stream_counts("2,2")
