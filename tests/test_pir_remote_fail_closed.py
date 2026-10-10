from __future__ import annotations

import ssl
import unittest

from anonlab.pir_rpc import PirRpcEndpoint, PirRpcProtocolError, retrieve_two_server_pir_rpc, retrieve_four_server_pir_rpc_checked


class RemotePirFailClosedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.endpoints = tuple(
            PirRpcEndpoint(f"remote-{i}", host, 443, ssl_context=context, server_hostname="pir.example.invalid")
            for i, host in enumerate(("192.0.2.1", "192.0.2.2", "192.0.2.3", "192.0.2.4"))
        )

    async def test_two_server_remote_pir_is_rejected_by_default_before_network_io(self):
        with self.assertRaisesRegex(PirRpcProtocolError, "remote PIR computation is disabled"):
            await retrieve_two_server_pir_rpc(self.endpoints[:2], 8, 3, record_bytes=16)

    async def test_four_server_remote_pir_is_rejected_by_default_before_network_io(self):
        with self.assertRaisesRegex(PirRpcProtocolError, "not cryptographically verifiable"):
            await retrieve_four_server_pir_rpc_checked(self.endpoints, 8, 3, record_bytes=16)

    async def test_explicit_unverified_override_cannot_enable_remote_queries(self):
        with self.assertRaisesRegex(PirRpcProtocolError, "no unverified-remote override"):
            await retrieve_two_server_pir_rpc(
                self.endpoints[:2], 8, 3, record_bytes=16, allow_unverified_remote=True
            )

    async def test_dns_hostname_is_never_classified_as_loopback(self):
        from anonlab.pir_rpc import _is_loopback_host

        self.assertFalse(_is_loopback_host("pir.example.invalid"))
        self.assertFalse(_is_loopback_host("localhost"))
        self.assertTrue(_is_loopback_host("127.0.0.1"))

    async def test_endpoint_rejects_dns_hostname_before_network_io(self):
        with self.assertRaisesRegex(ValueError, "numeric IP address"):
            PirRpcEndpoint(
                "dns-a", "pir-a.example.invalid", 443,
                ssl_context=self.endpoints[0].ssl_context,
                server_hostname="pir-a.example.invalid",
            )

    async def test_remote_research_mode_must_be_explicitly_boolean(self):
        with self.assertRaisesRegex(ValueError, "must be a bool"):
            await retrieve_two_server_pir_rpc(self.endpoints[:2], 8, 3, record_bytes=16, allow_unverified_remote=1)


if __name__ == "__main__":
    unittest.main()
