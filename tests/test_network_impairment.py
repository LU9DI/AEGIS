from __future__ import annotations

import asyncio
import time
import unittest

from anonlab.network_impairment import (
    DEFAULT_PROFILES,
    LinkImpairmentProfile,
    TcpImpairmentProxy,
)
from anonlab.network_impairment_benchmark import run_network_impairment_benchmark


class LinkImpairmentProfileTests(unittest.TestCase):
    def test_named_profiles_are_bounded_and_have_explicit_limitations(self) -> None:
        self.assertIn("metro", DEFAULT_PROFILES)
        self.assertIn("intercontinental", DEFAULT_PROFILES)
        self.assertEqual(DEFAULT_PROFILES["intercontinental"].latency_ms, 25.0)
        self.assertEqual(DEFAULT_PROFILES["intercontinental"].bandwidth_mbps, 50.0)

    def test_negative_latency_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "latency_ms"):
            LinkImpairmentProfile("invalid", latency_ms=-1)

    def test_non_finite_jitter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "jitter_ms"):
            LinkImpairmentProfile("invalid", jitter_ms=float("nan"))

    def test_invalid_bandwidth_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "bandwidth_mbps"):
            LinkImpairmentProfile("invalid", bandwidth_mbps=0)

    def test_chunk_and_queue_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "chunk_bytes"):
            LinkImpairmentProfile("invalid", chunk_bytes=65537)
        with self.assertRaisesRegex(ValueError, "queue_chunks"):
            LinkImpairmentProfile("invalid", queue_chunks=257)


class TcpImpairmentProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_rejects_non_loopback_endpoints(self) -> None:
        profile = DEFAULT_PROFILES["loopback"]
        with self.assertRaisesRegex(ValueError, "upstream_host"):
            TcpImpairmentProxy("192.0.2.1", 80, profile)
        with self.assertRaisesRegex(ValueError, "listen_host"):
            TcpImpairmentProxy("127.0.0.1", 80, profile, listen_host="0.0.0.0")

    async def test_proxy_forwards_bytes_and_preserves_half_close(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(2048)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
                if writer.can_write_eof():
                    writer.write_eof()
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        upstream_port = int(server.sockets[0].getsockname()[1])
        proxy = TcpImpairmentProxy(
            "127.0.0.1", upstream_port,
            LinkImpairmentProfile("test", latency_ms=1, jitter_ms=0, bandwidth_mbps=50, queue_chunks=2),
        )
        await proxy.start()
        payload = bytes(range(256)) * 16
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            await writer.drain()
            received = bytearray()
            while True:
                chunk = await reader.read(2048)
                if not chunk:
                    break
                received.extend(chunk)
            self.assertEqual(bytes(received), payload)
            for _ in range(100):
                if proxy.metrics.active_connections == 0:
                    break
                await asyncio.sleep(0.005)
            self.assertEqual(proxy.metrics.active_connections, 0)
            self.assertLessEqual(proxy.metrics.max_queue_chunks_observed, 2)
        finally:
            # The test client owns its StreamWriter; close it explicitly rather
            # than relying on proxy shutdown to tear down the client side.
            if "writer" in locals():
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
            await proxy.close()
            server.close()
            await server.wait_closed()


    async def test_bandwidth_cap_is_shared_across_connections(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(2048)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
                if writer.can_write_eof():
                    writer.write_eof()
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        upstream_port = int(server.sockets[0].getsockname()[1])
        proxy = TcpImpairmentProxy(
            "127.0.0.1", upstream_port,
            LinkImpairmentProfile("shared-rate", bandwidth_mbps=1.0, chunk_bytes=4096, queue_chunks=4),
        )
        await proxy.start()
        payloads = [b"A" * 4096, b"B" * 4096]

        async def exchange(payload: bytes) -> bytes:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            try:
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                await writer.drain()
                output = bytearray()
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    output.extend(data)
                return bytes(output)
            finally:
                writer.close()
                await writer.wait_closed()

        try:
            started = time.perf_counter()
            results = await asyncio.gather(*(exchange(payload) for payload in payloads))
            elapsed_s = time.perf_counter() - started
            self.assertEqual(results, payloads)
            # Aggregate 8 KiB must traverse the 1 Mbps proxy in both directions.
            # Keep a wide margin below the ~131 ms serialization lower bound.
            self.assertGreaterEqual(elapsed_s, 0.09)
            self.assertLessEqual(proxy.metrics.max_queue_chunks_observed, 4)
        finally:
            await proxy.close()
            server.close()
            await server.wait_closed()


    async def test_proxy_rejects_connections_above_admission_limit(self) -> None:
        never_read_event = asyncio.Event()

        async def idle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await never_read_event.wait()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(idle, "127.0.0.1", 0)
        upstream_port = int(server.sockets[0].getsockname()[1])
        proxy = TcpImpairmentProxy(
            "127.0.0.1", upstream_port, DEFAULT_PROFILES["loopback"], max_connections=1
        )
        await proxy.start()
        first_writer = second_writer = None
        try:
            _, first_writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            for _ in range(100):
                if proxy.metrics.active_connections == 1:
                    break
                await asyncio.sleep(0.002)
            second_reader, second_writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            await asyncio.wait_for(second_reader.read(), timeout=1)
            self.assertEqual(proxy.metrics.active_connections, 1)
            self.assertEqual(proxy.metrics.rejected_connections, 1)
        finally:
            never_read_event.set()
            if first_writer is not None:
                first_writer.close()
                await first_writer.wait_closed()
            if second_writer is not None:
                second_writer.close()
                await second_writer.wait_closed()
            await proxy.close()
            server.close()
            await server.wait_closed()

    async def test_proxy_applies_nonzero_one_way_delay(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                data = await reader.read(4096)
                if data:
                    writer.write(data)
                    await writer.drain()
                # Drain to EOF to keep this handler's half-close behavior explicit.
                while await reader.read(4096):
                    pass
                if writer.can_write_eof():
                    writer.write_eof()
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        upstream_port = int(server.sockets[0].getsockname()[1])
        proxy = TcpImpairmentProxy(
            "127.0.0.1", upstream_port,
            LinkImpairmentProfile("delay-test", latency_ms=5, jitter_ms=0, queue_chunks=4),
        )
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.listen_port)
            started = time.perf_counter()
            writer.write(b"latency check")
            await writer.drain()
            writer.write_eof()
            await writer.drain()
            result = await asyncio.wait_for(reader.read(), timeout=1)
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.assertEqual(result, b"latency check")
            # Two shaped directions each add 5 ms. Keep a wide margin for loaded CI hosts.
            self.assertGreaterEqual(elapsed_ms, 7.0)
            writer.close()
            await writer.wait_closed()
            for _ in range(100):
                if proxy.metrics.active_connections == 0:
                    break
                await asyncio.sleep(0.005)
            self.assertEqual(proxy.metrics.active_connections, 0)
        finally:
            await proxy.close()
            server.close()
            await server.wait_closed()


class NetworkImpairmentBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_benchmark_reports_shaping_metadata_and_cleans_up(self) -> None:
        result = await run_network_impairment_benchmark(
            profile=LinkImpairmentProfile("test-profile", latency_ms=0.1, jitter_ms=0.0, bandwidth_mbps=100),
            stream_count=1,
            payload_bytes=2048,
            seed=12345,
        )
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertTrue(result["results"]["relay_observability_check"])
        self.assertTrue(result["results"]["all_relay_connections_closed"])
        self.assertEqual(result["results"]["active_proxy_connections_after_close"], [0, 0, 0, 0])
        self.assertEqual(result["results"]["proxy_rejected_connections"], 0)
        self.assertEqual(result["config"]["max_proxy_connections_per_shaper"], 64)
        self.assertFalse(result["metadata"]["is_real_wan_measurement"])
        self.assertFalse(result["metadata"]["is_packet_loss_simulation"])
        self.assertEqual(len(result["results"]["circuit_per_stream"]), 1)
        self.assertEqual(len(result["results"]["direct_per_stream"]), 1)
        self.assertEqual(result["results"]["circuit_per_stream"][0]["bytes_returned"], 2048)
        self.assertGreaterEqual(result["results"]["circuit_completion_rate_jain_index"], 1.0)
        self.assertLessEqual(result["results"]["circuit_completion_rate_jain_index"], 1.0)
        self.assertLessEqual(
            result["results"]["max_shaper_queue_chunks_observed"],
            result["results"]["shaper_queue_chunks_configured"],
        )

    async def test_sparse_stream_remains_live_under_intercontinental_profile(self) -> None:
        result = await run_network_impairment_benchmark(
            profile=DEFAULT_PROFILES["intercontinental"],
            stream_count=1,
            payload_bytes=2048,
            seed=54321,
            sparse_gap_ms=0.2,
            sparse_chunk_bytes=256,
        )
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertTrue(result["results"]["all_relay_connections_closed"])
        self.assertEqual(result["config"]["sparse_chunk_bytes"], 256)

    async def test_invalid_benchmark_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stream_count"):
            await run_network_impairment_benchmark(
                profile=DEFAULT_PROFILES["loopback"], stream_count=0, payload_bytes=2048
            )
        with self.assertRaisesRegex(ValueError, "sparse_gap_ms"):
            await run_network_impairment_benchmark(
                profile=DEFAULT_PROFILES["loopback"], stream_count=1, payload_bytes=2048, sparse_gap_ms=-1
            )


if __name__ == "__main__":
    unittest.main()
