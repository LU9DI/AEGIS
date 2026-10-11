"""Authenticated RPC for the two-server XOR PIR research protocol.

Two modes are supported:
- Legacy loopback mode uses per-endpoint HMAC keys and is kept for regression tests.
- TLS mode uses a verified server certificate for client authentication of the
  endpoint plus TLS confidentiality/integrity. In TLS mode no server HMAC secret is
  distributed to clients; PIR clients remain anonymous at the TLS client-certificate
  layer. Nonces and a bounded replay cache remain active at the application layer.

Remote binds are permitted only in TLS mode, with explicit ``allow_remote=True``.
This is a research transport, not a production distributed PIR service.
"""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import json
import math
from pathlib import Path
import secrets
import ssl
import tempfile
import time
from typing import Sequence

from .pir_two_server import MAX_DATABASE_BYTES, MAX_RECORDS, MAX_RECORD_BYTES, make_query_pair

PROTOCOL = "AEGIS-PIR-RPC-v1"
MAX_FRAME_BYTES = 2_000_000
NONCE_BYTES = 32
MAX_CLOCK_SKEW_SECONDS = 60
MAX_SEEN_NONCES = 65_536
MAX_ACTIVE_RPC_CONNECTIONS = 128
RPC_READ_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_REQUESTS_PER_SECOND = 100.0
DEFAULT_REQUEST_BURST = 128
MAX_REQUEST_RATE = 10_000.0
MAX_REQUEST_BURST = 10_000
_REQUEST_DOMAIN = b"AEGIS-PIR-RPC-v1/request\x00"
_RESPONSE_DOMAIN = b"AEGIS-PIR-RPC-v1/response\x00"


class PirRpcError(RuntimeError):
    """Base exception for failed PIR RPC requests."""


class PirRpcProtocolError(PirRpcError):
    """A malformed, unauthenticated, replayed, or mis-correlated RPC message."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _mac(payload: dict[str, object], key: bytes, domain: bytes) -> str:
    return hmac.new(key, domain + _canonical_json(payload), hashlib.sha256).hexdigest()


def _signed_envelope(payload: dict[str, object], key: bytes, domain: bytes) -> bytes:
    envelope = {"payload": payload, "mac": _mac(payload, key, domain)}
    encoded = _canonical_json(envelope)
    if not 0 < len(encoded) <= MAX_FRAME_BYTES:
        raise PirRpcProtocolError("message exceeds frame limit")
    return len(encoded).to_bytes(4, "big") + encoded


def _verify_envelope(raw: bytes, key: bytes, domain: bytes) -> dict[str, object]:
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PirRpcProtocolError("message is not valid JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "mac"}:
        raise PirRpcProtocolError("invalid message envelope")
    payload, supplied_mac = envelope["payload"], envelope["mac"]
    if not isinstance(payload, dict) or not isinstance(supplied_mac, str):
        raise PirRpcProtocolError("invalid message envelope fields")
    expected_mac = _mac(payload, key, domain)
    if not hmac.compare_digest(supplied_mac, expected_mac):
        raise PirRpcProtocolError("message authentication failed")
    return payload


def _pack_transport_envelope(payload: dict[str, object], key: bytes | None, domain: bytes) -> bytes:
    """Frame a message, relying on TLS for integrity when no PSK is configured."""
    if key is not None:
        return _signed_envelope(payload, key, domain)
    encoded = _canonical_json({"payload": payload})
    if not 0 < len(encoded) <= MAX_FRAME_BYTES:
        raise PirRpcProtocolError("message exceeds frame limit")
    return len(encoded).to_bytes(4, "big") + encoded


def _verify_transport_envelope(raw: bytes, key: bytes | None, domain: bytes) -> dict[str, object]:
    if key is not None:
        return _verify_envelope(raw, key, domain)
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PirRpcProtocolError("message is not valid JSON") from exc
    # This unsigned form is accepted only on a stream already protected by TLS.
    if not isinstance(envelope, dict) or set(envelope) != {"payload"}:
        raise PirRpcProtocolError("invalid TLS message envelope")
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise PirRpcProtocolError("invalid TLS message payload")
    return payload


def _validate_client_tls_context(context: ssl.SSLContext) -> None:
    if not isinstance(context, ssl.SSLContext):
        raise ValueError("ssl_context must be an ssl.SSLContext")
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("client TLS context must require certificates and hostname verification")
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        raise ValueError("client TLS minimum_version must be TLS 1.2 or newer")
    if context.maximum_version != ssl.TLSVersion.MAXIMUM_SUPPORTED and context.maximum_version < ssl.TLSVersion.TLSv1_2:
        raise ValueError("client TLS maximum_version must permit TLS 1.2 or newer")


def _validate_server_tls_context(context: ssl.SSLContext) -> None:
    if not isinstance(context, ssl.SSLContext):
        raise ValueError("ssl_context must be an ssl.SSLContext")
    if context.protocol == ssl.PROTOCOL_TLS_CLIENT:
        raise ValueError("server ssl_context must be configured for server-side TLS")
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        raise ValueError("server TLS minimum_version must be TLS 1.2 or newer")
    if context.maximum_version != ssl.TLSVersion.MAXIMUM_SUPPORTED and context.maximum_version < ssl.TLSVersion.TLSv1_2:
        raise ValueError("server TLS maximum_version must permit TLS 1.2 or newer")


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = int.from_bytes(header, "big")
    if length < 1 or length > MAX_FRAME_BYTES:
        raise PirRpcProtocolError("frame length outside accepted bounds")
    return await reader.readexactly(length)


def _write_frame(writer: asyncio.StreamWriter, framed: bytes) -> None:
    writer.write(framed)


def _decode_b64(value: object, field_name: str) -> bytes:
    if not isinstance(value, str):
        raise PirRpcProtocolError(f"{field_name} must be base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise PirRpcProtocolError(f"{field_name} is not valid base64") from exc
    return decoded


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("each PIR RPC pre-shared key must contain at least 32 bytes")


def _validate_server_id(server_id: str) -> None:
    if not isinstance(server_id, str) or not 1 <= len(server_id) <= 64:
        raise ValueError("server_id must contain 1..64 characters")
    if not all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in server_id):
        raise ValueError("server_id may contain only ASCII letters, digits, '-' and '_'")


class _GlobalTokenBucket:
    """Aggregate endpoint rate limiter that deliberately stores no client identity."""

    def __init__(self, requests_per_second: float, burst: int) -> None:
        self.rate = float(requests_per_second)
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated_at = time.monotonic()

    def acquire(self) -> bool:
        now = time.monotonic()
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated_at = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class AuthenticatedPirRpcServer:
    """One RPC endpoint over a fixed replicated database.

    Non-TLS/HMAC mode is loopback-only. TLS mode can bind remotely only when the
    caller explicitly sets ``allow_remote=True`` and does not distribute a shared
    HMAC key to clients. Anonymous TLS clients are accepted; server authentication
    is performed by the client using the configured CA and hostname.
    """

    def __init__(
        self,
        records: Sequence[bytes],
        *,
        server_id: str,
        shared_key: bytes | None = None,
        host: str = "127.0.0.1",
        replay_cache_capacity: int = MAX_SEEN_NONCES,
        ssl_context: ssl.SSLContext | None = None,
        allow_remote: bool = False,
        request_timeout_seconds: float = RPC_READ_TIMEOUT_SECONDS,
        max_requests_per_second: float = DEFAULT_MAX_REQUESTS_PER_SECOND,
        request_burst: int = DEFAULT_REQUEST_BURST,
    ) -> None:
        _validate_server_id(server_id)
        if shared_key is not None:
            _validate_key(shared_key)
        if ssl_context is not None:
            _validate_server_tls_context(ssl_context)
        if shared_key is None and ssl_context is None:
            raise ValueError("a TLS context is required when no HMAC pre-shared key is configured")
        if not isinstance(allow_remote, bool):
            raise ValueError("allow_remote must be a bool")
        if (
            not isinstance(request_timeout_seconds, (int, float))
            or isinstance(request_timeout_seconds, bool)
            or not 0.05 <= request_timeout_seconds <= 60.0
        ):
            raise ValueError("request_timeout_seconds must be within 0.05..60")
        if (
            not isinstance(max_requests_per_second, (int, float))
            or isinstance(max_requests_per_second, bool)
            or not 0.1 <= max_requests_per_second <= MAX_REQUEST_RATE
        ):
            raise ValueError(f"max_requests_per_second must be within 0.1..{MAX_REQUEST_RATE:g}")
        if (
            not isinstance(request_burst, int)
            or isinstance(request_burst, bool)
            or not 1 <= request_burst <= MAX_REQUEST_BURST
        ):
            raise ValueError(f"request_burst must be within 1..{MAX_REQUEST_BURST}")
        try:
            bind_ip = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("server host must be a numeric IP address") from exc
        if not bind_ip.is_loopback:
            if not allow_remote or ssl_context is None or shared_key is not None:
                raise ValueError("remote binds require TLS, allow_remote=True, and no client-shared HMAC key")
        if not isinstance(replay_cache_capacity, int) or isinstance(replay_cache_capacity, bool) or not 1 <= replay_cache_capacity <= MAX_SEEN_NONCES:
            raise ValueError(f"replay_cache_capacity must be within 1..{MAX_SEEN_NONCES}")
        # A nonce can remain valid for two clock-skew windows when its timestamp
        # is at the future edge of the accepted interval. Reserve enough entries
        # for the configured sustained rate over that retention period plus burst.
        required_replay_capacity = (
            math.ceil(float(max_requests_per_second) * (2 * MAX_CLOCK_SKEW_SECONDS))
            + request_burst
        )
        if replay_cache_capacity < required_replay_capacity:
            raise ValueError(
                "replay_cache_capacity must be at least "
                f"{required_replay_capacity} for the configured request rate, burst, "
                "and nonce validity window"
            )
        # Reuse the shared validation rules from the in-process PIR reference server.
        from .pir_two_server import PirReferenceServer
        self._reference = PirReferenceServer(records)
        snapshot = (
            b"AEGIS-PIR-SNAPSHOT-v1\x00"
            + self._reference.item_count.to_bytes(8, "big")
            + self._reference.record_bytes.to_bytes(8, "big")
            + b"".join(records)
        )
        self.snapshot_sha256 = hashlib.sha256(snapshot).hexdigest()
        self.server_id = server_id
        self._key = bytes(shared_key) if shared_key is not None else None
        self.ssl_context = ssl_context
        self.allow_remote = allow_remote
        self._request_timeout_seconds = float(request_timeout_seconds)
        self.host = host
        self._replay_capacity = replay_cache_capacity
        self._seen_nonces: OrderedDict[str, float] = OrderedDict()
        self._active_connections = 0
        self._rate_limiter = _GlobalTokenBucket(float(max_requests_per_second), request_burst)
        self._requests_accepted = 0
        self._requests_rate_limited = 0
        self._server: asyncio.AbstractServer | None = None
        self.port: int | None = None

    @property
    def aggregate_stats(self) -> dict[str, int]:
        """Return counters aggregated for this endpoint; no client IP or request ID is kept."""
        return {
            "requests_accepted": self._requests_accepted,
            "requests_rate_limited": self._requests_rate_limited,
            "active_connections": self._active_connections,
        }

    def rotate_tls_certificate(self, certfile: str | Path, keyfile: str | Path) -> str:
        """Rotate the certificate for new TLS handshakes without restarting the listener.

        A temporary SSLContext validates the new certificate/key pair before the live
        context is changed. Existing TLS connections keep their negotiated session;
        only handshakes started after the call use the new certificate. The caller is
        responsible for ensuring the new certificate chains to the trust roots used by
        clients and contains the expected DNS/IP SAN.
        """
        if self.ssl_context is None:
            raise RuntimeError("live certificate rotation requires a TLS server")
        if self._server is None:
            raise RuntimeError("TLS server must be started before certificate rotation")
        cert_path = Path(certfile)
        key_path = Path(keyfile)
        try:
            cert_bytes = cert_path.read_bytes()
            key_bytes = key_path.read_bytes()
            cert_pem = cert_bytes.decode("ascii")
            cert_der = ssl.PEM_cert_to_DER_cert(cert_pem)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("could not read the certificate/key pair for rotation") from exc
        if not cert_bytes or not key_bytes or len(cert_bytes) > 1_048_576 or len(key_bytes) > 1_048_576:
            raise ValueError("certificate and key files must be non-empty and at most 1 MiB each")
        fingerprint = hashlib.sha256(cert_der).hexdigest()
        # Load the exact bytes read above, not the operator's mutable paths twice.
        # Temporary files reside in a private directory and are removed after both
        # contexts have loaded the material; the private key is created mode 0600.
        with tempfile.TemporaryDirectory(prefix="aegis-pir-cert-rotation-") as temporary_dir:
            temporary = Path(temporary_dir)
            temporary_cert = temporary / "certificate.pem"
            temporary_key = temporary / "private-key.pem"
            temporary_cert.write_bytes(cert_bytes)
            temporary_key.write_bytes(key_bytes)
            temporary_cert.chmod(0o600)
            temporary_key.chmod(0o600)
            candidate = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            candidate.minimum_version = self.ssl_context.minimum_version
            candidate.maximum_version = self.ssl_context.maximum_version
            # Validate before touching the active context so mismatched/unreadable
            # pairs leave the currently served certificate unchanged.
            candidate.load_cert_chain(str(temporary_cert), str(temporary_key))
            # This is synchronous on the event loop; no handshake callback can run
            # between validation and replacement. New handshakes use the new leaf.
            self.ssl_context.load_cert_chain(str(temporary_cert), str(temporary_key))
        return fingerprint

    @property
    def item_count(self) -> int:
        return self._reference.item_count

    @property
    def record_bytes(self) -> int:
        return self._reference.record_bytes

    async def start(self) -> "AuthenticatedPirRpcServer":
        if self._server is not None:
            raise RuntimeError("PIR RPC server is already started")
        server_options: dict[str, object] = {
            "limit": MAX_FRAME_BYTES + 4,
            "ssl": self.ssl_context,
            "backlog": MAX_ACTIVE_RPC_CONNECTIONS,
        }
        if self.ssl_context is not None:
            # Keep uncompleted TLS handshakes from occupying server resources indefinitely.
            server_options["ssl_handshake_timeout"] = self._request_timeout_seconds
            server_options["ssl_shutdown_timeout"] = self._request_timeout_seconds
        self._server = await asyncio.start_server(self._handle, self.host, 0, **server_options)
        sockets = self._server.sockets or []
        if len(sockets) != 1:
            await self.close()
            raise RuntimeError("could not allocate exactly one listener socket")
        self.port = int(sockets[0].getsockname()[1])
        return self

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self.port = None

    async def __aenter__(self) -> "AuthenticatedPirRpcServer":
        return await self.start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _accept_nonce(self, nonce_text: str, issued_at: int) -> None:
        now = time.time()
        if abs(now - issued_at) > MAX_CLOCK_SKEW_SECONDS:
            raise PirRpcProtocolError("request timestamp is outside accepted window")
        # A request timestamp may be MAX_CLOCK_SKEW_SECONDS in the future.
        # It remains acceptable until another full skew window after that
        # timestamp, so retain its nonce for up to two skew windows from receipt.
        # Never evict a still-live nonce to make room: that would re-enable replay.
        cutoff = now - (2 * MAX_CLOCK_SKEW_SECONDS)
        while self._seen_nonces:
            oldest_nonce, oldest_seen = next(iter(self._seen_nonces.items()))
            if oldest_seen >= cutoff:
                break
            self._seen_nonces.pop(oldest_nonce, None)
        if nonce_text in self._seen_nonces:
            raise PirRpcProtocolError("request replay detected")
        if len(self._seen_nonces) >= self._replay_capacity:
            raise PirRpcProtocolError("replay cache is full")
        self._seen_nonces[nonce_text] = now

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Bound concurrent handlers and slow clients. asyncio creates a task per
        # accepted connection, so reject over-capacity sockets before parsing frames.
        if self._active_connections >= MAX_ACTIVE_RPC_CONNECTIONS:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            return
        self._active_connections += 1
        try:
            raw = await asyncio.wait_for(_read_frame(reader), timeout=self._request_timeout_seconds)
            payload = _verify_transport_envelope(raw, self._key, _REQUEST_DOMAIN)
            if set(payload) != {"protocol", "server_id", "nonce", "issued_at", "query"}:
                raise PirRpcProtocolError("request fields do not match the protocol")
            if payload["protocol"] != PROTOCOL or payload["server_id"] != self.server_id:
                raise PirRpcProtocolError("wrong protocol or server identity")
            nonce = _decode_b64(payload["nonce"], "nonce")
            if len(nonce) != NONCE_BYTES:
                raise PirRpcProtocolError("nonce has an invalid size")
            issued_at = payload["issued_at"]
            if not isinstance(issued_at, int) or isinstance(issued_at, bool):
                raise PirRpcProtocolError("issued_at must be an integer Unix timestamp")
            nonce_text = payload["nonce"]
            query = _decode_b64(payload["query"], "query")
            # Reject malformed masks before replay-cache mutation or rate limiting.
            self._reference.validate_query_mask(query)
            self._accept_nonce(nonce_text, issued_at)
            # An aggregate token bucket limits total endpoint work without storing
            # per-client identifiers, which could become an anonymity side channel.
            if not self._rate_limiter.acquire():
                self._requests_rate_limited += 1
                return
            answer = self._reference.answer(query)
            self._requests_accepted += 1
            response = {
                "protocol": PROTOCOL,
                "server_id": self.server_id,
                "nonce": nonce_text,
                "answer": base64.b64encode(answer).decode("ascii"),
                "item_count": self._reference.item_count,
                "record_bytes": self._reference.record_bytes,
                "snapshot_sha256": self.snapshot_sha256,
            }
            _write_frame(writer, _pack_transport_envelope(response, self._key, _RESPONSE_DOMAIN))
            await asyncio.wait_for(writer.drain(), timeout=self._request_timeout_seconds)
        except (asyncio.IncompleteReadError, OSError, asyncio.TimeoutError):
            pass
        except (PirRpcProtocolError, ValueError, TypeError, json.JSONDecodeError):
            # Fail closed: do not disclose whether identity, MAC, replay cache,
            # frame shape or query validation rejected an unauthenticated request.
            pass
        finally:
            self._active_connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass


@dataclass(frozen=True, slots=True)
class PirRpcEndpoint:
    server_id: str
    host: str
    port: int
    shared_key: bytes | None = field(default=None, repr=False)
    ssl_context: ssl.SSLContext | None = field(default=None, repr=False, compare=False)
    server_hostname: str | None = None

    def __post_init__(self) -> None:
        _validate_server_id(self.server_id)
        if self.shared_key is not None:
            _validate_key(self.shared_key)
        if self.ssl_context is not None:
            _validate_client_tls_context(self.ssl_context)
            hostname = self.server_hostname or self.host
            if not isinstance(hostname, str) or not hostname or "\x00" in hostname:
                raise ValueError("TLS server_hostname must be a non-empty hostname")
        if self.shared_key is None and self.ssl_context is None:
            raise ValueError("endpoint requires TLS or a legacy HMAC pre-shared key")
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise ValueError("endpoint host must be a numeric IP address") from exc
        if not address.is_loopback and (self.ssl_context is None or self.shared_key is not None):
            raise ValueError("remote endpoints require verified TLS and must not distribute HMAC keys")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("endpoint port must be within 1..65535")


@dataclass(frozen=True, slots=True)
class PirRpcTransfer:
    record: bytes
    server_ids: tuple[str, str]
    query_bytes_per_server: int
    response_bytes_per_server: int
    snapshot_sha256: str
    authenticated_messages: int = 4
    transport: str = "TCP loopback with HMAC-SHA256 message authentication"
    is_production_secure: bool = False


@dataclass(frozen=True, slots=True)
class RedundantPirRpcTransfer:
    """Result of comparing two independent two-server PIR reconstructions.

    This detects disagreement between pairs; it is not a cryptographic proof and
    does not protect against coordinated corruption or collusion across both pairs.
    """
    record: bytes
    server_ids: tuple[str, str, str, str]
    snapshot_sha256: str
    query_bytes_per_server: int
    response_bytes_per_server: int
    authenticated_messages: int = 8
    is_production_secure: bool = False


async def _query_endpoint(
    endpoint: PirRpcEndpoint,
    query: bytes,
    expected_item_count: int,
    expected_record_bytes: int,
    *,
    timeout_seconds: float,
) -> tuple[bytes, str]:
    nonce_text = base64.b64encode(secrets.token_bytes(NONCE_BYTES)).decode("ascii")
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "server_id": endpoint.server_id,
        "nonce": nonce_text,
        "issued_at": int(time.time()),
        "query": base64.b64encode(query).decode("ascii"),
    }
    frame = _pack_transport_envelope(payload, endpoint.shared_key, _REQUEST_DOMAIN)
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                endpoint.host,
                endpoint.port,
                limit=MAX_FRAME_BYTES + 4,
                ssl=endpoint.ssl_context,
                server_hostname=(endpoint.server_hostname or endpoint.host) if endpoint.ssl_context else None,
            ),
            timeout=timeout_seconds,
        )
        _write_frame(writer, frame)
        await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
        raw = await asyncio.wait_for(_read_frame(reader), timeout=timeout_seconds)
        response = _verify_transport_envelope(raw, endpoint.shared_key, _RESPONSE_DOMAIN)
    except PirRpcError:
        raise
    except (asyncio.TimeoutError, OSError, asyncio.IncompleteReadError, ConnectionError) as exc:
        raise PirRpcError(f"RPC failed for endpoint {endpoint.server_id}") from exc
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    if set(response) != {"protocol", "server_id", "nonce", "answer", "item_count", "record_bytes", "snapshot_sha256"}:
        raise PirRpcProtocolError("response fields do not match the protocol")
    if response["protocol"] != PROTOCOL or response["server_id"] != endpoint.server_id:
        raise PirRpcProtocolError("response identity or protocol mismatch")
    if response["nonce"] != nonce_text:
        raise PirRpcProtocolError("response nonce does not match the request")
    if response["item_count"] != expected_item_count or response["record_bytes"] != expected_record_bytes:
        raise PirRpcProtocolError("replica database dimensions do not match the client manifest")
    snapshot_sha256 = response["snapshot_sha256"]
    if not isinstance(snapshot_sha256, str) or len(snapshot_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot_sha256):
        raise PirRpcProtocolError("replica snapshot fingerprint is malformed")
    answer = _decode_b64(response["answer"], "answer")
    if len(answer) != expected_record_bytes:
        raise PirRpcProtocolError("response has an unexpected record size")
    return answer, snapshot_sha256


def _is_loopback_host(host: str) -> bool:
    """Return False for DNS names and malformed literals; never trust them as loopback."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def retrieve_two_server_pir_rpc(
    endpoints: Sequence[PirRpcEndpoint],
    item_count: int,
    target_index: int,
    *,
    record_bytes: int,
    timeout_seconds: float = 5.0,
    expected_snapshot_sha256: str | None = None,
    allow_unverified_remote: bool = False,
) -> PirRpcTransfer:
    """Retrieve one record from two distinct authenticated RPC endpoints.

    The selected index is used only to form client-side query masks and is never
    present in an RPC request. Use TLS endpoints for remote hosts; HMAC-only mode
    is retained only for local research compatibility. TLS does not prove correct
    PIR computation. All non-loopback retrieval is disabled until a real
    privacy-preserving proof of computation is integrated. The legacy
    allow_unverified_remote parameter is retained for API compatibility only and
    cannot bypass this safety boundary.
    """
    if not isinstance(allow_unverified_remote, bool):
        raise ValueError("allow_unverified_remote must be a bool")
    if not isinstance(item_count, int) or isinstance(item_count, bool) or not 1 <= item_count <= MAX_RECORDS:
        raise ValueError(f"item_count must be within 1..{MAX_RECORDS}")
    if not isinstance(record_bytes, int) or isinstance(record_bytes, bool) or not 1 <= record_bytes <= MAX_RECORD_BYTES:
        raise ValueError(f"record_bytes must be within 1..{MAX_RECORD_BYTES}")
    if item_count * record_bytes > MAX_DATABASE_BYTES:
        raise ValueError(f"database exceeds {MAX_DATABASE_BYTES} bytes")
    if not isinstance(target_index, int) or isinstance(target_index, bool) or not 0 <= target_index < item_count:
        raise ValueError("target_index is outside the database")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0.05 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be within 0.05..60")
    if expected_snapshot_sha256 is not None and (
        not isinstance(expected_snapshot_sha256, str)
        or len(expected_snapshot_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in expected_snapshot_sha256)
    ):
        raise ValueError("expected_snapshot_sha256 must be a lowercase SHA-256 hex digest")
    if not isinstance(endpoints, (tuple, list)) or len(endpoints) != 2 or not all(isinstance(e, PirRpcEndpoint) for e in endpoints):
        raise ValueError("exactly two PirRpcEndpoint entries are required")
    a, b = endpoints
    if any(not _is_loopback_host(endpoint.host) for endpoint in endpoints):
        raise PirRpcProtocolError(
            "remote PIR computation is disabled: TLS and snapshot fingerprints do not prove correct computation; "
            "no unverified-remote override is permitted"
        )
    if a.server_id == b.server_id:
        raise ValueError("PIR endpoints must have distinct server IDs")
    if (a.host, a.port) == (b.host, b.port):
        raise ValueError("PIR endpoints must use distinct host/port pairs")
    if a.shared_key is not None and b.shared_key is not None and hmac.compare_digest(a.shared_key, b.shared_key):
        raise ValueError("PIR endpoints must use distinct pre-shared keys")
    if (a.shared_key is None) != (b.shared_key is None):
        raise ValueError("both PIR endpoints must use the same transport mode (TLS or legacy HMAC)")
    if (a.ssl_context is None) != (b.ssl_context is None):
        raise ValueError("both PIR endpoints must use the same transport mode (TLS or legacy HMAC)")

    query_a, query_b = make_query_pair(item_count, target_index)
    (answer_a, snapshot_a), (answer_b, snapshot_b) = await asyncio.gather(
        _query_endpoint(a, query_a, item_count, record_bytes, timeout_seconds=float(timeout_seconds)),
        _query_endpoint(b, query_b, item_count, record_bytes, timeout_seconds=float(timeout_seconds)),
    )
    if not hmac.compare_digest(snapshot_a, snapshot_b):
        raise PirRpcProtocolError("replicas do not hold the same database snapshot")
    if expected_snapshot_sha256 is not None and not hmac.compare_digest(
        snapshot_a, expected_snapshot_sha256
    ):
        raise PirRpcProtocolError("replica snapshot does not match the caller-pinned fingerprint")
    record = bytes(left ^ right for left, right in zip(answer_a, answer_b, strict=True))
    return PirRpcTransfer(
        record=record,
        server_ids=(a.server_id, b.server_id),
        query_bytes_per_server=len(query_a),
        response_bytes_per_server=record_bytes,
        snapshot_sha256=snapshot_a,
        transport=(
            "TLS 1.2+ encrypted stream with verified server certificate/hostname; no client certificate"
            if a.ssl_context is not None
            else "legacy loopback TCP with HMAC-SHA256 message authentication; not encrypted"
        ),
    )



async def retrieve_four_server_pir_rpc_checked(
    endpoints: Sequence[PirRpcEndpoint],
    item_count: int,
    target_index: int,
    *,
    record_bytes: int,
    timeout_seconds: float = 5.0,
    expected_snapshot_sha256: str | None = None,
    allow_unverified_remote: bool = False,
) -> RedundantPirRpcTransfer:
    """Compare two independently randomized 2-server PIR reconstructions.

    This is a defense-in-depth *fault detector*, not verifiable PIR. Under the
    limited assumption that at most one of four replicas is faulty and each pair
    remains non-colluding, a corrupt answer in one pair should disagree with the
    independent reconstruction. Coordinated corruption, common-mode bugs, and
    collusion can defeat this check. Four endpoints and doubled traffic are required.
    """
    if not isinstance(endpoints, (tuple, list)) or len(endpoints) != 4 or not all(
        isinstance(endpoint, PirRpcEndpoint) for endpoint in endpoints
    ):
        raise ValueError("exactly four PirRpcEndpoint entries are required")
    if len({endpoint.server_id for endpoint in endpoints}) != 4:
        raise ValueError("all four PIR endpoints must have distinct server IDs")
    if len({(endpoint.host, endpoint.port) for endpoint in endpoints}) != 4:
        raise ValueError("all four PIR endpoints must use distinct host/port pairs")
    keys = [endpoint.shared_key for endpoint in endpoints if endpoint.shared_key is not None]
    if len(keys) != len(set(keys)):
        raise ValueError("all legacy HMAC endpoints must use distinct pre-shared keys")
    if len({endpoint.ssl_context is None for endpoint in endpoints}) != 1:
        raise ValueError("all four PIR endpoints must use the same transport mode")
    first, second = await asyncio.gather(
        retrieve_two_server_pir_rpc(
            endpoints[:2], item_count, target_index, record_bytes=record_bytes,
            timeout_seconds=timeout_seconds,
            expected_snapshot_sha256=expected_snapshot_sha256,
            allow_unverified_remote=allow_unverified_remote,
        ),
        retrieve_two_server_pir_rpc(
            endpoints[2:], item_count, target_index, record_bytes=record_bytes,
            timeout_seconds=timeout_seconds,
            expected_snapshot_sha256=expected_snapshot_sha256,
            allow_unverified_remote=allow_unverified_remote,
        ),
    )
    if not hmac.compare_digest(first.snapshot_sha256, second.snapshot_sha256):
        raise PirRpcProtocolError("independent PIR pairs report different snapshot fingerprints")
    if not hmac.compare_digest(first.record, second.record):
        raise PirRpcProtocolError("independent PIR reconstructions disagree; possible faulty replica")
    return RedundantPirRpcTransfer(
        record=first.record,
        server_ids=(*first.server_ids, *second.server_ids),
        snapshot_sha256=first.snapshot_sha256,
        query_bytes_per_server=first.query_bytes_per_server,
        response_bytes_per_server=first.response_bytes_per_server,
        authenticated_messages=first.authenticated_messages + second.authenticated_messages,
    )


def recover_colluded_index(query_a: bytes, query_b: bytes, item_count: int) -> int:
    """Test helper illustrating why collusion breaks privacy; not part of the RPC API."""
    if not isinstance(item_count, int) or isinstance(item_count, bool) or not 1 <= item_count <= MAX_RECORDS:
        raise ValueError(f"item_count must be within 1..{MAX_RECORDS}")
    _mask_size = (item_count + 7) // 8
    if not isinstance(query_a, bytes) or not isinstance(query_b, bytes) or len(query_a) != _mask_size or len(query_b) != _mask_size:
        raise ValueError("query masks do not match item_count")
    combined = int.from_bytes(bytes(a ^ b for a, b in zip(query_a, query_b, strict=True)), "little")
    if combined <= 0 or combined & (combined - 1) or combined >= (1 << item_count):
        raise ValueError("query masks do not combine to a valid one-hot index")
    return combined.bit_length() - 1
