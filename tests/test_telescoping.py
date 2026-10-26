from __future__ import annotations

import asyncio
import contextlib
import os
import unittest

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from anonlab.telescoping import (
        RelayDescriptor,
        RelayNode,
        STREAM_WRITE_MAX_BYTES,
        STREAM_CHUNK_BYTES,
        MAX_STREAM_WINDOW_BYTES,
        WINDOW_UPDATE_BATCH_BYTES,
        WINDOW_UPDATE_MAX_DELAY_SECONDS,
        TelescopingClient,
        _encode_window_update_body,
        serve_node,
        frame,
        read_frame,
        _aad,
        _encode_extension,
        _open_reply,
        _decode_link_response,
        REQUEST_AAD_PREFIX,
        MAX_COMMANDS_PER_CIRCUIT,
        MAX_FRAME_BYTES,
        LINK_AUTH,
        LINK_SERVER_DOMAIN,
        _link_hello,
    )
    from anonlab.ntor_experiment import client_finish, client_start
    from anonlab.onion_protocol import seal
    from anonlab.telescoping_benchmark import run_telescoping_benchmark
    from anonlab.concurrency_benchmark import run_concurrency_benchmark
    from anonlab.multiplex_benchmark import run_stream_multiplex_benchmark
    from anonlab.duplex_benchmark import run_duplex_benchmark
    from anonlab.write_batch_benchmark import run_write_batch_benchmark
    from anonlab.pipeline_benchmark import run_pipeline_benchmark
except (ImportError, RuntimeError):  # optional research dependency
    X25519PrivateKey = None  # type: ignore[assignment,misc]


def raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


@unittest.skipIf(X25519PrivateKey is None, "install aegis-anon-lab[onion-lab] for telescoping tests")
class TelescopingCircuitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.nodes: list[RelayNode] = []
        self.servers: list[asyncio.AbstractServer] = []
        for _ in range(3):
            node = RelayNode(os.urandom(20), X25519PrivateKey.generate())
            server = await serve_node(node)
            self.nodes.append(node)
            self.servers.append(server)
        self.descriptors = [node.descriptor for node in self.nodes]
        self.client = TelescopingClient()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()

    async def test_descriptor_rejects_identity_public_key_digest_mismatch(self) -> None:
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        with self.assertRaisesRegex(ValueError, "does not match identity public key"):
            RelayDescriptor(
                "127.0.0.1", 12345, os.urandom(20),
                raw_public(X25519PrivateKey.generate()), public,
            )

    async def test_guard_rejects_server_signature_from_wrong_identity(self) -> None:
        expected_identity = Ed25519PrivateKey.generate()
        expected_public = expected_identity.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        expected_digest = __import__("hashlib").sha256(
            b"MALEBOLGE/relay-identity/v1\x00" + expected_public
        ).digest()[:20]
        expected_onion = X25519PrivateKey.generate()
        rogue_identity = Ed25519PrivateKey.generate()
        got_create = asyncio.Event()

        async def rogue(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                hello = await read_frame(reader)
                target_id = hello[2:22]
                rogue_signature = rogue_identity.sign(
                    LINK_SERVER_DOMAIN + hello + target_id
                )
                writer.write(frame(LINK_AUTH + rogue_signature))
                await writer.drain()
                try:
                    request = await asyncio.wait_for(read_frame(reader), timeout=0.1)
                    if request.startswith(b"C"):
                        got_create.set()
                except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
                    pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(rogue, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        descriptor = RelayDescriptor(
            "127.0.0.1", port, expected_digest,
            raw_public(expected_onion), expected_public,
        )
        try:
            with self.assertRaisesRegex(ValueError, "identity authentication failed"):
                await self.client.connect_guard(descriptor)
            await asyncio.sleep(0.15)
            self.assertFalse(got_create.is_set(), "CREATE must not be sent before server identity authentication")
            self.assertEqual(self.client.hops, [])
        finally:
            server.close()
            await server.wait_closed()

    async def test_relay_rejects_invalid_initiating_identity_signature(self) -> None:
        target_identity = Ed25519PrivateKey.generate()
        target_public = target_identity.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        target_digest = __import__("hashlib").sha256(
            b"MALEBOLGE/relay-identity/v1\x00" + target_public
        ).digest()[:20]
        target = RelayNode(
            target_digest, X25519PrivateKey.generate(),
            identity_private_key=target_identity,
        )
        server = await serve_node(target)
        peer_identity = Ed25519PrivateKey.generate()
        hello = bytearray(_link_hello(
            target.descriptor,
            initiator_identity_private_key=peer_identity,
            nonce=b"S" * 32,
        ))
        hello[-1] ^= 0x01
        try:
            reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
            writer.write(frame(bytes(hello)))
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader), timeout=1)
            writer.close()
            await writer.wait_closed()
            self.assertEqual(len(target.link_replay_guard._seen), 0)
        finally:
            server.close()
            await server.wait_closed()

    async def test_relay_to_relay_link_requires_and_rejects_replayed_nonce(self) -> None:
        target_identity = Ed25519PrivateKey.generate()
        target_public = target_identity.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        target_digest = __import__("hashlib").sha256(
            b"MALEBOLGE/relay-identity/v1\x00" + target_public
        ).digest()[:20]
        target = RelayNode(
            target_digest, X25519PrivateKey.generate(),
            identity_private_key=target_identity,
        )
        server = await serve_node(target)
        peer_identity = Ed25519PrivateKey.generate()
        hello = _link_hello(
            target.descriptor,
            initiator_identity_private_key=peer_identity,
            nonce=b"R" * 32,
        )
        try:
            reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
            writer.write(frame(hello))
            await writer.drain()
            reply = await read_frame(reader)
            self.assertTrue(reply.startswith(LINK_AUTH))
            writer.close()
            await writer.wait_closed()

            reader2, writer2 = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
            writer2.write(frame(hello))
            await writer2.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader2), timeout=1)
            writer2.close()
            await writer2.wait_closed()
            self.assertEqual(len(target.link_replay_guard._seen), 1)
        finally:
            server.close()
            await server.wait_closed()

    async def test_three_hop_circuit_is_extended_through_existing_guard(self) -> None:
        await self.client.connect_guard(self.descriptors[0])
        await self.client.extend(self.descriptors[1])
        await self.client.extend(self.descriptors[2])

        self.assertEqual(len(self.client.hops), 3)
        self.assertEqual(self.client.direct_connections_opened, 1)
        request_keys = [hop.keys.request_key for hop in self.client.hops]
        response_keys = [hop.keys.response_key for hop in self.client.hops]
        self.assertEqual(len(set(request_keys)), 3)
        self.assertEqual(len(set(response_keys)), 3)
        self.assertTrue(all(a != b for a, b in zip(request_keys, response_keys)))

    async def test_entry_observes_only_immediate_extension_then_opaque_forward(self) -> None:
        await self.client.connect_guard(self.descriptors[0])
        await self.client.extend(self.descriptors[1])
        await self.client.extend(self.descriptors[2])

        entry_events = self.nodes[0].observations
        middle_events = self.nodes[1].observations
        self.assertEqual(
            [(event.operation, event.target_port) for event in entry_events],
            [("extend", self.descriptors[1].port), ("forward", None)],
        )
        self.assertEqual(
            [(event.operation, event.target_port) for event in middle_events],
            [("extend", self.descriptors[2].port)],
        )
        # The guard's parsed observation ledger never contains the exit endpoint.
        self.assertNotIn(self.descriptors[2].port, [e.target_port for e in entry_events])
        self.assertEqual(self.nodes[2].observations, [])


    async def test_three_hop_data_round_trip_and_multirequest_sequence(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    payload = await read_frame(reader)
                    writer.write(frame(payload))
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, ValueError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", echo_port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            payloads = [b"MALEBOLGE echo check", bytes(range(256)) * 512]
            for payload in payloads:
                response = await self.client.request_echo("127.0.0.1", echo_port, payload)
                self.assertEqual(response, payload)
            self.assertEqual(self.client.direct_connections_opened, 1)
            self.assertEqual(
                [(event.operation, event.target_port) for event in self.nodes[0].observations],
                [("extend", self.descriptors[1].port), ("forward", None), ("forward", None), ("forward", None)],
            )
            self.assertEqual(
                [(event.operation, event.target_port) for event in self.nodes[1].observations],
                [("extend", self.descriptors[2].port), ("forward", None), ("forward", None)],
            )
            self.assertEqual(
                [(event.operation, event.target_port) for event in self.nodes[2].observations],
                [("data", echo_port), ("data", echo_port)],
            )
            # Only the exit parses the application's destination endpoint.
            self.assertNotIn(echo_port, [event.target_port for event in self.nodes[0].observations])
            self.assertNotIn(echo_port, [event.target_port for event in self.nodes[1].observations])
        finally:
            echo_server.close()
            await echo_server.wait_closed()

    async def test_client_rejects_duplicate_hop_before_network_write(self) -> None:
        await self.client.connect_guard(self.descriptors[0])
        await self.client.extend(self.descriptors[1])
        before = len(self.nodes[0].observations)
        with self.assertRaisesRegex(ValueError, "already exists"):
            await self.client.extend(self.descriptors[0])
        self.assertEqual(len(self.nodes[0].observations), before)
        self.assertEqual(self.client.direct_connections_opened, 1)

    async def test_replayed_extension_frame_is_rejected(self) -> None:
        await self.client.connect_guard(self.descriptors[0])
        guard_hop = self.client.hops[0]
        state, handshake = client_start(
            self.descriptors[1].identity_digest,
            self.descriptors[1].onion_public_key,
        )
        command = _encode_extension(0, self.descriptors[1], handshake)
        captured_frame = frame(seal(
            guard_hop.keys.request_key,
            command,
            _aad(REQUEST_AAD_PREFIX, guard_hop.descriptor.relay_id),
        ))
        assert self.client._writer is not None and self.client._reader is not None
        # Stop the normal response dispatcher for this deliberately low-level replay test.
        if self.client._reader_task is not None:
            self.client._reader_task.cancel()
            await asyncio.gather(self.client._reader_task, return_exceptions=True)
            self.client._reader_task = None
        self.client._writer.write(captured_frame)
        await self.client._writer.drain()
        reply_wire = await asyncio.wait_for(read_frame(self.client._reader), timeout=2)
        reply_sequence, reply_stream_id, reply_envelope = _decode_link_response(reply_wire)
        self.assertEqual((reply_sequence, reply_stream_id), (0, 0))
        raw_relay_reply = _open_reply(
            guard_hop.keys.response_key,
            guard_hop.descriptor.relay_id,
            0,
            reply_envelope,
            0,
        )
        keys = client_finish(state, raw_relay_reply)
        self.assertEqual(len(keys.request_key), 32)

        # Replay the byte-identical captured command after the relay advanced to sequence 1.
        self.client._writer.write(captured_frame)
        await self.client._writer.drain()
        closed = await asyncio.wait_for(self.client._reader.read(1), timeout=2)
        self.assertEqual(closed, b"")
        self.assertEqual(
            [(event.operation, event.target_port) for event in self.nodes[0].observations],
            [("extend", self.descriptors[1].port)],
        )

    async def test_benchmark_smoke_reports_single_entry_connection_and_route_check(self) -> None:
        result = await run_telescoping_benchmark(payload_bytes=4096, trials=2, seed=7)
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertTrue(result["results"]["route_knowledge_separation_check"])
        self.assertEqual(result["results"]["direct_connections_from_client_per_circuit"], [1, 1])
        self.assertGreater(result["results"]["telescoping_echo_rtt_ms_p50"], 0)
        self.assertGreater(result["results"]["direct_echo_rtt_ms_p50"], 0)
        self.assertFalse(result["metadata"]["is_production_security_test"])


    async def test_two_concurrent_clients_keep_circuit_state_separate(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    payload = await read_frame(reader)
                    writer.write(frame(payload))
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, ValueError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", echo_port))
        clients = [TelescopingClient(), TelescopingClient()]
        payloads = [os.urandom(32_768), os.urandom(65_536)]
        try:
            async def build(client: TelescopingClient) -> None:
                await client.connect_guard(self.descriptors[0])
                await client.extend(self.descriptors[1])
                await client.extend(self.descriptors[2])

            await asyncio.gather(*(build(client) for client in clients))
            responses = await asyncio.gather(*(
                client.request_echo("127.0.0.1", echo_port, payload)
                for client, payload in zip(clients, payloads, strict=True)
            ))
            self.assertEqual(responses, payloads)
            self.assertEqual([client.direct_connections_opened for client in clients], [1, 1])
            self.assertNotIn(echo_port, [event.target_port for event in self.nodes[0].observations])
            self.assertNotIn(echo_port, [event.target_port for event in self.nodes[1].observations])
            self.assertEqual(
                sum(event.operation == "data" for event in self.nodes[2].observations), 2
            )
        finally:
            for client in clients:
                await client.close()
            echo_server.close()
            await echo_server.wait_closed()
        for _ in range(50):
            if all(node.active_connections == 0 for node in self.nodes):
                break
            await asyncio.sleep(0.01)
        self.assertEqual([node.active_connections for node in self.nodes], [0, 0, 0])


    async def test_same_circuit_multiplexes_out_of_order_stream_responses(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                payload = await read_frame(reader)
                # Make completion order differ from submission order.
                await asyncio.sleep((12 - payload[0]) * 0.008)
                writer.write(frame(payload))
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, ValueError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", echo_port))
        payloads = [bytes([index]) + os.urandom(1023 + index) for index in range(1, 13)]
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            streams = await asyncio.gather(*(
                self.client.start_echo("127.0.0.1", echo_port, payload) for payload in payloads
            ))
            for hop in self.client.hops:
                ids = [stream.hop_stream_ids[hop.descriptor.relay_id] for stream in streams]
                self.assertEqual(len(ids), len(set(ids)))
            responses = await asyncio.gather(*(stream.result() for stream in streams))
            self.assertEqual(responses, payloads)
            self.assertEqual(self.client.direct_connections_opened, 1)
            self.assertEqual(sum(e.operation == "data" for e in self.nodes[2].observations), len(payloads))
            self.assertEqual(self.client._active_streams, {})
        finally:
            await self.client.close()
            echo_server.close()
            await echo_server.wait_closed()

    async def test_cancelling_one_stream_does_not_close_other_streams_or_circuit(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                payload = await read_frame(reader)
                if payload != b"quick":
                    await asyncio.sleep(1.0)
                writer.write(frame(payload))
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, ValueError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", echo_port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            slow = await self.client.start_echo("127.0.0.1", echo_port, b"slow")
            quick = await self.client.start_echo("127.0.0.1", echo_port, b"quick")
            self.assertEqual(await quick.result(), b"quick")
            cancelled = await slow.cancel()
            self.assertTrue(cancelled)
            with self.assertRaises(asyncio.CancelledError):
                await slow.result()
            # The cancellation consumes valid sequence numbers but should leave
            # the circuit usable for a subsequent independent stream.
            self.assertEqual(await self.client.request_echo("127.0.0.1", echo_port, b"quick"), b"quick")
            self.assertEqual(self.client.direct_connections_opened, 1)
        finally:
            await self.client.close()
            echo_server.close()
            await echo_server.wait_closed()

    async def test_client_active_stream_limit_can_still_cancel_streams(self) -> None:
        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                payload = await read_frame(reader)
                await asyncio.sleep(0.5 if payload != b"fast" else 0)
                writer.write(frame(payload))
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", echo_port))
        client = TelescopingClient(max_active_streams=1)
        try:
            await client.connect_guard(self.descriptors[0])
            await client.extend(self.descriptors[1])
            await client.extend(self.descriptors[2])
            slow = await client.start_echo("127.0.0.1", echo_port, b"slow")
            with self.assertRaisesRegex(ValueError, "active-stream limit"):
                await client.start_echo("127.0.0.1", echo_port, b"fast")
            self.assertTrue(await slow.cancel())
            self.assertEqual(await client.request_echo("127.0.0.1", echo_port, b"fast"), b"fast")
        finally:
            await client.close()
            echo_server.close()
            await echo_server.wait_closed()

    async def test_idle_timeout_closes_circuit_before_sending_data(self) -> None:
        client = TelescopingClient(idle_timeout_seconds=0.02, max_lifetime_seconds=2.0)
        try:
            await client.connect_guard(self.descriptors[0])
            await asyncio.sleep(0.04)
            with self.assertRaisesRegex(ValueError, "idle timeout"):
                await client.request_echo("127.0.0.1", 6553, b"must not be sent")
            self.assertEqual(client.hops, [])
            self.assertIsNone(client._writer)
            self.assertEqual(self.nodes[0].observations, [])
        finally:
            await client.close()

    async def test_maximum_circuit_lifetime_closes_circuit(self) -> None:
        client = TelescopingClient(idle_timeout_seconds=2.0, max_lifetime_seconds=0.02)
        try:
            await client.connect_guard(self.descriptors[0])
            await asyncio.sleep(0.04)
            with self.assertRaisesRegex(ValueError, "maximum lifetime"):
                await client.request_echo("127.0.0.1", 6553, b"must not be sent")
            self.assertEqual(client.hops, [])
            self.assertIsNone(client._writer)
            self.assertEqual(self.nodes[0].observations, [])
        finally:
            await client.close()

    async def test_client_rejects_nonpositive_or_nonfinite_lifecycle_limits(self) -> None:
        for kwargs in (
            {"idle_timeout_seconds": 0},
            {"max_lifetime_seconds": -1},
            {"idle_timeout_seconds": float("inf")},
            {"max_lifetime_seconds": float("nan")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                TelescopingClient(**kwargs)

    async def test_stream_multiplex_benchmark_smoke_checks_integrity_and_cleanup(self) -> None:
        result = await run_stream_multiplex_benchmark(streams_count=4, payload_bytes=1024, seed=13)
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertTrue(result["results"]["route_knowledge_separation_check"])
        self.assertGreater(result["results"]["multiplexed_goodput_mbps"], 0)
        self.assertEqual(result["results"]["active_streams_after_completion"], 0)
        self.assertEqual(result["results"]["active_connections_after_close"], [0, 0, 0])
        self.assertFalse(result["metadata"]["is_production_security_test"])

    async def test_concurrency_benchmark_smoke_checks_isolation_and_cleanup(self) -> None:
        result = await run_concurrency_benchmark(clients_count=2, payload_bytes=2048, seed=9)
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertTrue(result["results"]["route_knowledge_separation_check"])
        self.assertEqual(result["results"]["client_direct_connections_per_circuit"], [1, 1])
        self.assertTrue(result["results"]["relay_handlers_returned_to_zero"])
        self.assertEqual(result["results"]["active_connections_after_client_close"], [0, 0, 0])
        self.assertGreater(result["results"]["circuit_aggregate_response_goodput_mbps"], 0)
        self.assertFalse(result["metadata"]["is_production_security_test"])

    async def test_relay_rejects_connections_above_configured_cap(self) -> None:
        limited = RelayNode(
            os.urandom(20), X25519PrivateKey.generate(), max_active_connections=1
        )
        server = await serve_node(limited)
        first_writer = second_writer = None
        try:
            first_reader, first_writer = await asyncio.open_connection("127.0.0.1", limited.port)
            for _ in range(50):
                if limited.active_connections == 1:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(limited.active_connections, 1)
            second_reader, second_writer = await asyncio.open_connection("127.0.0.1", limited.port)
            rejected = await asyncio.wait_for(second_reader.read(1), timeout=1)
            self.assertEqual(rejected, b"")
            self.assertEqual(limited.active_connections, 1)
        finally:
            if first_writer is not None:
                first_writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await first_writer.wait_closed()
            if second_writer is not None:
                second_writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await second_writer.wait_closed()
            server.close()
            await server.wait_closed()
        for _ in range(50):
            if limited.active_connections == 0:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(limited.active_connections, 0)

    async def test_oversized_frame_is_rejected_before_body_read(self) -> None:
        reader, writer = await asyncio.open_connection(
            self.descriptors[0].host, self.descriptors[0].port
        )
        try:
            writer.write((MAX_FRAME_BYTES + 1).to_bytes(4, "big"))
            await writer.drain()
            closed = await asyncio.wait_for(reader.read(1), timeout=1)
            self.assertEqual(closed, b"")
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    async def test_client_fails_closed_when_command_budget_is_exhausted(self) -> None:
        await self.client.connect_guard(self.descriptors[0])
        await self.client.extend(self.descriptors[1])
        await self.client.extend(self.descriptors[2])
        before = len(self.nodes[0].observations)
        self.client.hops[0].next_sequence = MAX_COMMANDS_PER_CIRCUIT
        with self.assertRaisesRegex(ValueError, "command budget exhausted"):
            await self.client.request_echo("127.0.0.1", 12345, b"not sent")
        self.assertEqual(self.client.hops, [])
        self.assertEqual(len(self.nodes[0].observations), before)

    async def test_descriptor_rejects_non_loopback_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            RelayDescriptor(
                "192.0.2.10", 9000, os.urandom(20), os.urandom(32)
            )

    async def test_exit_rejects_unallowlisted_loopback_destination(self) -> None:
        connections = 0

        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal connections
            connections += 1
            try:
                payload = await read_frame(reader)
                writer.write(frame(payload))
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, ValueError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        echo_server = await asyncio.start_server(echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        # Do not allowlist this endpoint at the exit relay.
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            with self.assertRaises((asyncio.IncompleteReadError, ConnectionError, TimeoutError, ValueError)):
                await self.client.request_echo("127.0.0.1", echo_port, b"must be blocked")
            self.assertEqual(connections, 0)
            self.assertEqual(self.nodes[2].observations, [])
        finally:
            echo_server.close()
            await echo_server.wait_closed()

    async def test_full_duplex_stream_write_half_close_read_and_close(self) -> None:
        received_by_server = bytearray()

        async def duplex_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(8192)
                    if not data:
                        break
                    received_by_server.extend(data)
                    writer.write(data)
                    await writer.drain()
                writer.write(b"SERVER_FINISHED")
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        echo_server = await asyncio.start_server(duplex_echo, "127.0.0.1", 0)
        echo_port = int(echo_server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", echo_port))
        payload = bytes(range(256)) * 1024
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            stream = await self.client.open_stream("127.0.0.1", echo_port)
            written = 0
            for offset in range(0, len(payload), STREAM_WRITE_MAX_BYTES):
                written += await stream.write(payload[offset:offset + STREAM_WRITE_MAX_BYTES])
            self.assertEqual(written, len(payload))
            await stream.write_eof()
            received = bytearray()
            while True:
                chunk = await asyncio.wait_for(stream.read_chunk(), timeout=5)
                if not chunk:
                    break
                received.extend(chunk)
            self.assertEqual(bytes(received), payload + b"SERVER_FINISHED")
            self.assertEqual(bytes(received_by_server), payload)
            self.assertTrue(await stream.close())
            self.assertEqual(self.client._active_duplex_streams, {})
            self.assertEqual(self.client.direct_connections_opened, 1)
            self.assertNotIn(echo_port, [e.target_port for node in self.nodes[:2] for e in node.observations])
        finally:
            echo_server.close()
            await echo_server.wait_closed()

    async def test_duplex_stream_window_bounds_server_push_until_client_reads(self) -> None:
        pushed = os.urandom(192 * 1024)

        async def push(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                writer.write(pushed)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

        server = await asyncio.start_server(push, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            stream = await self.client.open_stream("127.0.0.1", port)
            # Let the exit consume its initial bounded credit without the
            # application reading. It must not buffer the entire destination.
            await asyncio.sleep(0.05)
            self.assertLessEqual(len(stream._receive_buffer), 64 * 1024)
            result = bytearray()
            while True:
                chunk = await asyncio.wait_for(stream.read_chunk(), timeout=5)
                if not chunk:
                    break
                result.extend(chunk)
            self.assertEqual(bytes(result), pushed)
            window_updates = sum(
                event.operation == "window_update" for event in self.nodes[2].observations
            )
            self.assertLess(window_updates, len(pushed) // STREAM_CHUNK_BYTES)
            await stream.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_window_credit_batch_configuration_and_encoding_are_bounded(self) -> None:
        self.assertEqual(WINDOW_UPDATE_BATCH_BYTES, 64 * 1024)
        self.assertEqual(len(_encode_window_update_body(64 * 1024)), 4)
        self.assertEqual(len(_encode_window_update_body(MAX_STREAM_WINDOW_BYTES)), 4)
        with self.assertRaisesRegex(ValueError, "window update must be within"):
            _encode_window_update_body(0)
        with self.assertRaisesRegex(ValueError, "window update must be within"):
            _encode_window_update_body(MAX_STREAM_WINDOW_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "window update must be within"):
            _encode_window_update_body(True)
        with self.assertRaisesRegex(ValueError, "window_update_batch_bytes"):
            TelescopingClient(window_update_batch_bytes=0)
        with self.assertRaisesRegex(ValueError, "window_update_batch_bytes"):
            TelescopingClient(window_update_batch_bytes=MAX_STREAM_WINDOW_BYTES + 1)
        self.assertEqual(WINDOW_UPDATE_MAX_DELAY_SECONDS, 0.002)
        self.assertEqual(TelescopingClient().window_update_max_delay_seconds, 0.002)
        for invalid_delay in (0, -0.1, float("inf"), float("nan"), True, 1.01):
            with self.subTest(invalid_delay=invalid_delay), self.assertRaisesRegex(
                ValueError, "window_update_max_delay_seconds"
            ):
                TelescopingClient(window_update_max_delay_seconds=invalid_delay)
        self.assertEqual(TelescopingClient(window_update_max_delay_seconds=0.0005).window_update_max_delay_seconds, 0.0005)

    async def test_sparse_stream_flushes_subthreshold_credit_and_continues(self) -> None:
        first = os.urandom(STREAM_CHUNK_BYTES)
        second = os.urandom(STREAM_CHUNK_BYTES)

        async def sparse_push(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                writer.write(first)
                await writer.drain()
                # The gap must outlast stream setup (which itself can take tens
                # of milliseconds on slower platforms); otherwise both chunks
                # are already buffered before the first read and the timer path
                # this test exercises is never reached. It stays far below the
                # 5 s read timeout above.
                await asyncio.sleep(0.2)
                writer.write(second)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

        server = await asyncio.start_server(sparse_push, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            stream = await self.client.open_stream("127.0.0.1", port)
            received = bytearray()
            while True:
                chunk = await asyncio.wait_for(stream.read_chunk(), timeout=5)
                if not chunk:
                    break
                received.extend(chunk)
            self.assertEqual(bytes(received), first + second)
            # Two sparse chunks separated by a delay should not deadlock behind
            # the 64 KiB batching threshold; the 2 ms timer flushes the first.
            window_updates = sum(
                event.operation == "window_update" for event in self.nodes[2].observations
            )
            self.assertGreaterEqual(window_updates, 1)
            await stream.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_two_full_duplex_streams_are_isolated_on_one_circuit(self) -> None:
        async def duplex_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while data := await reader.read(4096):
                    writer.write(data)
                    await writer.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(duplex_echo, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            first, second = await asyncio.gather(
                self.client.open_stream("127.0.0.1", port),
                self.client.open_stream("127.0.0.1", port),
            )
            self.assertNotEqual(first.stream_id, second.stream_id)
            await asyncio.gather(first.write(b"alpha"), second.write(b"beta"))
            await asyncio.gather(first.write_eof(), second.write_eof())

            async def collect(stream) -> bytes:
                chunks = []
                while True:
                    chunk = await asyncio.wait_for(stream.read_chunk(), timeout=5)
                    if not chunk:
                        return b"".join(chunks)
                    chunks.append(chunk)

            out_first, out_second = await asyncio.gather(collect(first), collect(second))
            self.assertEqual(out_first, b"alpha")
            self.assertEqual(out_second, b"beta")
            await asyncio.gather(first.close(), second.close())
            self.assertEqual(self.client._active_duplex_streams, {})
        finally:
            server.close()
            await server.wait_closed()

    async def test_bounded_write_pipeline_preserves_order_and_half_close(self) -> None:
        received_by_server: list[bytes] = []

        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            received = bytearray()
            try:
                while data := await reader.read(16 * 1024):
                    received.extend(data)
                    writer.write(data)
                    await writer.drain()
                received_by_server.append(bytes(received))
                writer.write(b"PIPELINE_DONE")
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        payload_a = bytes(range(251)) * 1024
        payload_b = b"stream-b/" * 20_000
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            first, second = await asyncio.gather(
                self.client.open_stream("127.0.0.1", port),
                self.client.open_stream("127.0.0.1", port),
            )

            write_a = asyncio.create_task(first.write_pipelined(
                payload_a, chunk_bytes=32 * 1024, max_in_flight=4
            ))
            await asyncio.sleep(0)  # allow the pipeline to acquire the stream write lock
            eof_a = asyncio.create_task(first.write_eof())
            write_b = asyncio.create_task(second.write_pipelined(
                payload_b, chunk_bytes=16 * 1024, max_in_flight=3
            ))
            eof_b = asyncio.create_task(second.write_eof())
            self.assertEqual(await asyncio.wait_for(write_a, timeout=10), len(payload_a))
            self.assertEqual(await asyncio.wait_for(write_b, timeout=10), len(payload_b))
            await asyncio.wait_for(asyncio.gather(eof_a, eof_b), timeout=10)

            async def collect(stream) -> bytes:
                chunks: list[bytes] = []
                while True:
                    part = await asyncio.wait_for(stream.read_chunk(), timeout=5)
                    if not part:
                        return b"".join(chunks)
                    chunks.append(part)

            response_a, response_b = await asyncio.gather(collect(first), collect(second))
            self.assertEqual(response_a, payload_a + b"PIPELINE_DONE")
            self.assertEqual(response_b, payload_b + b"PIPELINE_DONE")
            self.assertCountEqual(received_by_server, [payload_a, payload_b])
            await asyncio.gather(first.close(), second.close())
            self.assertEqual(self.client._active_duplex_streams, {})
        finally:
            server.close()
            await server.wait_closed()

    async def test_pipeline_benchmark_smoke_checks_all_depths(self) -> None:
        result = await run_pipeline_benchmark(
            trials=1, stream_count=2, payload_bytes=1024, chunk_bytes=256, seed=113
        )
        self.assertEqual(set(result["by_pipeline_depth"]), {"1", "2", "4"})
        self.assertTrue(result["summary"]["all_integrity_checks_passed"])
        self.assertTrue(result["summary"]["all_relay_observability_checks_passed"])
        self.assertTrue(result["summary"]["all_cleanup_checks_passed"])
        self.assertEqual(result["metadata"]["version"], "0.26.0")
        self.assertFalse(result["metadata"]["is_production_security_test"])

    async def test_write_pipeline_rejects_invalid_depth_and_oversized_payload(self) -> None:
        async def sink(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while await reader.read(4096):
                    pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(sink, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            stream = await self.client.open_stream("127.0.0.1", port)
            with self.assertRaisesRegex(ValueError, "max_in_flight"):
                await stream.write_pipelined(b"x", max_in_flight=5)
            with self.assertRaisesRegex(ValueError, "pipelined write requires"):
                await stream.write_pipelined(b"x" * (4 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "would exceed 512 commands"):
                await stream.write_pipelined(b"x" * (1024 * 1024), chunk_bytes=1)
            await stream.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_duplex_benchmark_smoke_checks_integrity_flow_and_cleanup(self) -> None:
        result = await run_duplex_benchmark(stream_count=2, payload_bytes=2048, seed=15)
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertTrue(result["results"]["relay_observability_check"])
        self.assertGreater(result["results"]["duplex_goodput_mbps"], 0)
        self.assertGreater(result["results"]["direct_goodput_mbps"], 0)
        self.assertEqual(result["results"]["active_streams_after_completion"], 0)
        self.assertEqual(result["results"]["active_connections_after_close"], [0, 0, 0])
        self.assertFalse(result["metadata"]["is_production_security_test"])

    async def test_write_batch_benchmark_compares_three_sizes_with_integrity(self) -> None:
        from anonlab.write_batch_benchmark import BASELINE_WRITE_CHUNK_BYTES

        result = await run_write_batch_benchmark(
            trials=1, stream_count=2, payload_bytes=2048, seed=92
        )
        self.assertTrue(result["summary"]["all_integrity_checks_passed"])
        self.assertTrue(result["summary"]["all_relay_observability_checks_passed"])
        self.assertTrue(result["summary"]["all_cleanup_checks_passed"])
        modes = result["by_write_chunk_bytes"]
        self.assertEqual(set(modes), {str(BASELINE_WRITE_CHUNK_BYTES), str(64 * 1024), str(STREAM_WRITE_MAX_BYTES)})
        self.assertEqual(modes[str(BASELINE_WRITE_CHUNK_BYTES)]["write_acknowledgements_per_full_64k_stream"], 4)
        self.assertEqual(modes[str(64 * 1024)]["write_acknowledgements_per_full_64k_stream"], 1)
        self.assertEqual(modes[str(STREAM_WRITE_MAX_BYTES)]["write_acknowledgements_per_full_64k_stream"], 1)
        self.assertEqual(modes[str(BASELINE_WRITE_CHUNK_BYTES)]["write_acknowledgements_per_full_256k_stream"], 16)
        self.assertEqual(modes[str(64 * 1024)]["write_acknowledgements_per_full_256k_stream"], 4)
        self.assertEqual(modes[str(STREAM_WRITE_MAX_BYTES)]["write_acknowledgements_per_full_256k_stream"], 1)

    async def test_duplex_stream_rejects_oversized_write_locally(self) -> None:
        async def sink(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while await reader.read(4096):
                    pass
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(sink, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            stream = await self.client.open_stream("127.0.0.1", port)
            with self.assertRaisesRegex(ValueError, "write requires"):
                await stream.write(b"x" * (STREAM_WRITE_MAX_BYTES + 1))
            await stream.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_round_robin_scheduler_interleaves_streams_and_preserves_payloads(self) -> None:
        self.client = TelescopingClient(fair_write_scheduling=True)

        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    payload = await reader.read(8192)
                    if not payload:
                        break
                    writer.write(payload)
                    await writer.drain()
                if writer.can_write_eof():
                    writer.write_eof()
                    await writer.drain()
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        streams = []
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            streams = await asyncio.gather(*(
                self.client.open_stream("127.0.0.1", port) for _ in range(4)
            ))
            self.client._write_scheduler_trace.clear()
            payloads = [bytes([index]) * 4096 for index in range(1, 5)]
            written = await asyncio.gather(*(
                stream.write_pipelined(payload, chunk_bytes=1024, max_in_flight=4)
                for stream, payload in zip(streams, payloads, strict=True)
            ))
            self.assertEqual(written, [4096] * 4)
            trace = list(self.client._write_scheduler_trace)
            self.assertGreaterEqual(len(trace), 16)
            first_round = trace[:4]
            self.assertEqual(set(first_round), {stream.logical_id for stream in streams})
            self.assertEqual(len(first_round), len(set(first_round)))
            await asyncio.gather(*(stream.write_eof() for stream in streams))

            async def collect(stream):
                received = bytearray()
                while True:
                    part = await stream.read_chunk()
                    if not part:
                        return bytes(received)
                    received.extend(part)

            received = await asyncio.gather(*(collect(stream) for stream in streams))
            self.assertEqual(received, payloads)
            await asyncio.gather(*(stream.close() for stream in streams))
            self.assertEqual(self.client._scheduled_write_commands, 0)
            self.assertEqual(self.client._scheduled_write_bytes, 0)
        finally:
            for stream in streams:
                if not stream._closed:
                    with contextlib.suppress(Exception):
                        await stream.close()
            server.close()
            await server.wait_closed()

    async def test_scheduler_admission_limit_does_not_poison_circuit(self) -> None:
        from unittest.mock import patch

        self.client = TelescopingClient(fair_write_scheduling=True)

        async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    payload = await reader.read(4096)
                    if not payload:
                        break
                    writer.write(payload)
                    await writer.drain()
            finally:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        self.nodes[2].allowed_destinations.add(("127.0.0.1", port))
        stream = None
        try:
            await self.client.connect_guard(self.descriptors[0])
            await self.client.extend(self.descriptors[1])
            await self.client.extend(self.descriptors[2])
            stream = await self.client.open_stream("127.0.0.1", port)
            with patch("anonlab.telescoping.MAX_SCHEDULED_WRITE_BYTES", 512):
                with self.assertRaisesRegex(ValueError, "byte budget"):
                    await stream.write_pipelined(b"x" * 1024)
            self.assertEqual(len(self.client.hops), 3)
            self.assertFalse(stream._closed)
            self.assertEqual(await stream.write_pipelined(b"ok"), 2)
            await stream.write_eof()
            self.assertEqual(await stream.read_chunk(), b"ok")
            self.assertEqual(await stream.read_chunk(), b"")
        finally:
            if stream is not None and not stream._closed:
                with contextlib.suppress(Exception):
                    await stream.close()
            server.close()
            await server.wait_closed()

    async def test_fair_scheduler_is_opt_in_by_default(self) -> None:
        self.assertFalse(self.client.fair_write_scheduling)
        self.assertFalse(self.client.write_metrics_snapshot()["enabled"])
        self.assertTrue(TelescopingClient(fair_write_scheduling=True).fair_write_scheduling)
        self.assertTrue(TelescopingClient(collect_write_metrics=True).collect_write_metrics)
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            TelescopingClient(fair_write_scheduling=1)
        with self.assertRaisesRegex(ValueError, "collect_write_metrics must be a boolean"):
            TelescopingClient(collect_write_metrics=1)

    async def test_client_cannot_extend_before_guard_handshake(self) -> None:
        with self.assertRaisesRegex(ValueError, "connect to a guard"):
            await self.client.extend(self.descriptors[0])


if __name__ == "__main__":
    unittest.main()
