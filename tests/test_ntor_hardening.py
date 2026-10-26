from __future__ import annotations

import unittest

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from anonlab.ntor_experiment import (
        NtorReplayGuard,
        client_finish,
        client_start,
        relay_respond,
    )
except (ImportError, RuntimeError):
    X25519PrivateKey = None  # type: ignore[assignment,misc]


def _raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


@unittest.skipIf(X25519PrivateKey is None, "install aegis-anon-lab[onion-lab] for ntor tests")
class NtorHardeningRegressionTests(unittest.TestCase):
    def test_failed_client_finish_consumes_one_shot_state(self) -> None:
        identity = b"A" * 20
        relay_private = X25519PrivateKey.generate()
        state, _message = client_start(identity, _raw_public(relay_private))

        with self.assertRaisesRegex(ValueError, "invalid length"):
            client_finish(state, b"malformed")

        with self.assertRaisesRegex(ValueError, "already been consumed"):
            client_finish(state, b"malformed")

    def test_bad_client_identity_does_not_consume_replay_guard_capacity(self) -> None:
        identity = b"A" * 20
        relay_private = X25519PrivateKey.generate()
        guard = NtorReplayGuard(max_handshakes=1)
        _state, message = client_start(identity, _raw_public(relay_private))
        wrong_identity_message = b"B" * 20 + message[20:]

        with self.assertRaisesRegex(ValueError, "different relay identity"):
            relay_respond(
                wrong_identity_message,
                identity,
                relay_private,
                replay_guard=guard,
            )
        self.assertEqual(guard.count, 0)

        response, relay_keys = relay_respond(
            message, identity, relay_private, replay_guard=guard
        )
        self.assertEqual(len(response), 64)
        self.assertEqual(len(relay_keys.request_key), 32)
        self.assertEqual(guard.count, 1)

    def test_replay_guard_capacity_is_not_consumed_by_low_order_client_key(self) -> None:
        identity = b"C" * 20
        relay_private = X25519PrivateKey.generate()
        relay_public = _raw_public(relay_private)
        malformed = identity + relay_public + (b"\x00" * 32)
        guard = NtorReplayGuard(max_handshakes=1)

        with self.assertRaisesRegex(ValueError, "low-order"):
            relay_respond(malformed, identity, relay_private, replay_guard=guard)
        self.assertEqual(guard.count, 0)

        _state, valid_message = client_start(identity, relay_public)
        relay_respond(valid_message, identity, relay_private, replay_guard=guard)
        self.assertEqual(guard.count, 1)


if __name__ == "__main__":
    unittest.main()
