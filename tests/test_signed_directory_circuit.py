from __future__ import annotations

import asyncio
import copy
import time
import unittest
import tempfile
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from anonlab.directory import (
        DirectoryAuthority,
        DirectoryVerifier,
        create_relay_descriptor,
        relay_identity_digest,
        descriptor_to_json,
    )
    from anonlab.onion_protocol import frame
    from anonlab.telescoping import (
        RelayNode, TelescopingClient, read_frame, serve_node, _link_hello, LINK_AUTH,
    )
except (ImportError, RuntimeError):  # optional research dependency
    X25519PrivateKey = None  # type: ignore[assignment,misc]


def raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def raw_ed_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


@unittest.skipIf(X25519PrivateKey is None, "install aegis-anon-lab[onion-lab] for signed-directory integration tests")
class SignedDirectoryCircuitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.nodes: list[RelayNode] = []
        self.servers: list[asyncio.AbstractServer] = []
        self.client = TelescopingClient()
        self.state_directory = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self.state_directory.cleanup)
        self.authority = DirectoryAuthority.generate()
        self.verifier = DirectoryVerifier(
            self.authority.public_key_bytes,
            state_path=Path(self.state_directory.name) / "directory-state.json",
        )
        self.now = int(time.time())
        self.verifier.apply_revocations(
            self.authority.sign_revocations([], epoch=1, now=self.now), now=self.now
        )
        self.signed_descriptors: list[dict] = []
        for _ in range(3):
            identity_key = Ed25519PrivateKey.generate()
            onion_key = X25519PrivateKey.generate()
            identity_public = raw_ed_public(identity_key)
            node = RelayNode(relay_identity_digest(identity_public), onion_key, identity_private_key=identity_key)
            server = await serve_node(node)
            self.nodes.append(node)
            self.servers.append(server)
            relay_descriptor = create_relay_descriptor(
                identity_key,
                raw_public(onion_key),
                "127.0.0.1",
                node.port,
                now=self.now,
                valid_for_seconds=1800,
                sequence=1,
            )
            self.signed_descriptors.append(
                self.authority.certify(relay_descriptor, now=self.now)
            )
        # Each relay has its own persistent verifier and independently verifies
        # its local certificate. This models per-node trust state rather than
        # relying on the client's in-memory verifier for peer authorization.
        self.peer_verifiers: list[DirectoryVerifier] = []
        initial_revocations = self.authority.sign_revocations([], epoch=1, now=self.now)
        for index, (node, descriptor) in enumerate(zip(self.nodes, self.signed_descriptors, strict=True)):
            peer_verifier = DirectoryVerifier(
                self.authority.public_key_bytes,
                state_path=Path(self.state_directory.name) / f"relay-{index}-directory-state.json",
                require_persistent_state=True,
            )
            peer_verifier.apply_revocations(initial_revocations, now=self.now)
            node.configure_directory_authorization(peer_verifier, descriptor)
            self.peer_verifiers.append(peer_verifier)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()

    async def test_peer_authorization_requires_listener_to_be_bound(self) -> None:
        identity = Ed25519PrivateKey.generate()
        public = raw_ed_public(identity)
        node = RelayNode(
            relay_identity_digest(public),
            X25519PrivateKey.generate(),
            identity_private_key=identity,
        )
        with self.assertRaisesRegex(ValueError, "must be bound to its listener"):
            node.configure_directory_authorization(self.verifier, self.signed_descriptors[0])

    async def test_signed_directory_drives_three_hop_circuit_and_data_plane(self) -> None:
        route = self.verifier.verify_circuit_route(
            self.signed_descriptors, now=self.now
        )

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
        self.nodes[-1].allowed_destinations.add(("127.0.0.1", echo_port))
        try:
            self.assertTrue(all(len(item.identity_public_key) == 32 for item in route.descriptors))
            await self.client.connect_verified_route(route)
            # Entry saw a client-only authenticated hello; middle and exit each
            # authenticated their previous relay over the existing circuit.
            self.assertEqual(len(self.nodes[0].link_replay_guard._seen), 1)
            self.assertEqual(len(self.nodes[1].link_replay_guard._seen), 1)
            self.assertEqual(len(self.nodes[2].link_replay_guard._seen), 1)
            payload = b"signed directory to telescoping circuit" * 64
            response = await self.client.request_echo("127.0.0.1", echo_port, payload)
            self.assertEqual(response, payload)
            self.assertEqual(self.client.direct_connections_opened, 1)
            self.assertNotIn(echo_port, [event.target_port for event in self.nodes[0].observations])
            self.assertNotIn(echo_port, [event.target_port for event in self.nodes[1].observations])
            self.assertEqual(self.nodes[2].observations[-1].target_port, echo_port)
        finally:
            echo_server.close()
            await echo_server.wait_closed()

    async def test_new_revocation_epoch_invalidates_live_verified_route_before_data(self) -> None:
        route = self.verifier.verify_circuit_route(self.signed_descriptors, now=self.now)
        await self.client.connect_verified_route(route)
        self.assertEqual(len(self.client.hops), 3)

        current = int(time.time())
        newer_snapshot = self.authority.sign_revocations([], epoch=2, now=current)
        self.verifier.apply_revocations(newer_snapshot, now=current)

        with self.assertRaisesRegex(ValueError, "invalidated by a newer revocation snapshot"):
            await self.client.request_echo("127.0.0.1", 6553, b"must fail before DATA")

        self.assertEqual(self.client.hops, [])
        self.assertIsNone(self.client._writer)
        self.assertEqual(
            [event.operation for event in self.nodes[2].observations],
            [],
            "stale route must be rejected before the exit sees a command",
        )

    async def test_revoked_certified_peer_is_rejected_before_link_auth_reply(self) -> None:
        target = self.nodes[1]
        peer = self.nodes[0]
        current = int(time.time())
        revoked = self.authority.sign_revocations(
            [self.signed_descriptors[0]["relay_id"]], epoch=2, now=current
        )
        self.peer_verifiers[1].apply_revocations(revoked, now=current)
        hello = _link_hello(
            target.descriptor,
            initiator_identity_private_key=peer.identity_private_key,
            initiator_directory_descriptor=descriptor_to_json(self.signed_descriptors[0]).encode("ascii"),
        )
        reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
        try:
            writer.write(frame(hello))
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader), timeout=1)
            self.assertEqual(len(target.link_replay_guard._seen), 0)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_strict_relay_requires_peer_certificate(self) -> None:
        target = self.nodes[1]
        peer = self.nodes[0]
        hello = _link_hello(
            target.descriptor,
            initiator_identity_private_key=peer.identity_private_key,
            initiator_directory_descriptor=None,
        )
        reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
        try:
            writer.write(frame(hello))
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader), timeout=1)
            self.assertEqual(len(target.link_replay_guard._seen), 0)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_peer_allowlist_rejects_otherwise_valid_certified_relay(self) -> None:
        target = self.nodes[1]
        peer = self.nodes[0]
        target.authorized_peer_ids = frozenset({b"\x99" * 20})
        hello = _link_hello(
            target.descriptor,
            initiator_identity_private_key=peer.identity_private_key,
            initiator_directory_descriptor=descriptor_to_json(self.signed_descriptors[0]).encode("ascii"),
        )
        reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
        try:
            writer.write(frame(hello))
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader), timeout=1)
            self.assertEqual(len(target.link_replay_guard._seen), 0)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_expired_peer_certificate_is_rejected(self) -> None:
        target = self.nodes[1]
        peer_identity = Ed25519PrivateKey.generate()
        past = int(time.time()) - 120
        peer_onion = X25519PrivateKey.generate()
        expired_unsigned = create_relay_descriptor(
            peer_identity, raw_public(peer_onion), "127.0.0.1", 54321,
            now=past, valid_for_seconds=1, sequence=1,
        )
        expired_cert = self.authority.certify(expired_unsigned, now=past)
        hello = _link_hello(
            target.descriptor,
            initiator_identity_private_key=peer_identity,
            initiator_directory_descriptor=descriptor_to_json(expired_cert).encode("ascii"),
        )
        reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
        try:
            writer.write(frame(hello))
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader), timeout=1)
            self.assertEqual(len(target.link_replay_guard._seen), 0)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_peer_certificate_from_wrong_directory_authority_is_rejected(self) -> None:
        target = self.nodes[1]
        peer_identity = Ed25519PrivateKey.generate()
        peer_onion = X25519PrivateKey.generate()
        current = int(time.time())
        unsigned = create_relay_descriptor(
            peer_identity, raw_public(peer_onion), "127.0.0.1", 54322,
            now=current, valid_for_seconds=600, sequence=1,
        )
        rogue_authority = DirectoryAuthority.generate()
        rogue_cert = rogue_authority.certify(unsigned, now=current)
        hello = _link_hello(
            target.descriptor,
            initiator_identity_private_key=peer_identity,
            initiator_directory_descriptor=descriptor_to_json(rogue_cert).encode("ascii"),
        )
        reader, writer = await asyncio.open_connection(target.descriptor.host, target.descriptor.port)
        try:
            writer.write(frame(hello))
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(read_frame(reader), timeout=1)
            self.assertEqual(len(target.link_replay_guard._seen), 0)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_unverified_route_is_rejected_before_any_socket(self) -> None:
        class FakeRoute:
            descriptors = tuple()
            def assert_usable(self) -> None:
                return None
        with self.assertRaisesRegex(ValueError, "DirectoryVerifier-issued"):
            await self.client.connect_verified_route(FakeRoute())
        self.assertEqual(self.client.direct_connections_opened, 0)

    async def test_expired_verified_route_is_rejected_before_any_socket(self) -> None:
        route = self.verifier.verify_circuit_route(self.signed_descriptors, now=self.now)
        with self.assertRaisesRegex(ValueError, "has expired"):
            route.assert_usable(now=route.expires_at)
        self.assertEqual(self.client.direct_connections_opened, 0)

    async def test_tampered_directory_entry_is_rejected_before_any_circuit_socket(self) -> None:
        forged = copy.deepcopy(self.signed_descriptors)
        forged[1]["port"] = forged[1]["port"] + 1
        with self.assertRaisesRegex(ValueError, "relay signature verification failed"):
            self.verifier.verify_circuit_descriptors(forged, now=self.now)
        self.assertEqual(self.client.direct_connections_opened, 0)
        self.assertEqual([node.active_connections for node in self.nodes], [0, 0, 0])

    async def test_revoked_relay_prevents_route_materialization(self) -> None:
        relay_id = self.signed_descriptors[1]["relay_id"]
        revocations = self.authority.sign_revocations(
            [relay_id], epoch=2, now=self.now + 1, valid_for_seconds=1800
        )
        self.verifier.apply_revocations(revocations, now=self.now + 1)
        with self.assertRaisesRegex(ValueError, "identity is revoked"):
            self.verifier.verify_circuit_descriptors(
                self.signed_descriptors, now=self.now + 1
            )
        self.assertEqual(self.client.direct_connections_opened, 0)


if __name__ == "__main__":
    unittest.main()
