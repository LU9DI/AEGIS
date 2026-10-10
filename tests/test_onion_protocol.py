from __future__ import annotations

import asyncio
import os
import unittest

try:
    from cryptography.exceptions import InvalidTag
    from anonlab.onion_protocol import (
        CircuitReplayGuard,
        build_request,
        frame,
        open_sealed,
        parse_request_layer,
        seal,
        unwrap_response,
        wrap_response,
    )
    from anonlab.onion_benchmark import run_onion_benchmark
except (ImportError, RuntimeError):  # optional research dependency
    InvalidTag = None  # type: ignore[assignment,misc]


@unittest.skipIf(InvalidTag is None, "install aegis-anon-lab[onion-lab] to run AEAD prototype tests")
class OnionPrototypeTests(unittest.TestCase):
    def test_aead_detects_tampering(self) -> None:
        key = bytes(range(32))
        packet = seal(key, b"secret", b"aad")
        self.assertEqual(open_sealed(key, packet, b"aad"), b"secret")
        modified = packet[:-1] + bytes([packet[-1] ^ 1])
        with self.assertRaises(InvalidTag):
            open_sealed(key, modified, b"aad")

    def test_response_round_trip_binds_circuit_and_sequence(self) -> None:
        key = b"k" * 32
        circuit_id = b"c" * 16
        sealed = wrap_response(
            key, "relay-1", b"response", circuit_id=circuit_id, sequence=7
        )
        self.assertEqual(
            unwrap_response(
                key, "relay-1", sealed, circuit_id=circuit_id, expected_sequence=7
            ),
            b"response",
        )
        with self.assertRaises(ValueError):
            unwrap_response(
                key, "relay-1", sealed, circuit_id=circuit_id, expected_sequence=6
            )
        with self.assertRaises(ValueError):
            unwrap_response(
                key, "relay-1", sealed, circuit_id=b"d" * 16, expected_sequence=7
            )
        with self.assertRaises(InvalidTag):
            unwrap_response(
                key, "relay-2", sealed, circuit_id=circuit_id, expected_sequence=7
            )

    def test_request_layer_carries_authenticated_circuit_and_sequence(self) -> None:
        key = b"a" * 32
        circuit_id = bytes(range(16))
        packet = build_request(
            b"payload", [12001], [key], 12002, circuit_id=circuit_id, sequence=41
        )
        layer = parse_request_layer(key, "relay-1", packet)
        self.assertEqual(layer["payload"], b"payload")
        self.assertEqual(layer["circuit_id"], circuit_id)
        self.assertEqual(layer["sequence"], 41)
        self.assertTrue(layer["terminal"])

    def test_build_request_requires_matching_route_keys(self) -> None:
        with self.assertRaises(ValueError):
            build_request(
                b"x", [10001, 10002], [b"k" * 32], 10003, circuit_id=b"c" * 16
            )

    def test_replay_guard_rejects_duplicate_ids_and_fails_closed_when_full(self) -> None:
        guard = CircuitReplayGuard(max_circuits=2)
        first = b"a" * 16
        second = b"b" * 16
        guard.claim(first)
        with self.assertRaisesRegex(ValueError, "replayed"):
            guard.claim(first)
        guard.claim(second)
        with self.assertRaisesRegex(ValueError, "full"):
            guard.claim(b"c" * 16)
        self.assertEqual(guard.count, 2)

    def test_live_relay_rejects_replayed_first_frame_on_new_connection(self) -> None:
        from anonlab.onion_relay import _handle

        async def scenario() -> None:
            key = os.urandom(32)

            async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    payload = await reader.readexactly(8)
                    writer.write(payload)
                    await writer.drain()
                except (asyncio.IncompleteReadError, ConnectionError):
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()

            destination = await asyncio.start_server(echo, "127.0.0.1", 0)
            destination_port = int(destination.sockets[0].getsockname()[1])
            relay = await asyncio.start_server(
                lambda r, w: _handle(r, w, "relay-1", key, destination_port, True),
                "127.0.0.1",
                0,
            )
            relay_port = int(relay.sockets[0].getsockname()[1])
            circuit_id = os.urandom(16)
            packet = build_request(
                b"payload!", [relay_port], [key], destination_port,
                circuit_id=circuit_id, sequence=0,
            )

            async def read_frame(reader: asyncio.StreamReader) -> bytes:
                length = int.from_bytes(await reader.readexactly(4), "big")
                return await reader.readexactly(length)

            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
                writer.write(frame(packet))
                await writer.drain()
                response = await asyncio.wait_for(read_frame(reader), timeout=2)
                self.assertEqual(
                    unwrap_response(
                        key, "relay-1", response,
                        circuit_id=circuit_id, expected_sequence=0,
                    ),
                    b"payload!",
                )
                # Replay an already accepted sequence on the same live circuit.
                writer.write(frame(packet))
                await writer.drain()
                duplicate_sequence_close = await asyncio.wait_for(reader.read(4), timeout=2)
                self.assertEqual(duplicate_sequence_close, b"", "relay should close a duplicate sequence")
                writer.close()
                await writer.wait_closed()

                # Replay the same captured first frame on a different TCP connection.
                replay_reader, replay_writer = await asyncio.open_connection("127.0.0.1", relay_port)
                replay_writer.write(frame(packet))
                await replay_writer.drain()
                duplicate_circuit_close = await asyncio.wait_for(replay_reader.read(4), timeout=2)
                self.assertEqual(duplicate_circuit_close, b"", "relay should close a reused circuit ID")
                replay_writer.close()
                await replay_writer.wait_closed()
            finally:
                relay.close()
                destination.close()
                await relay.wait_closed()
                await destination.wait_closed()

        asyncio.run(scenario())

    def test_three_hop_encrypted_request_response_integrity(self) -> None:
        result = asyncio.run(
            run_onion_benchmark(
                hop_count=3,
                payload_bytes=32_000,
                trials=1,
                latency_samples=3,
                seed=321,
            )
        )
        self.assertFalse(result["is_anonymity_test"])
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertGreater(result["results"]["request_response_latency_p50_ms"], 0)
        self.assertGreater(result["results"]["payload_goodput_mbps_median"], 0)
        self.assertEqual(result["topology"]["relay_count"], 3)
        self.assertEqual(result["schema_version"], 2)

    def test_three_hop_persistent_circuit_checks_monotonic_sequence(self) -> None:
        result = asyncio.run(
            run_onion_benchmark(
                hop_count=3,
                payload_bytes=16_000,
                trials=2,
                latency_samples=3,
                seed=654,
                persistent=True,
            )
        )
        self.assertTrue(result["config"]["persistent_circuit"])
        self.assertTrue(result["results"]["integrity_verified"])
        self.assertEqual(len(result["results"]["transfer_trials"]), 2)
        self.assertGreater(result["results"]["payload_goodput_mbps_median"], 0)


if __name__ == "__main__":
    unittest.main()
