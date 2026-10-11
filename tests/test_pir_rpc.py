from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
import unittest
from unittest.mock import patch

from anonlab.pir_rpc import (
    AuthenticatedPirRpcServer,
    PirRpcEndpoint,
    PirRpcError,
    PirRpcProtocolError,
    _REQUEST_DOMAIN,
    _RESPONSE_DOMAIN,
    _signed_envelope,
    _verify_envelope,
    recover_colluded_index,
    retrieve_two_server_pir_rpc,
    retrieve_four_server_pir_rpc_checked,
)
from anonlab.pir_two_server import make_query_pair


class AuthenticatedPirRpcTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.records = tuple(bytes([i, i ^ 0xA5, 255 - i, i ^ 0x3C]) for i in range(32))
        self.key_a = secrets.token_bytes(32)
        self.key_b = secrets.token_bytes(32)
        self.server_a = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-a", shared_key=self.key_a
        ).start()
        self.server_b = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-b", shared_key=self.key_b
        ).start()
        assert self.server_a.port is not None and self.server_b.port is not None
        self.endpoint_a = PirRpcEndpoint("replica-a", "127.0.0.1", self.server_a.port, self.key_a)
        self.endpoint_b = PirRpcEndpoint("replica-b", "127.0.0.1", self.server_b.port, self.key_b)

    async def asyncTearDown(self) -> None:
        await asyncio.gather(self.server_a.close(), self.server_b.close())

    async def test_two_distinct_authenticated_rpc_endpoints_retrieve_the_record(self):
        for index, expected in enumerate(self.records):
            with self.subTest(index=index):
                result = await retrieve_two_server_pir_rpc(
                    (self.endpoint_a, self.endpoint_b), len(self.records), index,
                    record_bytes=len(expected), timeout_seconds=2,
                )
                self.assertEqual(result.record, expected)
                self.assertEqual(result.server_ids, ("replica-a", "replica-b"))
                self.assertEqual(result.query_bytes_per_server, 4)
                self.assertEqual(result.response_bytes_per_server, len(expected))
                self.assertEqual(result.authenticated_messages, 4)
                self.assertFalse(result.is_production_secure)

    async def test_malformed_query_is_rejected_before_nonce_cache_and_rate_limit(self):
        nonce = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "replica-a",
            "nonce": nonce,
            "issued_at": int(time.time()),
            "query": base64.b64encode(bytes(1)).decode("ascii"),
        }
        frame = _signed_envelope(payload, self.key_a, _REQUEST_DOMAIN)
        original_acquire = self.server_a._rate_limiter.acquire
        calls = 0

        def count_acquire():
            nonlocal calls
            calls += 1
            return original_acquire()

        self.server_a._rate_limiter.acquire = count_acquire
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server_a.port)
            writer.write(frame)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(1), timeout=2), b"")
            self.assertNotIn(nonce, self.server_a._seen_nonces)
            self.assertEqual(calls, 0)
        finally:
            self.server_a._rate_limiter.acquire = original_acquire
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def test_query_mask_trailing_bits_are_rejected_before_admission(self):
        server = await AuthenticatedPirRpcServer(
            self.records[:10], server_id="ten-records", shared_key=secrets.token_bytes(32)
        ).start()
        key = server._key
        nonce = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "ten-records",
            "nonce": nonce,
            "issued_at": int(time.time()),
            "query": base64.b64encode(bytes([0, 0x80])).decode("ascii"),
        }
        frame = _signed_envelope(payload, key, _REQUEST_DOMAIN)
        original_acquire = server._rate_limiter.acquire
        calls = 0

        def count_acquire():
            nonlocal calls
            calls += 1
            return original_acquire()

        server._rate_limiter.acquire = count_acquire
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            writer.write(frame)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(1), timeout=2), b"")
            self.assertNotIn(nonce, server._seen_nonces)
            self.assertEqual(calls, 0)
        finally:
            server._rate_limiter.acquire = original_acquire
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await server.close()

    async def test_query_wire_schema_contains_mask_but_never_selected_index(self):
        query_a, query_b = make_query_pair(len(self.records), 19)
        payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "replica-a",
            "nonce": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
            "issued_at": int(time.time()),
            "query": base64.b64encode(query_a).decode("ascii"),
        }
        self.assertEqual(set(payload), {"protocol", "server_id", "nonce", "issued_at", "query"})
        self.assertNotIn("index", payload)
        self.assertNotIn("target_index", payload)
        self.assertEqual(recover_colluded_index(query_a, query_b, len(self.records)), 19)

    async def test_wrong_mac_is_rejected_and_connection_fails_closed(self):
        writer_payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "replica-a",
            "nonce": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
            "issued_at": int(time.time()),
            "query": base64.b64encode(b"\x00" * 4).decode("ascii"),
        }
        valid = _signed_envelope(writer_payload, self.key_a, _REQUEST_DOMAIN)
        raw = bytearray(valid[4:])
        envelope = json.loads(raw)
        envelope["mac"] = "0" * 64
        encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server_a.port)
            writer.write(len(encoded).to_bytes(4, "big") + encoded)
            await writer.drain()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(reader.readexactly(4), timeout=2)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

    async def test_stalled_client_is_closed_by_server_read_timeout(self):
        stalled = await AuthenticatedPirRpcServer(
            self.records, server_id="stall-guard", shared_key=secrets.token_bytes(32),
            request_timeout_seconds=0.05,
        ).start()
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", stalled.port)
            result = await asyncio.wait_for(reader.read(1), timeout=1.0)
            self.assertEqual(result, b"")
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await stalled.close()

    async def test_replayed_authenticated_request_is_rejected(self):
        nonce = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "replica-a",
            "nonce": nonce,
            "issued_at": int(time.time()),
            "query": base64.b64encode(b"\x00" * 4).decode("ascii"),
        }
        frame = _signed_envelope(payload, self.key_a, _REQUEST_DOMAIN)

        async def submit():
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server_a.port)
            try:
                writer.write(frame)
                await writer.drain()
                return await asyncio.wait_for(reader.read(1024), timeout=2)
            finally:
                writer.close()
                await writer.wait_closed()

        first = await submit()
        second = await submit()
        self.assertTrue(first)  # accepted query receives an authenticated response
        self.assertEqual(second, b"")  # same nonce is rejected without protocol detail
        response = _verify_envelope(first[4:], self.key_a, _RESPONSE_DOMAIN)
        self.assertEqual(response["nonce"], nonce)

    def test_future_dated_nonce_is_retained_for_full_validity_window(self):
        server = AuthenticatedPirRpcServer(
            self.records, server_id="future-nonce", shared_key=secrets.token_bytes(32),
            replay_cache_capacity=13,
            max_requests_per_second=0.1,
            request_burst=1,
        )
        with patch("anonlab.pir_rpc.time.time", return_value=1000):
            server._accept_nonce("future-nonce", 1060)
        # At t=1061 the request timestamp is still valid; its nonce must remain.
        with patch("anonlab.pir_rpc.time.time", return_value=1061):
            with self.assertRaisesRegex(PirRpcProtocolError, "replay"):
                server._accept_nonce("future-nonce", 1060)

    def test_full_replay_cache_rejects_without_evicting_live_nonces(self):
        server = AuthenticatedPirRpcServer(
            self.records, server_id="small-cache", shared_key=secrets.token_bytes(32),
            replay_cache_capacity=13, max_requests_per_second=0.1, request_burst=1,
        )
        with patch("anonlab.pir_rpc.time.time", return_value=1000):
            for index in range(13):
                server._accept_nonce(f"nonce-{index}", 1000)
            with self.assertRaisesRegex(PirRpcProtocolError, "cache is full"):
                server._accept_nonce("nonce-overflow", 1000)
            self.assertEqual(set(server._seen_nonces), {f"nonce-{i}" for i in range(13)})
            with self.assertRaisesRegex(PirRpcProtocolError, "replay"):
                server._accept_nonce("nonce-0", 1000)
        # After the complete validity window, old entries expire and admission recovers.
        with patch("anonlab.pir_rpc.time.time", return_value=1121):
            server._accept_nonce("nonce-recovered", 1121)
            self.assertEqual(set(server._seen_nonces), {"nonce-recovered"})

    async def test_response_mac_tampering_is_detected(self):
        payload = {"protocol": "AEGIS-PIR-RPC-v1", "server_id": "replica-a", "nonce": "n", "answer": "AA=="}
        frame = _signed_envelope(payload, self.key_a, _RESPONSE_DOMAIN)
        altered = json.loads(frame[4:])
        altered["payload"]["answer"] = "AQ=="
        raw = json.dumps(altered, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaises(PirRpcProtocolError):
            _verify_envelope(raw, self.key_a, _RESPONSE_DOMAIN)

    async def test_refuses_duplicate_identity_endpoint_or_key(self):
        same_identity = PirRpcEndpoint("replica-a", "127.0.0.1", self.server_b.port, self.key_b)
        with self.assertRaises(ValueError):
            await retrieve_two_server_pir_rpc((self.endpoint_a, same_identity), 32, 1, record_bytes=4)
        same_endpoint = PirRpcEndpoint("replica-b", "127.0.0.1", self.server_a.port, self.key_b)
        with self.assertRaises(ValueError):
            await retrieve_two_server_pir_rpc((self.endpoint_a, same_endpoint), 32, 1, record_bytes=4)
        same_key = PirRpcEndpoint("replica-b", "127.0.0.1", self.server_b.port, self.key_a)
        with self.assertRaises(ValueError):
            await retrieve_two_server_pir_rpc((self.endpoint_a, same_key), 32, 1, record_bytes=4)

    async def test_tls_certificate_rotation_is_rejected_for_legacy_hmac_server(self):
        with self.assertRaises(RuntimeError):
            self.server_a.rotate_tls_certificate("not-used-cert.pem", "not-used-key.pem")

    async def test_non_loopback_bind_and_short_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(self.records, server_id="remote", shared_key=secrets.token_bytes(32), host="0.0.0.0")
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(self.records, server_id="bad", shared_key=b"short")
        with self.assertRaises(ValueError):
            PirRpcEndpoint("remote", "192.0.2.1", 1234, secrets.token_bytes(32))

    async def test_mismatched_replica_shape_is_rejected(self):
        different_records = self.records[:-1]
        key_c = secrets.token_bytes(32)
        third = await AuthenticatedPirRpcServer(
            different_records, server_id="replica-c", shared_key=key_c
        ).start()
        try:
            assert third.port is not None
            endpoint_c = PirRpcEndpoint("replica-c", "127.0.0.1", third.port, key_c)
            # The RPC client cannot see remote DB shape before querying; fixed response-size
            # checking turns this mismatch into a protocol failure rather than bad output.
            with self.assertRaises(PirRpcError):
                await retrieve_two_server_pir_rpc(
                    (self.endpoint_a, endpoint_c), len(self.records), 3, record_bytes=4, timeout_seconds=2
                )
        finally:
            await third.close()


    async def test_caller_pinned_snapshot_fingerprint_is_enforced(self):
        # The fingerprint must come from a trusted channel; this only detects a
        # mismatch and does not prove a malicious replica computed its answer correctly.
        expected = self.server_a.snapshot_sha256
        result = await retrieve_two_server_pir_rpc(
            (self.endpoint_a, self.endpoint_b), len(self.records), 7,
            record_bytes=4, timeout_seconds=2, expected_snapshot_sha256=expected,
        )
        self.assertEqual(result.snapshot_sha256, expected)
        with self.assertRaises(PirRpcProtocolError):
            await retrieve_two_server_pir_rpc(
                (self.endpoint_a, self.endpoint_b), len(self.records), 7,
                record_bytes=4, timeout_seconds=2, expected_snapshot_sha256="0" * 64,
            )

    async def test_malicious_replica_can_corrupt_answer_while_claiming_pinned_snapshot(self):
        # Security characterization test: transport authentication and snapshot
        # pinning do not prove that a replica evaluated the PIR query correctly.
        # The malicious endpoint controls its valid HMAC key and lies only in the
        # answer while preserving the genuine snapshot fingerprint.
        original_answer = self.server_b._reference.answer

        def corrupted_answer(query):
            answer = bytearray(original_answer(query))
            answer[0] ^= 0x80
            return bytes(answer)

        self.server_b._reference.answer = corrupted_answer
        expected_record = self.records[7]
        result = await retrieve_two_server_pir_rpc(
            (self.endpoint_a, self.endpoint_b), len(self.records), 7,
            record_bytes=4, timeout_seconds=2,
            expected_snapshot_sha256=self.server_a.snapshot_sha256,
        )
        self.assertEqual(result.snapshot_sha256, self.server_a.snapshot_sha256)
        self.assertNotEqual(result.record, expected_record)

    async def test_four_server_independent_reconstruction_detects_one_corrupt_replica(self):
        key_c, key_d = secrets.token_bytes(32), secrets.token_bytes(32)
        server_c = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-c", shared_key=key_c
        ).start()
        server_d = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-d", shared_key=key_d
        ).start()
        try:
            assert server_c.port is not None and server_d.port is not None
            endpoint_c = PirRpcEndpoint("replica-c", "127.0.0.1", server_c.port, key_c)
            endpoint_d = PirRpcEndpoint("replica-d", "127.0.0.1", server_d.port, key_d)
            original_answer = self.server_b._reference.answer

            def corrupted_answer(query):
                answer = bytearray(original_answer(query))
                answer[0] ^= 0x01
                return bytes(answer)

            self.server_b._reference.answer = corrupted_answer
            with self.assertRaisesRegex(PirRpcProtocolError, "reconstructions disagree"):
                await retrieve_four_server_pir_rpc_checked(
                    (self.endpoint_a, self.endpoint_b, endpoint_c, endpoint_d),
                    len(self.records), 7, record_bytes=4, timeout_seconds=2,
                    expected_snapshot_sha256=self.server_a.snapshot_sha256,
                )
        finally:
            await asyncio.gather(server_c.close(), server_d.close())

    async def test_four_server_checked_retrieval_succeeds_when_all_replicas_agree(self):
        key_c, key_d = secrets.token_bytes(32), secrets.token_bytes(32)
        server_c = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-c", shared_key=key_c
        ).start()
        server_d = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-d", shared_key=key_d
        ).start()
        try:
            assert server_c.port is not None and server_d.port is not None
            endpoints = (
                self.endpoint_a, self.endpoint_b,
                PirRpcEndpoint("replica-c", "127.0.0.1", server_c.port, key_c),
                PirRpcEndpoint("replica-d", "127.0.0.1", server_d.port, key_d),
            )
            result = await retrieve_four_server_pir_rpc_checked(
                endpoints, len(self.records), 13, record_bytes=4, timeout_seconds=2,
                expected_snapshot_sha256=self.server_a.snapshot_sha256,
            )
            self.assertEqual(result.record, self.records[13])
            self.assertEqual(result.server_ids, ("replica-a", "replica-b", "replica-c", "replica-d"))
            self.assertEqual(result.authenticated_messages, 8)
            self.assertFalse(result.is_production_secure)
        finally:
            await asyncio.gather(server_c.close(), server_d.close())

    async def test_caller_pinned_snapshot_fingerprint_format_is_validated(self):
        with self.assertRaises(ValueError):
            await retrieve_two_server_pir_rpc(
                (self.endpoint_a, self.endpoint_b), len(self.records), 7,
                record_bytes=4, expected_snapshot_sha256="not-a-digest",
            )

    async def test_same_shape_but_different_replica_snapshot_is_rejected(self):
        altered_records = tuple((bytes([row[0] ^ 0xFF]) + row[1:]) for row in self.records)
        key_c = secrets.token_bytes(32)
        third = await AuthenticatedPirRpcServer(
            altered_records, server_id="replica-c", shared_key=key_c
        ).start()
        try:
            assert third.port is not None
            endpoint_c = PirRpcEndpoint("replica-c", "127.0.0.1", third.port, key_c)
            with self.assertRaises(PirRpcProtocolError):
                await retrieve_two_server_pir_rpc(
                    (self.endpoint_a, endpoint_c), len(self.records), 3, record_bytes=4, timeout_seconds=2
                )
        finally:
            await third.close()


if __name__ == "__main__":
    unittest.main()
