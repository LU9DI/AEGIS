from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import unittest

from anonlab.pir_rpc import (
    AuthenticatedPirRpcServer,
    PirRpcEndpoint,
    PirRpcError,
    retrieve_two_server_pir_rpc,
    _REQUEST_DOMAIN,
    _pack_transport_envelope,
    _verify_transport_envelope,
)


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL CLI is required for local TLS integration certificate")
class PirRpcTlsTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory(prefix="aegis-pir-tls-test-")
        cls.directory = Path(cls.tempdir.name)
        cls.ca_cert = cls.directory / "test-ca.pem"
        cls.ca_key = cls.directory / "test-ca-key.pem"
        openssl = shutil.which("openssl") or "openssl"
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(cls.ca_key),
             "-out", str(cls.ca_cert), "-days", "1", "-subj", "/CN=AEGIS PIR test CA",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
            check=True, capture_output=True, text=True,
        )
        os.chmod(cls.ca_key, 0o600)
        cls.cert_paths: dict[str, tuple[Path, Path]] = {}
        for label in ("a", "b"):
            name = f"replica-{label}.test"
            key = cls.directory / f"{label}-key.pem"
            csr = cls.directory / f"{label}.csr.pem"
            cert = cls.directory / f"{label}-cert.pem"
            ext = cls.directory / f"{label}-extensions.cnf"
            subprocess.run(
                [openssl, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                 "-out", str(csr), "-subj", f"/CN={name}"],
                check=True, capture_output=True, text=True,
            )
            ext.write_text(
                "subjectAltName=DNS:" + name + ",IP:127.0.0.1\n"
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n",
                encoding="ascii",
            )
            subprocess.run(
                [openssl, "x509", "-req", "-in", str(csr), "-CA", str(cls.ca_cert),
                 "-CAkey", str(cls.ca_key), "-CAcreateserial", "-out", str(cert), "-days", "1",
                 "-sha256", "-extfile", str(ext)],
                check=True, capture_output=True, text=True,
            )
            os.chmod(key, 0o600)
            cls.cert_paths[label] = (cert, key)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def setUp(self) -> None:
        self.records = tuple(bytes([i, 255 - i, i ^ 0xA5]) for i in range(24))
        self.server_context_a = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_context_a.minimum_version = ssl.TLSVersion.TLSv1_2
        self.server_context_a.load_cert_chain(*(str(value) for value in self.cert_paths["a"]))
        self.server_context_b = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_context_b.minimum_version = ssl.TLSVersion.TLSv1_2
        self.server_context_b.load_cert_chain(*(str(value) for value in self.cert_paths["b"]))
        self.client_context = ssl.create_default_context(cafile=str(self.ca_cert))
        self.client_context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.server_a = None
        self.server_b = None

    async def asyncTearDown(self) -> None:
        if self.server_a is not None:
            await self.server_a.close()
        if self.server_b is not None:
            await self.server_b.close()

    def _issue_server_certificate(self, label: str, dns_name: str) -> tuple[Path, Path]:
        openssl = shutil.which("openssl") or "openssl"
        key = self.directory / f"{label}-key.pem"
        csr = self.directory / f"{label}.csr.pem"
        cert = self.directory / f"{label}-cert.pem"
        ext = self.directory / f"{label}-extensions.cnf"
        subprocess.run(
            [openssl, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
             "-out", str(csr), "-subj", f"/CN={dns_name}"],
            check=True, capture_output=True, text=True,
        )
        ext.write_text(
            f"subjectAltName=DNS:{dns_name},IP:127.0.0.1\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n",
            encoding="ascii",
        )
        subprocess.run(
            [openssl, "x509", "-req", "-in", str(csr), "-CA", str(self.ca_cert),
             "-CAkey", str(self.ca_key), "-CAcreateserial", "-out", str(cert), "-days", "1",
             "-sha256", "-extfile", str(ext)],
            check=True, capture_output=True, text=True,
        )
        os.chmod(key, 0o600)
        return cert, key

    async def _peer_certificate_fingerprint(self, endpoint: PirRpcEndpoint) -> str:
        reader, writer = await asyncio.open_connection(
            endpoint.host, endpoint.port, ssl=endpoint.ssl_context,
            server_hostname=endpoint.server_hostname,
        )
        try:
            ssl_object = writer.get_extra_info("ssl_object")
            self.assertIsNotNone(ssl_object)
            cert_der = ssl_object.getpeercert(binary_form=True)
            self.assertTrue(cert_der)
            return hashlib.sha256(cert_der).hexdigest()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _start_servers(self) -> tuple[PirRpcEndpoint, PirRpcEndpoint]:
        self.server_a = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-a", ssl_context=self.server_context_a
        ).start()
        self.server_b = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-b", ssl_context=self.server_context_b
        ).start()
        assert self.server_a.port is not None and self.server_b.port is not None
        return (
            PirRpcEndpoint(
                "replica-a", "127.0.0.1", self.server_a.port,
                ssl_context=self.client_context, server_hostname="replica-a.test",
            ),
            PirRpcEndpoint(
                "replica-b", "127.0.0.1", self.server_b.port,
                ssl_context=self.client_context, server_hostname="replica-b.test",
            ),
        )

    async def test_tls_transport_retrieves_record_without_client_shared_hmac_keys(self):
        endpoints = await self._start_servers()
        result = await retrieve_two_server_pir_rpc(endpoints, len(self.records), 11, record_bytes=3, timeout_seconds=2)
        self.assertEqual(result.record, self.records[11])
        self.assertIn("TLS 1.2+ encrypted", result.transport)
        self.assertIsNone(endpoints[0].shared_key)
        self.assertEqual(result.server_ids, ("replica-a", "replica-b"))

    async def test_live_tls_certificate_rotation_changes_new_handshakes(self):
        endpoints = await self._start_servers()
        old_fingerprint = await self._peer_certificate_fingerprint(endpoints[0])
        replacement_cert, replacement_key = self._issue_server_certificate("a-rotated", "replica-a.test")

        reported_fingerprint = self.server_a.rotate_tls_certificate(replacement_cert, replacement_key)
        new_fingerprint = await self._peer_certificate_fingerprint(endpoints[0])

        self.assertNotEqual(old_fingerprint, new_fingerprint)
        self.assertEqual(reported_fingerprint, new_fingerprint)
        result = await retrieve_two_server_pir_rpc(
            endpoints, len(self.records), 7, record_bytes=3, timeout_seconds=2
        )
        self.assertEqual(result.record, self.records[7])

    async def test_failed_certificate_rotation_leaves_active_certificate_unchanged(self):
        endpoints = await self._start_servers()
        old_fingerprint = await self._peer_certificate_fingerprint(endpoints[0])
        # A certificate paired with the other replica's private key must fail validation.
        with self.assertRaises(ssl.SSLError):
            self.server_a.rotate_tls_certificate(self.cert_paths["a"][0], self.cert_paths["b"][1])

        current_fingerprint = await self._peer_certificate_fingerprint(endpoints[0])
        self.assertEqual(current_fingerprint, old_fingerprint)
        result = await retrieve_two_server_pir_rpc(
            endpoints, len(self.records), 8, record_bytes=3, timeout_seconds=2
        )
        self.assertEqual(result.record, self.records[8])

    async def test_endpoint_global_rate_limit_rejects_excess_without_client_identity_state(self):
        self.server_a = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-a", ssl_context=self.server_context_a,
            max_requests_per_second=0.1, request_burst=1,
        ).start()
        self.server_b = await AuthenticatedPirRpcServer(
            self.records, server_id="replica-b", ssl_context=self.server_context_b,
            max_requests_per_second=100.0, request_burst=16,
        ).start()
        endpoints = (
            PirRpcEndpoint("replica-a", "127.0.0.1", self.server_a.port,
                           ssl_context=self.client_context, server_hostname="replica-a.test"),
            PirRpcEndpoint("replica-b", "127.0.0.1", self.server_b.port,
                           ssl_context=self.client_context, server_hostname="replica-b.test"),
        )
        first = await retrieve_two_server_pir_rpc(endpoints, len(self.records), 4, record_bytes=3, timeout_seconds=2)
        self.assertEqual(first.record, self.records[4])
        with self.assertRaises(PirRpcError):
            await retrieve_two_server_pir_rpc(endpoints, len(self.records), 5, record_bytes=3, timeout_seconds=2)
        await asyncio.sleep(0.01)
        stats = self.server_a.aggregate_stats
        self.assertEqual(stats["requests_accepted"], 1)
        self.assertGreaterEqual(stats["requests_rate_limited"], 1)
        self.assertEqual(stats["active_connections"], 0)
        self.assertNotIn("client_ip", stats)
        self.assertNotIn("peer_address", stats)

    async def test_rate_limit_configuration_is_bounded(self):
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(
                self.records, server_id="low-rate", ssl_context=self.server_context_a,
                max_requests_per_second=0.0,
            )
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(
                self.records, server_id="high-burst", ssl_context=self.server_context_a,
                request_burst=10001,
            )

    async def test_authenticated_tls_replica_can_still_lie_about_its_computation(self):
        # Red-team limitation test: TLS proves endpoint identity and protects transport,
        # but does not prove that an authenticated server computed its PIR answer honestly.
        endpoints = await self._start_servers()
        original_answer = self.server_b._reference.answer
        self.server_b._reference.answer = lambda query: bytes(
            byte ^ 0x01 for byte in original_answer(query)
        )
        transfer = await retrieve_two_server_pir_rpc(
            endpoints, len(self.records), 9, record_bytes=3, timeout_seconds=2
        )
        self.assertNotEqual(transfer.record, self.records[9])
        self.assertEqual(transfer.snapshot_sha256, self.server_a.snapshot_sha256)

    async def test_tls_message_envelope_has_no_client_shared_hmac(self):
        payload = {"protocol": "AEGIS-PIR-RPC-v1", "server_id": "replica-a", "query": "AA=="}
        frame = _pack_transport_envelope(payload, None, _REQUEST_DOMAIN)
        decoded = _verify_transport_envelope(frame[4:], None, _REQUEST_DOMAIN)
        self.assertEqual(decoded, payload)
        self.assertNotIn(b'"mac"', frame)

    async def test_wrong_hostname_fails_closed_even_when_ca_is_trusted(self):
        endpoints = await self._start_servers()
        wrong_name = (
            PirRpcEndpoint("replica-a", "127.0.0.1", endpoints[0].port,
                           ssl_context=self.client_context, server_hostname="not-replica-a.test"),
            endpoints[1],
        )
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        handshake_errors = []
        loop.set_exception_handler(lambda _loop, context: handshake_errors.append(context))
        try:
            with self.assertRaises(PirRpcError):
                await retrieve_two_server_pir_rpc(wrong_name, len(self.records), 11, record_bytes=3, timeout_seconds=2)
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)
        self.assertTrue(all(isinstance(item.get("exception"), ConnectionResetError) for item in handshake_errors))

    async def test_untrusted_server_certificate_fails_closed(self):
        endpoints = await self._start_servers()
        untrusted = ssl.create_default_context()  # deliberately does not trust our test CA
        untrusted.minimum_version = ssl.TLSVersion.TLSv1_2
        bad = (
            PirRpcEndpoint("replica-a", "127.0.0.1", endpoints[0].port, ssl_context=untrusted, server_hostname="replica-a.test"),
            endpoints[1],
        )
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        handshake_errors = []
        loop.set_exception_handler(lambda _loop, context: handshake_errors.append(context))
        try:
            with self.assertRaises(PirRpcError):
                await retrieve_two_server_pir_rpc(bad, len(self.records), 11, record_bytes=3, timeout_seconds=2)
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)
        self.assertTrue(all(isinstance(item.get("exception"), ConnectionResetError) for item in handshake_errors))

    async def test_tls_client_context_must_verify_certificate_and_hostname(self):
        insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        insecure.minimum_version = ssl.TLSVersion.TLSv1_2
        with self.assertRaises(ValueError):
            PirRpcEndpoint("replica-a", "127.0.0.1", 12345, ssl_context=insecure, server_hostname="replica-a.test")

    async def test_remote_bind_and_endpoint_require_tls_without_distributed_hmac_key(self):
        # Construct-only test: do not bind a public interface during unit tests.
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(self.records, server_id="unsafe", host="0.0.0.0", shared_key=b"x" * 32)
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(
                self.records, server_id="missing-allow", host="0.0.0.0", ssl_context=self.server_context_a
            )
        with self.assertRaises(ValueError):
            AuthenticatedPirRpcServer(
                self.records, server_id="key-distribution", host="0.0.0.0", shared_key=b"x" * 32,
                ssl_context=self.server_context_a, allow_remote=True,
            )
        server = AuthenticatedPirRpcServer(
            self.records, server_id="tls-remote", host="192.0.2.10", ssl_context=self.server_context_a,
            allow_remote=True,
        )
        self.assertTrue(server.allow_remote)
        endpoint = PirRpcEndpoint(
            "remote", "192.0.2.11", 443, ssl_context=self.client_context, server_hostname="replica-a.test"
        )
        self.assertIsNone(endpoint.shared_key)
        with self.assertRaises(ValueError):
            PirRpcEndpoint("remote", "192.0.2.11", 443, shared_key=b"x" * 32)


if __name__ == "__main__":
    unittest.main()
