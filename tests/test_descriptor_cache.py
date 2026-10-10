from __future__ import annotations

import unittest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from anonlab.telescoping import RelayNode, serve_node


class RelayDescriptorCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_descriptor_is_cached_after_binding(self) -> None:
        node = RelayNode(identity_digest=b"m" * 20, onion_private_key=X25519PrivateKey.generate())
        self.assertIsNone(node.port)
        with self.assertRaisesRegex(ValueError, "not been bound"):
            _ = node.descriptor

        server = await serve_node(node)
        try:
            first = node.descriptor
            second = node.descriptor
            self.assertIs(first, second)
            self.assertEqual(first.port, node.port)
            self.assertEqual(first.host, "127.0.0.1")
        finally:
            server.close()
            await server.wait_closed()

    async def test_descriptor_cache_invalidates_if_endpoint_changes(self) -> None:
        node = RelayNode(identity_digest=b"n" * 20, onion_private_key=X25519PrivateKey.generate())
        server = await serve_node(node)
        original_port = node.port
        try:
            original = node.descriptor
            node.port = int(original_port) + 1
            changed = node.descriptor
            self.assertIsNot(original, changed)
            self.assertEqual(changed.port, int(original_port) + 1)
            node.port = original_port
            restored = node.descriptor
            self.assertIsNot(changed, restored)
            self.assertEqual(restored.port, original_port)
        finally:
            server.close()
            await server.wait_closed()

    async def test_descriptor_cache_invalidates_if_onion_key_changes(self) -> None:
        node = RelayNode(identity_digest=b"q" * 20, onion_private_key=X25519PrivateKey.generate())
        server = await serve_node(node)
        try:
            first = node.descriptor
            node.onion_private_key = X25519PrivateKey.generate()
            second = node.descriptor
            self.assertIsNot(first, second)
            self.assertNotEqual(first.onion_public_key, second.onion_public_key)
        finally:
            server.close()
            await server.wait_closed()

    async def test_descriptor_cache_invalidates_if_identity_digest_changes(self) -> None:
        node = RelayNode(identity_digest=b"o" * 20, onion_private_key=X25519PrivateKey.generate())
        server = await serve_node(node)
        try:
            first = node.descriptor
            node.identity_digest = b"p" * 20
            second = node.descriptor
            self.assertIsNot(first, second)
            self.assertEqual(second.identity_digest, b"p" * 20)
        finally:
            server.close()
            await server.wait_closed()
