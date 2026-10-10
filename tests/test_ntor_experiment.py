from __future__ import annotations

import asyncio
import unittest

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from anonlab.ntor_experiment import (
        CLIENT_HANDSHAKE_BYTES,
        SERVER_HANDSHAKE_BYTES,
        NtorReplayGuard,
        client_finish,
        client_start,
        relay_respond,
    )
    from anonlab.ntor_benchmark import run_ntor_benchmark
except (ImportError, RuntimeError):  # optional research dependency
    X25519PrivateKey = None  # type: ignore[assignment,misc]


def raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


@unittest.skipIf(X25519PrivateKey is None, "install aegis-anon-lab[onion-lab] for ntor tests")
class NtorExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = b"M" * 20
        self.onion_private = X25519PrivateKey.generate()
        self.onion_public = raw_public(self.onion_private)

    def test_client_and_relay_derive_matching_directional_keys(self) -> None:
        state, message = client_start(self.identity, self.onion_public)
        response, relay_keys = relay_respond(message, self.identity, self.onion_private)
        client_keys = client_finish(state, response)
        self.assertEqual(len(message), CLIENT_HANDSHAKE_BYTES)
        self.assertEqual(len(response), SERVER_HANDSHAKE_BYTES)
        self.assertEqual(client_keys, relay_keys)
        self.assertNotEqual(client_keys.request_key, client_keys.response_key)

    def test_each_handshake_derives_fresh_keys(self) -> None:
        sessions = []
        for _ in range(2):
            state, message = client_start(self.identity, self.onion_public)
            response, _ = relay_respond(message, self.identity, self.onion_private)
            sessions.append(client_finish(state, response))
        self.assertNotEqual(sessions[0].request_key, sessions[1].request_key)
        self.assertNotEqual(sessions[0].response_key, sessions[1].response_key)

    def test_client_rejects_tampered_server_authenticator(self) -> None:
        state, message = client_start(self.identity, self.onion_public)
        response, _ = relay_respond(message, self.identity, self.onion_private)
        changed = response[:-1] + bytes([response[-1] ^ 0x01])
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            client_finish(state, changed)

    def test_client_state_is_one_shot(self) -> None:
        state, message = client_start(self.identity, self.onion_public)
        response, _ = relay_respond(message, self.identity, self.onion_private)
        client_finish(state, response)
        with self.assertRaisesRegex(ValueError, "already been consumed"):
            client_finish(state, response)

    def test_client_rejects_low_order_relay_ephemeral_key(self) -> None:
        state, _message = client_start(self.identity, self.onion_public)
        response = (b"\x00" * 32) + (b"\x00" * 32)
        with self.assertRaisesRegex(ValueError, "low-order"):
            client_finish(state, response)

    def test_relay_rejects_wrong_identity_digest(self) -> None:
        state, message = client_start(self.identity, self.onion_public)
        del state
        with self.assertRaisesRegex(ValueError, "different relay identity"):
            relay_respond(message, b"N" * 20, self.onion_private)

    def test_relay_rejects_stale_or_wrong_onion_public_key(self) -> None:
        wrong_relay_key = X25519PrivateKey.generate()
        state, message = client_start(self.identity, raw_public(wrong_relay_key))
        del state
        with self.assertRaisesRegex(ValueError, "stale or incorrect"):
            relay_respond(message, self.identity, self.onion_private)

    def test_relay_rejects_low_order_client_public_key(self) -> None:
        message = self.identity + self.onion_public + (b"\x00" * 32)
        with self.assertRaisesRegex(ValueError, "low-order"):
            relay_respond(message, self.identity, self.onion_private)

    def test_replay_guard_rejects_reused_ephemeral_and_fails_closed(self) -> None:
        guard = NtorReplayGuard(max_handshakes=1)
        state, message = client_start(self.identity, self.onion_public)
        first_response, _ = relay_respond(
            message, self.identity, self.onion_private, replay_guard=guard
        )
        self.assertEqual(len(first_response), SERVER_HANDSHAKE_BYTES)
        with self.assertRaisesRegex(ValueError, "replayed"):
            relay_respond(message, self.identity, self.onion_private, replay_guard=guard)
        second_state, second_message = client_start(self.identity, self.onion_public)
        del state, second_state
        with self.assertRaisesRegex(ValueError, "full"):
            relay_respond(second_message, self.identity, self.onion_private, replay_guard=guard)

    def test_malformed_handshake_length_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid length"):
            relay_respond(b"short", self.identity, self.onion_private)
        state, message = client_start(self.identity, self.onion_public)
        del message
        with self.assertRaisesRegex(ValueError, "invalid length"):
            client_finish(state, b"short")

    def test_handshake_messages_work_over_loopback_tcp(self) -> None:
        async def scenario() -> None:
            replay_guard = NtorReplayGuard()

            async def responder(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    client_message = await reader.readexactly(CLIENT_HANDSHAKE_BYTES)
                    reply, _keys = relay_respond(
                        client_message, self.identity, self.onion_private,
                        replay_guard=replay_guard,
                    )
                    writer.write(reply)
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            server = await asyncio.start_server(responder, "127.0.0.1", 0)
            port = int(server.sockets[0].getsockname()[1])
            try:
                state, message = client_start(self.identity, self.onion_public)
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(message)
                await writer.drain()
                response = await asyncio.wait_for(reader.readexactly(SERVER_HANDSHAKE_BYTES), 2)
                client_keys = client_finish(state, response)
                writer.close()
                await writer.wait_closed()
                self.assertEqual(len(client_keys.request_key), 32)
                self.assertEqual(len(client_keys.response_key), 32)
            finally:
                server.close()
                await server.wait_closed()

        asyncio.run(scenario())

    def test_ntor_benchmark_smoke(self) -> None:
        from anonlab.ntor_benchmark import run_ntor_benchmark

        result = asyncio.run(run_ntor_benchmark(rounds=2))
        self.assertFalse(result["is_anonymity_test"])
        self.assertTrue(result["results"]["all_key_agreements_verified"])
        self.assertEqual(result["config"]["rounds"], 2)
        self.assertEqual(result["protocol"]["total_handshake_payload_bytes"], 148)
        self.assertGreater(result["results"]["loopback_handshake_rtt_ms_p50"], 0)


if __name__ == "__main__":
    unittest.main()
