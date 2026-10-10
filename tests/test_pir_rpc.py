from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
import unittest

from anonlab.pir_rpc import (
    AuthenticatedPirRpcServer,
    PirRpcEndpoint,
    PirRpcError,
    PirRpcProtocolError,
    _REQUEST_DOMAIN,
    _RESPONSE_DOMAIN,
    _query_endpoint,
    _mac,
    _strict_json_loads,
    _verify_transport_envelope,
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

        original_acquire = self.server_a._rate_limiter.acquire
        acquire_calls = 0

        def count_acquire():
            nonlocal acquire_calls
            acquire_calls += 1
            return original_acquire()

        self.server_a._rate_limiter.acquire = count_acquire
        try:
            first = await submit()
            second = await submit()
        finally:
            self.server_a._rate_limiter.acquire = original_acquire
        self.assertTrue(first)  # accepted query receives an authenticated response
        self.assertEqual(second, b"")  # same nonce is rejected without protocol detail
        self.assertEqual(acquire_calls, 1)  # replay rejection happens before admission control
        response = _verify_envelope(first[4:], self.key_a, _RESPONSE_DOMAIN)
        self.assertEqual(response["nonce"], nonce)

    async def test_saturated_replay_cache_preserves_live_nonces_and_fails_closed(self):
        # A full bounded cache must not evict a still-fresh nonce, otherwise a
        # captured request could be replayed before its timestamp expires.
        self.server_a._replay_capacity = 1
        first_nonce = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        first_payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "replica-a",
            "nonce": first_nonce,
            "issued_at": int(time.time()),
            "query": base64.b64encode(b"\\x00" * 4).decode("ascii"),
        }
        first_frame = _signed_envelope(first_payload, self.key_a, _REQUEST_DOMAIN)

        async def submit(frame):
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server_a.port)
            try:
                writer.write(frame)
                await writer.drain()
                return await asyncio.wait_for(reader.read(1024), timeout=2)
            finally:
                writer.close()
                await writer.wait_closed()

        self.assertTrue(await submit(first_frame))
        self.assertIn(first_nonce, self.server_a._seen_nonces)
        second_payload = dict(first_payload)
        second_payload["nonce"] = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        second_frame = _signed_envelope(second_payload, self.key_a, _REQUEST_DOMAIN)
        original_acquire = self.server_a._rate_limiter.acquire
        acquire_calls = 0

        def count_acquire():
            nonlocal acquire_calls
            acquire_calls += 1
            return original_acquire()

        self.server_a._rate_limiter.acquire = count_acquire
        try:
            self.assertEqual(await submit(second_frame), b"")
        finally:
            self.server_a._rate_limiter.acquire = original_acquire
        self.assertEqual(acquire_calls, 0)
        self.assertEqual(list(self.server_a._seen_nonces), [first_nonce])

    async def test_rate_limited_request_does_not_mutate_replay_cache(self):
        nonce = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        payload = {
            "protocol": "AEGIS-PIR-RPC-v1",
            "server_id": "replica-a",
            "nonce": nonce,
            "issued_at": int(time.time()),
            "query": base64.b64encode(b"\\x00" * 4).decode("ascii"),
        }
        frame = _signed_envelope(payload, self.key_a, _REQUEST_DOMAIN)
        original_acquire = self.server_a._rate_limiter.acquire
        self.server_a._rate_limiter.acquire = lambda: False
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server_a.port)
            writer.write(frame)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(1), timeout=2), b"")
            self.assertNotIn(nonce, self.server_a._seen_nonces)
            self.assertEqual(self.server_a.aggregate_stats["requests_rate_limited"], 1)
        finally:
            self.server_a._rate_limiter.acquire = original_acquire
            if writer is not None:
                writer.close()
                await writer.wait_closed()

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

    async def test_remote_tls_pir_fails_closed_even_with_legacy_override(self):
        # The legacy override is intentionally ignored. A remote endpoint must not
        # be queried until a real privacy-preserving proof of computation exists.
        import ssl

        context = ssl.create_default_context()
        remote_a = PirRpcEndpoint(
            "remote-a", "192.0.2.10", 1234, None, ssl_context=context,
        )
        remote_b = PirRpcEndpoint(
            "remote-b", "192.0.2.11", 1235, None, ssl_context=context,
        )
        for allow_override in (False, True):
            with self.subTest(allow_unverified_remote=allow_override):
                with self.assertRaisesRegex(PirRpcProtocolError, "remote PIR computation is disabled"):
                    await retrieve_two_server_pir_rpc(
                        (remote_a, remote_b), len(self.records), 3,
                        record_bytes=4, timeout_seconds=0.1,
                        allow_unverified_remote=allow_override,
                    )

    async def test_four_server_remote_tls_pir_fails_closed_even_with_legacy_override(self):
        # The four-server fault detector is not a proof system and must share the
        # same remote safety boundary as the two-server client.
        import ssl

        context = ssl.create_default_context()
        endpoints = tuple(
            PirRpcEndpoint(
                f"remote-{index}", f"192.0.2.{10 + index}", 1234 + index,
                None, ssl_context=context,
            )
            for index in range(4)
        )
        for allow_override in (False, True):
            with self.subTest(allow_unverified_remote=allow_override):
                with self.assertRaisesRegex(PirRpcProtocolError, "remote PIR computation is disabled"):
                    await retrieve_four_server_pir_rpc_checked(
                        endpoints, len(self.records), 3, record_bytes=4,
                        timeout_seconds=0.1,
                        allow_unverified_remote=allow_override,
                    )

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


    async def test_boolean_response_dimensions_are_rejected_as_malformed_json_types(self):
        # In Python, bool subclasses int and True == 1. JSON peers must not be
        # allowed to smuggle booleans into integer protocol fields.
        for malformed_field in ("item_count", "record_bytes"):
            key = secrets.token_bytes(32)

            async def handle(reader, writer, field=malformed_field, shared_key=key):
                try:
                    header = await reader.readexactly(4)
                    length = int.from_bytes(header, "big")
                    request_raw = await reader.readexactly(length)
                    request = _verify_envelope(request_raw, shared_key, _REQUEST_DOMAIN)
                    response = {
                        "protocol": "AEGIS-PIR-RPC-v1",
                        "server_id": request["server_id"],
                        "nonce": request["nonce"],
                        "answer": base64.b64encode(b"X").decode("ascii"),
                        "item_count": 1,
                        "record_bytes": 1,
                        "snapshot_sha256": "a" * 64,
                    }
                    response[field] = True
                    writer.write(_signed_envelope(response, shared_key, _RESPONSE_DOMAIN))
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            try:
                port = server.sockets[0].getsockname()[1]
                endpoint = PirRpcEndpoint("malformed-peer", "127.0.0.1", port, key)
                with self.subTest(field=malformed_field):
                    with self.assertRaisesRegex(PirRpcProtocolError, "dimensions do not match"):
                        await _query_endpoint(
                            endpoint, b"\\x00", 1, 1, timeout_seconds=1.0,
                        )
            finally:
                server.close()
                await server.wait_closed()


class StrictJsonEnvelopeTests(unittest.TestCase):
    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(PirRpcProtocolError, "duplicate key"):
            _strict_json_loads(b'{"payload":{"server_id":"good","server_id":"evil"}}')

    def test_nonstandard_json_numeric_constants_are_rejected(self):
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(constant=constant):
                with self.assertRaisesRegex(PirRpcProtocolError, "non-standard numeric constant"):
                    _strict_json_loads(b'{"value":' + constant + b"}")

    def test_duplicate_envelope_key_is_rejected_even_if_mac_matches_parsed_payload(self):
        key = secrets.token_bytes(32)
        payload = {"protocol": "AEGIS-PIR-RPC-v1"}
        mac = _mac(payload, key, _REQUEST_DOMAIN)
        payload_json = json.dumps(payload, separators=(",", ":"))
        raw = (
            '{"payload":' + payload_json
            + ',"payload":' + payload_json
            + ',"mac":' + json.dumps(mac) + '}'
        ).encode("ascii")
        with self.assertRaisesRegex(PirRpcProtocolError, "duplicate key"):
            _verify_envelope(raw, key, _REQUEST_DOMAIN)

    def test_tls_envelope_rejects_duplicate_nested_payload_key(self):
        raw = b'{"payload":{"protocol":"AEGIS-PIR-RPC-v1","protocol":"evil"}}'
        with self.assertRaisesRegex(PirRpcProtocolError, "duplicate key"):
            _verify_transport_envelope(raw, None, _RESPONSE_DOMAIN)

    def test_tls_envelope_rejects_non_utf8_json_encoding(self):
        raw = '{"payload":{"protocol":"AEGIS-PIR-RPC-v1"}}'.encode("utf-16")
        with self.assertRaises((PirRpcProtocolError, UnicodeDecodeError)):
            _verify_transport_envelope(raw, None, _RESPONSE_DOMAIN)


if __name__ == "__main__":
    unittest.main()
