from __future__ import annotations

import unittest

from anonlab.route_selection import (
    Endpoint,
    RelayCandidate,
    RoutePolicy,
    demo_topology,
    geometric_rtt_floor_ms,
    plan_from_json,
    select_route,
)


def relay(relay_id, roles, *, asn=None, family=None, subnet=None, country="BR", lat=-23.55, lon=-46.63, bw=100, confirmed=False, running=True, load=0.0):
    return RelayCandidate(
        relay_id=relay_id,
        roles=frozenset(roles),
        latitude=lat,
        longitude=lon,
        bandwidth_mbps=bw,
        asn_group=asn or f"asn-{relay_id}",
        family_id=family or f"family-{relay_id}",
        subnet_group=subnet or f"subnet-{relay_id}",
        country_code=country,
        utilization=load,
        confirmed_guard=confirmed,
        running=running,
    )


class RouteSelectionTests(unittest.TestCase):
    def setUp(self):
        self.client = Endpoint("client", -23.55, -46.63)
        self.destination = Endpoint("target", -23.56, -46.64)
        self.guard = relay("g", {"guard"}, confirmed=True)
        self.mid_fast = relay("m-fast", {"middle"}, asn="asn-mid1", lat=-23.56, lon=-46.64, load=0.0)
        self.mid_slow = relay("m-slow", {"middle"}, asn="asn-mid2", lat=50.0, lon=8.0)
        self.exit_fast = relay("e-fast", {"exit"}, asn="asn-exit1", lat=-23.55, lon=-46.64)
        self.exit_far = relay("e-far", {"exit"}, asn="asn-exit2", country="US", lat=40.7, lon=-74.0)
        self.policy = RoutePolicy(pinned_guard_id="g")

    def test_demo_topology_produces_synthetic_route_without_coords_in_output(self):
        result = plan_from_json(demo_topology()).to_dict()
        self.assertEqual(len(result["relays"]), 3)
        self.assertEqual(result["relays"][0], "guard-pinned-sp")
        self.assertFalse(result["uses_zero_knowledge_proofs"])
        self.assertFalse(result["is_live_network_test"])
        serialized = str(result)
        self.assertNotIn("latitude", serialized)
        self.assertNotIn("longitude", serialized)

    def test_select_prefers_measured_fast_path_but_obeys_diversity(self):
        candidates = [self.guard, self.mid_fast, self.mid_slow, self.exit_fast, self.exit_far]
        links = {
            ("client", "g"): 2.0,
            ("g", "m-fast"): 2.0,
            ("m-fast", "e-fast"): 2.0,
            ("e-fast", "target"): 2.0,
            ("g", "m-slow"): 70.0,
            ("m-slow", "e-fast"): 75.0,
            ("m-fast", "e-far"): 130.0,
            ("e-far", "target"): 120.0,
        }
        plan = select_route(candidates=candidates, client=self.client, destination=self.destination, link_rtts_ms=links, policy=self.policy)
        self.assertEqual(plan.relay_ids, ("g", "m-fast", "e-fast"))
        self.assertEqual(plan.measured_link_count, 4)
        self.assertEqual(plan.estimated_link_count, 0)

    def test_pinned_guard_is_not_silently_rotated(self):
        with self.assertRaisesRegex(ValueError, "pinned confirmed guard"):
            select_route(candidates=[self.mid_fast, self.exit_fast], client=self.client, destination=self.destination, link_rtts_ms={}, policy=self.policy)
        unconfirmed = relay("g", {"guard"}, confirmed=False)
        with self.assertRaisesRegex(ValueError, "pinned confirmed guard"):
            select_route(candidates=[unconfirmed, self.mid_fast, self.exit_fast], client=self.client, destination=self.destination, link_rtts_ms={}, policy=self.policy)

    def test_duplicate_asn_family_or_subnet_paths_are_excluded(self):
        same_asn_exit = relay("e-same-asn", {"exit"}, asn=self.guard.asn_group)
        with self.assertRaisesRegex(ValueError, "no route satisfies"):
            select_route(candidates=[self.guard, self.mid_fast, same_asn_exit], client=self.client, destination=self.destination, link_rtts_ms={}, policy=self.policy)
        same_subnet_mid = relay("m-same-subnet", {"middle"}, subnet=self.guard.subnet_group)
        with self.assertRaisesRegex(ValueError, "no route satisfies"):
            select_route(candidates=[self.guard, same_subnet_mid, self.exit_fast], client=self.client, destination=self.destination, link_rtts_ms={}, policy=self.policy)

    def test_geometric_floor_is_nonnegative_and_symmetric(self):
        far = relay("far", {"middle"}, lat=40.7, lon=-74.0)
        self.assertGreater(geometric_rtt_floor_ms(self.guard, far), 0)
        self.assertAlmostEqual(geometric_rtt_floor_ms(self.guard, far), geometric_rtt_floor_ms(far, self.guard), places=10)

    def test_invalid_metrics_and_coordinate_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            Endpoint("bad", 91, 0)
        with self.assertRaises(ValueError):
            relay("bad", {"middle"}, bw=0)
        with self.assertRaises(ValueError):
            select_route(candidates=[self.guard, self.mid_fast, self.exit_fast], client=self.client, destination=self.destination, link_rtts_ms={("client", "g"): -1}, policy=self.policy)

    def test_unknown_links_are_marked_and_penalized(self):
        plan = select_route(candidates=[self.guard, self.mid_fast, self.exit_fast], client=self.client, destination=self.destination, link_rtts_ms={}, policy=self.policy)
        self.assertEqual(plan.estimated_link_count, 4)
        self.assertGreater(plan.estimated_rtt_ms, plan.geometric_rtt_floor_ms)


if __name__ == "__main__":
    unittest.main()
