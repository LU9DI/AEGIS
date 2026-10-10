from __future__ import annotations

import os
import unittest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from anonlab.mixed_workload_benchmark import (
    run_mixed_scheduler_comparison,
    run_mixed_workload_benchmark,
)
from anonlab.network_impairment import DEFAULT_PROFILES
from anonlab.telescoping import RelayNode


class MixedWorkloadBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_workload_preserves_data_and_cleans_up(self) -> None:
        result = await run_mixed_workload_benchmark(
            profile=DEFAULT_PROFILES["loopback"],
            bulk_bytes=32 * 1024,
            interactive_requests=3,
            request_bytes=64,
            request_gap_ms=1,
            stagger_after_ms=2,
            write_chunk_bytes=4096,
            pipeline_depth=2,
            seed=20261023,
        )
        measured = result["results"]
        self.assertTrue(result["metadata"]["loopback_only"])
        self.assertFalse(result["metadata"]["real_wan_measurement"])
        self.assertTrue(measured["integrity_verified"])
        self.assertTrue(measured["bulk"]["integrity_verified"])
        self.assertTrue(measured["early_interactive"]["integrity_verified"])
        self.assertTrue(measured["staggered_interactive"]["integrity_verified"])
        self.assertGreaterEqual(measured["early_interactive"]["request_rtt_p50_ms"], 0)
        self.assertGreaterEqual(measured["staggered_interactive"]["request_rtt_p95_ms"], 0)
        self.assertTrue(measured["relay_observability_check"])
        self.assertTrue(measured["resources_closed"])
        self.assertEqual(measured["active_proxy_connections_after_close"], [0, 0, 0, 0])
        diagnostics = measured["write_diagnostics"]
        self.assertTrue(diagnostics["enabled"])
        self.assertGreater(diagnostics["event_count"], 0)
        self.assertIn("write_batch", diagnostics["summary_by_event"])
        self.assertTrue(all("payload" not in event for event in diagnostics["events"]))
        relay_diagnostics = measured["relay_stage_diagnostics"]
        self.assertEqual([row["hop"] for row in relay_diagnostics], [1, 2, 3])
        self.assertTrue(all(row["enabled"] for row in relay_diagnostics))
        self.assertGreater(relay_diagnostics[0]["summary_by_stage"]["downstream_response_wait"]["samples"], 0)
        self.assertGreater(relay_diagnostics[1]["summary_by_stage"]["downstream_response_wait"]["samples"], 0)
        self.assertIn("destination_read_wait", relay_diagnostics[2]["summary_by_stage"])
        self.assertIn("flow_credit_wait", relay_diagnostics[2]["summary_by_stage"])
        flow_pause_summary = relay_diagnostics[2]["flow_control_pause_summary"]
        self.assertEqual(flow_pause_summary["threshold_ms"], 1.0)
        self.assertGreaterEqual(flow_pause_summary["pauses_over_threshold"], 0)
        self.assertGreater(relay_diagnostics[2]["command_counts"].get("write", 0), 0)
        for hop in relay_diagnostics:
            self.assertTrue(all(set(event) <= {"stage", "operation", "elapsed_ms"} for event in hop["events"]))
            self.assertTrue(all("payload" not in event for event in hop["events"]))
            self.assertEqual(hop["dropped_events"], 0)

    def test_relay_metrics_are_disabled_by_default(self) -> None:
        node = RelayNode(os.urandom(20), X25519PrivateKey.generate())
        snapshot = node.relay_metrics_snapshot()
        self.assertFalse(snapshot["enabled"])
        self.assertEqual(snapshot["event_count"], 0)
        self.assertEqual(snapshot["summary_by_stage"], {})
        with self.assertRaisesRegex(ValueError, "collect_relay_metrics"):
            RelayNode(os.urandom(20), X25519PrivateKey.generate(), collect_relay_metrics=1)

    async def test_mixed_workload_comparison_includes_both_schedulers(self) -> None:
        result = await run_mixed_scheduler_comparison(
            profile_name="loopback",
            trials=1,
            bulk_bytes=16 * 1024,
            interactive_requests=2,
            request_bytes=64,
            request_gap_ms=0,
            stagger_after_ms=0,
            write_chunk_bytes=4096,
            pipeline_depth=2,
            seed=23,
        )
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual({row["scheduler"] for row in result["runs"]}, {"baseline", "round_robin"})
        self.assertTrue(result["all_integrity_and_cleanup_checks_passed"])
        self.assertEqual(len(result["summary"]), 11)
        for row in result["runs"]:
            self.assertTrue(row["write_diagnostics"]["enabled"])
            if row["scheduler"] == "round_robin":
                self.assertIn("dispatch_round", row["write_diagnostics"]["summary_by_event"])

    async def test_invalid_mixed_workload_bounds_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "bulk_bytes"):
            await run_mixed_workload_benchmark(profile=DEFAULT_PROFILES["loopback"], bulk_bytes=10)
        with self.assertRaisesRegex(ValueError, "request_bytes"):
            await run_mixed_workload_benchmark(profile=DEFAULT_PROFILES["loopback"], request_bytes=2)
        with self.assertRaisesRegex(ValueError, "trials"):
            await run_mixed_scheduler_comparison(profile_name="loopback", trials=0)
