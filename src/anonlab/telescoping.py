"""Loopback-only telescoping circuit-extension proof of concept.

The client opens a single TCP connection to the guard. Each extension request
is encrypted for the current last relay and carried through the already-built
circuit. Earlier relays see only a FORWARD command and opaque downstream bytes.
This harness uses the project's ntor-derived handshake experiment and custom
legacy MALEBOLGE v1 AEAD framing (retained for protocol compatibility); it is not Tor-compatible or production-safe.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import math
import os
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .ntor_experiment import (
    CLIENT_HANDSHAKE_BYTES,
    NtorClientState,
    NtorReplayGuard,
    NtorSessionKeys,
    _raw_public_key,
    client_finish,
    client_start,
    relay_respond,
)
from .onion_protocol import MAX_FRAME_BYTES, frame, open_sealed, seal

BOOTSTRAP_CREATE = b"C"
BOOTSTRAP_CREATED = b"c"
LINK_HELLO = b"L"
LINK_AUTH = b"l"
LINK_CLIENT_DOMAIN = b"MALEBOLGE/link-auth/client/v1\x00"
LINK_SERVER_DOMAIN = b"MALEBOLGE/link-auth/server/v1\x00"
LINK_NONCE_BYTES = 32
LINK_SIGNATURE_BYTES = 64
LINK_MAX_AUTHENTICATIONS = 100_000
LINK_DESCRIPTOR_MAX_BYTES = 16_384
REQUEST_AAD_PREFIX = b"MALEBOLGE/telescope/request/v1/"
RESPONSE_AAD_PREFIX = b"MALEBOLGE/telescope/response/v1/"
_COMMAND_HEADER = struct.Struct("!QIB")  # per-hop sequence, per-hop stream id, operation
_PORT = struct.Struct("!H")
_LEN32 = struct.Struct("!I")
_LEN16 = struct.Struct("!H")
MAX_CONTROL_BYTES = 4096
MAX_DATA_BYTES = 1 * 1024 * 1024
MAX_HOPS = 5
MAX_COMMANDS_PER_CIRCUIT = 4096
DEFAULT_MAX_ACTIVE_CONNECTIONS = 64
_RESPONSE_HEADER = struct.Struct("!QII")  # sequence, stream id, response length
_LINK_RESPONSE_HEADER = struct.Struct("!QIB")  # seq, stream id, message kind
_FORWARD_HEADER = struct.Struct("!QIBI")  # downstream sequence, stream id, kind, packet length
_STREAM_ID = struct.Struct("!I")
FORWARD_DATA = 0
FORWARD_CANCEL = 1
FORWARD_OPEN_STREAM = 2
FORWARD_START_STREAM = 3
FORWARD_WRITE_STREAM = 4
FORWARD_HALF_CLOSE_STREAM = 5
FORWARD_CLOSE_STREAM = 6
FORWARD_WINDOW_UPDATE = 7
LINK_RESPONSE = 0
LINK_EVENT_DATA = 1
LINK_EVENT_EOF = 2
STREAM_CHUNK_BYTES = 16 * 1024
# Larger write batches amortize one acknowledged circuit command over more useful bytes.
# The read/event path remains 16 KiB to keep response buffering bounded and predictable.
# Larger command batches reduce acknowledged round trips; hard-capped to bound transient memory.
STREAM_WRITE_MAX_BYTES = 256 * 1024
MAX_PIPELINE_DEPTH = 4
MAX_PIPELINED_WRITE_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_PIPELINED_WRITE_COMMANDS = 512
MAX_RELAY_INFLIGHT_WRITE_COMMANDS_PER_STREAM = 4
MAX_RELAY_INFLIGHT_WRITE_BYTES_PER_STREAM = 2 * 1024 * 1024
MAX_RELAY_TOTAL_INFLIGHT_WRITE_BYTES = 16 * 1024 * 1024
INITIAL_STREAM_WINDOW_BYTES = 64 * 1024
MAX_STREAM_WINDOW_BYTES = 256 * 1024
# Coalesce consumed-byte credits to reduce control commands on fast streams.
# A short timer bounds stalls when the peer is slow or the stream is sparse.
WINDOW_UPDATE_BATCH_BYTES = 64 * 1024
WINDOW_UPDATE_MAX_DELAY_SECONDS = 0.002
MAX_STREAM_EVENT_QUEUE = 8
_EVENT_FORWARD_HEADER = struct.Struct("!QIBI")  # child seq, child sid, event kind, packet length
_STREAM_OPEN_HEADER = struct.Struct("!B")
MAX_ACTIVE_STREAMS = 128
# The client scheduler queues commands across streams and dispatches a bounded
# round-robin batch. The queue cap includes queued plus currently-dispatched jobs.
MAX_SCHEDULED_WRITE_COMMANDS = 512
MAX_SCHEDULED_WRITE_BYTES = 8 * 1024 * 1024
MAX_SCHEDULER_DRAIN_COMMANDS = 32
MAX_SCHEDULER_TRACE_ITEMS = 8192


def relay_id_for(identity_digest: bytes) -> str:
    if not isinstance(identity_digest, bytes) or len(identity_digest) != 20:
        raise ValueError("relay identity digest must contain exactly 20 bytes")
    return identity_digest.hex()


def _aad(prefix: bytes, relay_id: str) -> bytes:
    return prefix + relay_id.encode("ascii")


def _ensure_loopback(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("telescoping lab accepts only literal loopback IP addresses") from exc
    if not address.is_loopback or address.version != 4:
        raise ValueError("telescoping lab is IPv4-loopback-only")


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    length = int.from_bytes(header, "big")
    if length > MAX_FRAME_BYTES:
        raise ValueError("telescoping frame exceeds its size limit")
    return await reader.readexactly(length)


def _seal_reply(key: bytes, relay_id: str, sequence: int, stream_id: int, payload: bytes) -> bytes:
    if len(payload) > MAX_FRAME_BYTES - _RESPONSE_HEADER.size:
        raise ValueError("response exceeds the telescoping frame limit")
    body = _RESPONSE_HEADER.pack(sequence, stream_id, len(payload)) + payload
    return seal(key, body, _aad(RESPONSE_AAD_PREFIX, relay_id))


def _open_reply(
    key: bytes, relay_id: str, sequence: int, envelope: bytes, stream_id: int = 0
) -> bytes:
    plaintext = open_sealed(key, envelope, _aad(RESPONSE_AAD_PREFIX, relay_id))
    if len(plaintext) < _RESPONSE_HEADER.size:
        raise ValueError("response envelope is truncated")
    actual_sequence, actual_stream_id, length = _RESPONSE_HEADER.unpack_from(plaintext)
    if actual_sequence != sequence:
        raise ValueError("response sequence mismatch")
    if actual_stream_id != stream_id:
        raise ValueError("response stream id mismatch")
    payload = plaintext[_RESPONSE_HEADER.size:]
    if len(payload) != length or length > MAX_FRAME_BYTES - _RESPONSE_HEADER.size:
        raise ValueError("response length is invalid")
    return payload


def _encode_link_response(
    sequence: int, stream_id: int, envelope: bytes, *, kind: int = LINK_RESPONSE
) -> bytes:
    """Encode hop-local response/event metadata outside the AEAD envelope.

    This local framing is not an anonymity boundary: the adjacent relay can
    observe timing, sizes, stream identifiers, and event direction.
    """
    if not 0 <= sequence < (1 << 64) or not 0 <= stream_id < (1 << 32):
        raise ValueError("invalid link response correlation fields")
    if kind not in (LINK_RESPONSE, LINK_EVENT_DATA, LINK_EVENT_EOF):
        raise ValueError("invalid link message kind")
    if len(envelope) < 28 or len(envelope) > MAX_FRAME_BYTES:
        raise ValueError("link envelope has an invalid length")
    return _LINK_RESPONSE_HEADER.pack(sequence, stream_id, kind) + envelope


def _decode_link_message(packet: bytes) -> tuple[int, int, int, bytes]:
    if len(packet) < _LINK_RESPONSE_HEADER.size + 28:
        raise ValueError("link response is truncated")
    sequence, stream_id, kind = _LINK_RESPONSE_HEADER.unpack_from(packet)
    if kind not in (LINK_RESPONSE, LINK_EVENT_DATA, LINK_EVENT_EOF):
        raise ValueError("unknown link message kind")
    return sequence, stream_id, kind, packet[_LINK_RESPONSE_HEADER.size:]


def _decode_link_response(packet: bytes) -> tuple[int, int, bytes]:
    """Decode a regular solicited response; intentionally excludes events."""
    sequence, stream_id, kind, envelope = _decode_link_message(packet)
    if kind != LINK_RESPONSE:
        raise ValueError("expected a solicited link response")
    return sequence, stream_id, envelope


@dataclass(frozen=True, slots=True)
class RelayDescriptor:
    """Endpoint descriptor; identity_public_key is required for authenticated links."""

    host: str
    port: int
    identity_digest: bytes
    onion_public_key: bytes
    identity_public_key: bytes | None = None
    signed_descriptor_json: bytes | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _ensure_loopback(self.host)
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError("relay port must be within 1..65535")
        if not isinstance(self.identity_digest, bytes) or len(self.identity_digest) != 20:
            raise ValueError("relay identity digest must contain exactly 20 bytes")
        if not isinstance(self.onion_public_key, bytes) or len(self.onion_public_key) != 32:
            raise ValueError("relay onion public key must contain exactly 32 bytes")
        if self.identity_public_key is not None:
            if not isinstance(self.identity_public_key, bytes) or len(self.identity_public_key) != 32:
                raise ValueError("relay identity public key must contain exactly 32 bytes")
            expected = hashlib.sha256(
                b"MALEBOLGE/relay-identity/v1\x00" + self.identity_public_key
            ).digest()[:20]
            if not hmac.compare_digest(expected, self.identity_digest):
                raise ValueError("relay identity digest does not match identity public key")
        if self.signed_descriptor_json is not None:
            if not isinstance(self.signed_descriptor_json, bytes):
                raise ValueError("signed directory descriptor must be encoded bytes")
            if not 1 <= len(self.signed_descriptor_json) <= LINK_DESCRIPTOR_MAX_BYTES:
                raise ValueError("signed directory descriptor exceeds its size limit")

    @property
    def relay_id(self) -> str:
        return relay_id_for(self.identity_digest)


@dataclass(slots=True)
class ClientHop:
    descriptor: RelayDescriptor
    keys: NtorSessionKeys
    next_sequence: int = 0


@dataclass(slots=True)
class RelayObservation:
    operation: str
    target_port: int | None


class LinkReplayGuard:
    """Bounded no-eviction replay guard for authenticated transport hellos."""

    def __init__(self, max_authentications: int = LINK_MAX_AUTHENTICATIONS) -> None:
        if not isinstance(max_authentications, int) or isinstance(max_authentications, bool) or max_authentications < 1:
            raise ValueError("max_authentications must be a positive integer")
        self._max_authentications = max_authentications
        self._seen: set[tuple[bytes, bytes]] = set()

    def claim(self, peer_identity: bytes, nonce: bytes) -> None:
        if len(peer_identity) != 20 or len(nonce) != LINK_NONCE_BYTES:
            raise ValueError("link authentication replay token has an invalid length")
        token = (peer_identity, nonce)
        if token in self._seen:
            raise ValueError("replayed link-authentication nonce")
        if len(self._seen) >= self._max_authentications:
            raise ValueError("link authentication replay guard is full; fail closed")
        self._seen.add(token)


def _ed25519_raw_public(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _link_hello(
    target: RelayDescriptor,
    *,
    initiator_identity_private_key: Ed25519PrivateKey | None = None,
    initiator_directory_descriptor: bytes | None = None,
    nonce: bytes | None = None,
) -> bytes:
    """Build a target-bound hello, optionally carrying a signed peer descriptor.

    Clients use mode 0 and reveal no persistent identity. Relay initiators use
    mode 1 and sign the full hello, including the directory certificate, so the
    receiver can authenticate both proof of key possession and authority
    authorization from the same transcript.
    """
    if target.identity_public_key is None:
        raise ValueError("authenticated transport requires a pinned relay identity public key")
    nonce_value = os.urandom(LINK_NONCE_BYTES) if nonce is None else nonce
    if not isinstance(nonce_value, bytes) or len(nonce_value) != LINK_NONCE_BYTES:
        raise ValueError("link authentication nonce must contain 32 bytes")
    if initiator_directory_descriptor is not None:
        if not isinstance(initiator_directory_descriptor, bytes):
            raise ValueError("initiator directory descriptor must be encoded bytes")
        if not 1 <= len(initiator_directory_descriptor) <= LINK_DESCRIPTOR_MAX_BYTES:
            raise ValueError("initiator directory descriptor exceeds its size limit")
    if initiator_identity_private_key is None:
        if initiator_directory_descriptor is not None:
            raise ValueError("anonymous client hello cannot include a relay descriptor")
        mode = 0
        initiator_id = bytes(20)
        initiator_public = bytes(32)
        descriptor = b""
        unsigned = (
            LINK_HELLO + bytes([mode]) + target.identity_digest + initiator_id
            + initiator_public + nonce_value + _LEN16.pack(0) + descriptor
        )
        signature = bytes(LINK_SIGNATURE_BYTES)
    else:
        mode = 1
        initiator_public = _ed25519_raw_public(initiator_identity_private_key.public_key())
        initiator_id = hashlib.sha256(b"MALEBOLGE/relay-identity/v1\x00" + initiator_public).digest()[:20]
        descriptor = initiator_directory_descriptor or b""
        unsigned = (
            LINK_HELLO + bytes([mode]) + target.identity_digest + initiator_id
            + initiator_public + nonce_value + _LEN16.pack(len(descriptor)) + descriptor
        )
        signature = initiator_identity_private_key.sign(LINK_CLIENT_DOMAIN + unsigned)
    return unsigned + signature


async def _authenticate_relay_endpoint(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target: RelayDescriptor,
    *,
    initiator_identity_private_key: Ed25519PrivateKey | None = None,
    initiator_directory_descriptor: bytes | None = None,
) -> None:
    """Authenticate the remote endpoint against its directory-pinned Ed25519 key.

    When called by a relay, the request also authenticates the initiating relay.
    The entry/client handshake uses mode 0 so it does not reveal a client identity.
    """
    if target.identity_public_key is None:
        # Legacy low-level test fixtures have no identity key. Verified routes
        # always carry one and therefore cannot take this compatibility branch.
        if initiator_identity_private_key is not None:
            raise ValueError("relay-to-relay authentication requires a pinned target identity")
        return
    hello = _link_hello(
        target,
        initiator_identity_private_key=initiator_identity_private_key,
        initiator_directory_descriptor=initiator_directory_descriptor,
    )
    writer.write(frame(hello))
    await writer.drain()
    try:
        reply = await asyncio.wait_for(read_frame(reader), timeout=3)
        if len(reply) != 1 + LINK_SIGNATURE_BYTES or not reply.startswith(LINK_AUTH):
            raise ValueError("relay returned an invalid link-authentication response")
        signature = reply[1:]
        transcript = LINK_SERVER_DOMAIN + hello + target.identity_digest
        Ed25519PublicKey.from_public_bytes(target.identity_public_key).verify(signature, transcript)
    except (InvalidSignature, ValueError, asyncio.IncompleteReadError, TimeoutError) as exc:
        raise ValueError("relay transport identity authentication failed") from exc


@dataclass(slots=True)
class RelayDuplexState:
    """One destination TCP stream owned by the exit relay of a lab circuit."""
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    read_task: asyncio.Task[None] | None = None
    write_closed: bool = False
    read_closed: bool = False
    read_credit: int = INITIAL_STREAM_WINDOW_BYTES
    credit_condition: asyncio.Condition = field(default_factory=asyncio.Condition)


@dataclass(slots=True)
class RelayNode:
    """A single-circuit local relay that records only parsed command metadata."""

    identity_digest: bytes
    onion_private_key: X25519PrivateKey
    replay_guard: NtorReplayGuard = field(default_factory=NtorReplayGuard)
    allowed_destinations: set[tuple[str, int]] = field(default_factory=set)
    observations: list[RelayObservation] = field(default_factory=list)
    port: int | None = None
    max_active_connections: int = DEFAULT_MAX_ACTIVE_CONNECTIONS
    max_active_streams: int = MAX_ACTIVE_STREAMS
    identity_private_key: Ed25519PrivateKey | None = None
    link_replay_guard: LinkReplayGuard = field(default_factory=LinkReplayGuard)
    directory_verifier: Any | None = None
    directory_descriptor_json: bytes | None = field(default=None, repr=False)
    authorized_peer_ids: frozenset[bytes] | None = None
    # Opt-in, bounded relay-side timings for research benchmarks. Default off.
    collect_relay_metrics: bool = False
    bound_host: str | None = field(default=None, init=False, repr=False)
    _active_connections: int = field(default=0, init=False, repr=False)
    _descriptor_cache_key: tuple[Any, ...] | None = field(default=None, init=False, repr=False)
    _descriptor_cache: RelayDescriptor | None = field(default=None, init=False, repr=False)
    _relay_metric_events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=8192), init=False, repr=False
    )
    _relay_metric_dropped_events: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        relay_id_for(self.identity_digest)
        if not isinstance(self.collect_relay_metrics, bool):
            raise ValueError("collect_relay_metrics must be a boolean")
        if self.identity_private_key is not None:
            public_bytes = _ed25519_raw_public(self.identity_private_key.public_key())
            expected = hashlib.sha256(b"MALEBOLGE/relay-identity/v1\x00" + public_bytes).digest()[:20]
            if not hmac.compare_digest(expected, self.identity_digest):
                raise ValueError("relay identity private key does not match relay identity digest")
        if (
            not isinstance(self.max_active_connections, int)
            or isinstance(self.max_active_connections, bool)
            or not 1 <= self.max_active_connections <= 1024
        ):
            raise ValueError("max_active_connections must be within 1..1024")
        if (
            not isinstance(self.max_active_streams, int)
            or isinstance(self.max_active_streams, bool)
            or not 1 <= self.max_active_streams <= 4096
        ):
            raise ValueError("max_active_streams must be within 1..4096")
        if self.directory_descriptor_json is not None:
            if not isinstance(self.directory_descriptor_json, bytes) or not 1 <= len(self.directory_descriptor_json) <= LINK_DESCRIPTOR_MAX_BYTES:
                raise ValueError("signed directory descriptor exceeds its size limit")
        if self.authorized_peer_ids is not None:
            peers = frozenset(self.authorized_peer_ids)
            if any(not isinstance(peer, bytes) or len(peer) != 20 for peer in peers):
                raise ValueError("authorized peer IDs must be 20-byte relay identity digests")
            self.authorized_peer_ids = peers

    @property
    def active_connections(self) -> int:
        """Current admitted TCP handlers; intended for tests and local diagnostics."""
        return self._active_connections

    def _record_relay_metric(
        self, stage: str, elapsed_ns: int, *, operation: str | None = None,
    ) -> None:
        """Store bounded timings/counts only; never store payloads, IDs or addresses."""
        if not self.collect_relay_metrics:
            return
        if len(self._relay_metric_events) == self._relay_metric_events.maxlen:
            self._relay_metric_dropped_events += 1
        event: dict[str, Any] = {
            "stage": stage,
            "elapsed_ms": max(0, elapsed_ns) / 1_000_000,
        }
        if operation is not None:
            event["operation"] = operation
        self._relay_metric_events.append(event)

    def relay_metrics_snapshot(self) -> dict[str, Any]:
        """Return bounded per-relay stage summaries without traffic contents or identities."""
        events = [dict(event) for event in self._relay_metric_events]
        grouped: dict[str, list[dict[str, Any]]] = {}
        operations: dict[str, int] = {}
        for event in events:
            stage = str(event["stage"])
            grouped.setdefault(stage, []).append(event)
            if stage == "command_dispatch":
                operation = str(event.get("operation", "unknown"))
                operations[operation] = operations.get(operation, 0) + 1

        summary: dict[str, Any] = {}
        for stage, rows in grouped.items():
            values = sorted(float(row["elapsed_ms"]) for row in rows)
            p95_index = min(len(values) - 1, math.ceil((len(values) - 1) * 0.95))
            summary[stage] = {
                "samples": len(values),
                "median_ms": (
                    values[len(values) // 2] if len(values) % 2 else
                    (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2
                ),
                "p95_ms": values[p95_index],
                "total_ms": sum(values),
            }
        flow_credit_waits_ms = [
            float(event["elapsed_ms"]) for event in events
            if event.get("stage") == "flow_credit_wait"
        ]
        flow_control_stalls = [value for value in flow_credit_waits_ms if value >= 1.0]
        return {
            "enabled": self.collect_relay_metrics,
            "event_count": len(events),
            "dropped_events": self._relay_metric_dropped_events,
            "command_counts": operations,
            "summary_by_stage": summary,
            "flow_control_pause_summary": {
                "threshold_ms": 1.0,
                "wait_samples": len(flow_credit_waits_ms),
                "pauses_over_threshold": len(flow_control_stalls),
                "time_over_threshold_ms": sum(flow_control_stalls),
                "longest_pause_ms": max(flow_control_stalls, default=0.0),
            },
            "events": events,
            "privacy_note": "Contains only stage names, operation names and elapsed times; no payloads, stream IDs or network addresses.",
        }

    @property
    def descriptor(self) -> RelayDescriptor:
        if self.port is None:
            raise ValueError("relay has not been bound to a TCP port yet")
        # Relay descriptors are immutable and are consulted on the hot path for
        # every forwarded/event frame. Cache only after binding, and key the
        # cache by the mutable fields that define the advertised endpoint and
        # key objects so a port/host/identity replacement invalidates it.
        cache_key = (
            self.port,
            self.bound_host,
            self.identity_digest,
            self.onion_private_key,
            self.identity_private_key,
        )
        if self._descriptor_cache is not None and self._descriptor_cache_key == cache_key:
            return self._descriptor_cache
        identity_public = (
            _ed25519_raw_public(self.identity_private_key.public_key())
            if self.identity_private_key is not None else None
        )
        descriptor = RelayDescriptor(
            self.bound_host or "127.0.0.1", self.port, self.identity_digest,
            _raw_public_key(self.onion_private_key.public_key()),
            identity_public,
        )
        self._descriptor_cache_key = cache_key
        self._descriptor_cache = descriptor
        return descriptor

    def configure_directory_authorization(
        self, verifier: Any, signed_descriptor: Any, *, authorized_peer_ids: set[bytes] | frozenset[bytes] | None = None
    ) -> None:
        """Install a persistent trust verifier and this relay's own certified descriptor.

        Configuration verifies the relay's own certificate before any peer-auth
        exchange can use it. The verifier must have persistent state and a fresh
        authority-signed revocation snapshot. ``authorized_peer_ids`` optionally
        narrows the otherwise directory-authorized peer set.
        """
        from .directory import DirectoryVerifier, descriptor_to_json

        if not isinstance(verifier, DirectoryVerifier):
            raise ValueError("peer authorization requires a DirectoryVerifier")
        if self.port is None or self.bound_host is None:
            raise ValueError("relay must be bound to its listener before directory authorization")
        if not verifier.has_persistent_state:
            raise ValueError("peer authorization requires persistent directory state")
        verified = verifier.verify_peer_descriptor(signed_descriptor)
        if verified.identity_digest != self.identity_digest:
            raise ValueError("local directory descriptor does not match relay identity")
        if verified.onion_public_key != _raw_public_key(self.onion_private_key.public_key()):
            raise ValueError("local directory descriptor does not match relay onion key")
        if verified.port != self.port:
            raise ValueError("local directory descriptor does not match relay listener port")
        if verified.host != self.bound_host:
            raise ValueError("local directory descriptor does not match relay listener address")
        if not isinstance(verified.host, str) or not ipaddress.ip_address(verified.host).is_loopback:
            raise ValueError("local directory descriptor is not loopback")
        self.directory_verifier = verifier
        self.directory_descriptor_json = descriptor_to_json(signed_descriptor).encode("ascii")
        if authorized_peer_ids is not None:
            peers = frozenset(authorized_peer_ids)
            if any(not isinstance(peer, bytes) or len(peer) != 20 for peer in peers):
                raise ValueError("authorized peer IDs must be 20-byte relay identity digests")
            self.authorized_peer_ids = peers

    async def _answer_link_hello(self, hello: bytes, writer: asyncio.StreamWriter) -> None:
        """Authenticate the target-bound hello and authorize certified relay peers."""
        if self.identity_private_key is None:
            raise ValueError("relay has no identity signing key for authenticated transport")
        minimum = 1 + 1 + 20 + 20 + 32 + LINK_NONCE_BYTES + _LEN16.size + LINK_SIGNATURE_BYTES
        if len(hello) < minimum or len(hello) > minimum + LINK_DESCRIPTOR_MAX_BYTES:
            raise ValueError("malformed link-authentication hello")
        if hello[0:1] != LINK_HELLO:
            raise ValueError("malformed link-authentication hello")
        mode = hello[1]
        target_id = hello[2:22]
        peer_id = hello[22:42]
        peer_public = hello[42:74]
        nonce = hello[74:74 + LINK_NONCE_BYTES]
        descriptor_length = _LEN16.unpack_from(hello, 106)[0]
        descriptor_start = 108
        signature_start = descriptor_start + descriptor_length
        if descriptor_length > LINK_DESCRIPTOR_MAX_BYTES or signature_start + LINK_SIGNATURE_BYTES != len(hello):
            raise ValueError("link-authentication descriptor length is invalid")
        descriptor_bytes = hello[descriptor_start:signature_start]
        peer_signature = hello[signature_start:]
        if not hmac.compare_digest(target_id, self.identity_digest):
            raise ValueError("link-authentication hello names a different target relay")
        if mode == 0:
            if (
                peer_id != bytes(20) or peer_public != bytes(32)
                or peer_signature != bytes(LINK_SIGNATURE_BYTES) or descriptor_bytes
            ):
                raise ValueError("client link-authentication fields must be empty")
            replay_identity = bytes(20)
        elif mode == 1:
            expected_peer_id = hashlib.sha256(b"MALEBOLGE/relay-identity/v1\x00" + peer_public).digest()[:20]
            if not hmac.compare_digest(expected_peer_id, peer_id):
                raise ValueError("initiating relay identity does not match its public key")
            unsigned = hello[:-LINK_SIGNATURE_BYTES]
            try:
                Ed25519PublicKey.from_public_bytes(peer_public).verify(
                    peer_signature, LINK_CLIENT_DOMAIN + unsigned
                )
            except (InvalidSignature, ValueError) as exc:
                raise ValueError("initiating relay link signature is invalid") from exc
            if self.directory_verifier is not None:
                if not descriptor_bytes:
                    raise ValueError("initiating relay has no authority-certified directory descriptor")
                from .directory import descriptor_from_json
                try:
                    peer_descriptor = descriptor_from_json(descriptor_bytes.decode("ascii"))
                    verified_peer = self.directory_verifier.verify_peer_descriptor(peer_descriptor)
                except (UnicodeDecodeError, ValueError) as exc:
                    raise ValueError("initiating relay directory authorization failed") from exc
                if (
                    not hmac.compare_digest(verified_peer.identity_digest, peer_id)
                    or not hmac.compare_digest(verified_peer.identity_public_key, peer_public)
                ):
                    raise ValueError("initiating relay certificate identity does not match transport transcript")
                if self.authorized_peer_ids is not None and peer_id not in self.authorized_peer_ids:
                    raise ValueError("initiating relay is not authorized by local peer policy")
            elif descriptor_bytes:
                raise ValueError("cannot authorize directory descriptor without a trusted DirectoryVerifier")
            replay_identity = peer_id
        else:
            raise ValueError("unsupported link-authentication mode")
        self.link_replay_guard.claim(replay_identity, nonce)
        transcript = LINK_SERVER_DOMAIN + hello + self.identity_digest
        signature = self.identity_private_key.sign(transcript)
        writer.write(frame(LINK_AUTH + signature))
        await writer.drain()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Admission runs without an await so it is atomic on the asyncio loop.
        if self._active_connections >= self.max_active_connections:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            return
        self._active_connections += 1
        downstream_reader: asyncio.StreamReader | None = None
        downstream_writer: asyncio.StreamWriter | None = None
        downstream_read_task: asyncio.Task[None] | None = None
        downstream_write_lock = asyncio.Lock()
        response_write_lock = asyncio.Lock()
        downstream_pending: dict[tuple[int, int], asyncio.Future[bytes]] = {}
        ignored_downstream: set[tuple[int, int]] = set()
        stream_tasks: dict[int, asyncio.Task[None]] = {}
        duplex_streams: dict[int, RelayDuplexState] = {}
        duplex_write_pending_counts: dict[int, int] = {}
        duplex_write_pending_bytes: dict[int, int] = {}
        duplex_write_tasks: set[asyncio.Task[None]] = set()
        duplex_write_total_bytes = 0
        child_to_parent_streams: dict[int, int] = {}
        parent_to_child_streams: dict[int, int] = {}
        ready_streams: set[int] = set()
        event_sequences: dict[int, int] = {}
        queued_events: dict[int, list[tuple[int, int, int, bytes]]] = {}
        ignored_child_streams: set[int] = set()
        extension_used = False

        async def send_reply(sequence: int, stream_id: int, payload: bytes) -> None:
            started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
            try:
                envelope = _seal_reply(
                    keys.response_key, self.descriptor.relay_id, sequence, stream_id, payload
                )
                wire = _encode_link_response(sequence, stream_id, envelope)
                async with response_write_lock:
                    if writer.is_closing():
                        return
                    writer.write(frame(wire))
                    await writer.drain()
            finally:
                if self.collect_relay_metrics:
                    self._record_relay_metric("relay_reply_send", time.perf_counter_ns() - started_ns)

        def next_event_sequence(stream_id: int) -> int:
            sequence = event_sequences.get(stream_id, 0)
            if sequence >= (1 << 64) - 1:
                raise ValueError("stream event sequence exhausted")
            event_sequences[stream_id] = sequence + 1
            return sequence

        async def write_link_message(sequence: int, stream_id: int, kind: int, envelope: bytes) -> None:
            started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
            try:
                wire = _encode_link_response(sequence, stream_id, envelope, kind=kind)
                async with response_write_lock:
                    if writer.is_closing():
                        return
                    writer.write(frame(wire))
                    await writer.drain()
            finally:
                if self.collect_relay_metrics:
                    self._record_relay_metric("relay_event_send", time.perf_counter_ns() - started_ns)

        async def send_local_stream_event(stream_id: int, kind: int, payload: bytes) -> None:
            if kind == LINK_EVENT_EOF and payload:
                raise ValueError("EOF stream event must have an empty payload")
            sequence = next_event_sequence(stream_id)
            envelope = _seal_reply(
                keys.response_key, self.descriptor.relay_id, sequence, stream_id, payload
            )
            await write_link_message(sequence, stream_id, kind, envelope)

        async def send_forwarded_stream_event(
            parent_stream_id: int, child_sequence: int, child_stream_id: int,
            kind: int, child_envelope: bytes,
        ) -> None:
            if parent_stream_id not in ready_streams:
                queue = queued_events.setdefault(parent_stream_id, [])
                if len(queue) >= MAX_STREAM_EVENT_QUEUE:
                    raise ValueError("pre-ready stream event queue limit exceeded")
                queue.append((child_sequence, child_stream_id, kind, child_envelope))
                return
            parent_sequence = next_event_sequence(parent_stream_id)
            child_header = _EVENT_FORWARD_HEADER.pack(
                child_sequence, child_stream_id, kind, len(child_envelope)
            )
            payload = child_header + child_envelope
            envelope = _seal_reply(
                keys.response_key, self.descriptor.relay_id,
                parent_sequence, parent_stream_id, payload,
            )
            await write_link_message(parent_sequence, parent_stream_id, kind, envelope)

        async def flush_queued_stream_events(parent_stream_id: int) -> None:
            queued = queued_events.pop(parent_stream_id, [])
            for child_sequence, child_stream_id, kind, child_envelope in queued:
                await send_forwarded_stream_event(
                    parent_stream_id, child_sequence, child_stream_id, kind, child_envelope
                )

        async def pump_destination_stream(stream_id: int, state: RelayDuplexState) -> None:
            try:
                while not state.read_closed:
                    credit_wait_started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
                    async with state.credit_condition:
                        await state.credit_condition.wait_for(
                            lambda: state.read_credit > 0 or state.read_closed
                        )
                        if self.collect_relay_metrics:
                            self._record_relay_metric(
                                "flow_credit_wait", time.perf_counter_ns() - credit_wait_started_ns
                            )
                        if state.read_closed:
                            return
                        requested = min(STREAM_CHUNK_BYTES, state.read_credit)
                        # Reserve credit before awaiting socket I/O so WINDOW cannot over-credit.
                        state.read_credit -= requested
                    read_started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
                    data = await state.reader.read(requested)
                    if self.collect_relay_metrics:
                        self._record_relay_metric("destination_read_wait", time.perf_counter_ns() - read_started_ns)
                    if data:
                        unused = requested - len(data)
                        if unused:
                            async with state.credit_condition:
                                state.read_credit += unused
                        await send_local_stream_event(stream_id, LINK_EVENT_DATA, data)
                        continue
                    if requested:
                        async with state.credit_condition:
                            state.read_credit += requested
                    state.read_closed = True
                    await send_local_stream_event(stream_id, LINK_EVENT_EOF, b"")
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                # Treat a failed destination reader as EOF; don't expose the
                # destination's error details through the anonymous circuit.
                state.read_closed = True
                with contextlib.suppress(Exception):
                    await send_local_stream_event(stream_id, LINK_EVENT_EOF, b"")

        async def close_duplex_state(stream_id: int) -> bool:
            state = duplex_streams.pop(stream_id, None)
            if state is None:
                return False
            state.read_closed = True
            async with state.credit_condition:
                state.credit_condition.notify_all()
            task = state.read_task
            state.read_task = None
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            state.writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await state.writer.wait_closed()
            return True

        def reserve_duplex_write(stream_id: int, byte_count: int) -> None:
            nonlocal duplex_write_total_bytes
            pending_count = duplex_write_pending_counts.get(stream_id, 0)
            pending_bytes = duplex_write_pending_bytes.get(stream_id, 0)
            if pending_count >= MAX_RELAY_INFLIGHT_WRITE_COMMANDS_PER_STREAM:
                raise ValueError("duplex stream has too many in-flight WRITE commands")
            if pending_bytes + byte_count > MAX_RELAY_INFLIGHT_WRITE_BYTES_PER_STREAM:
                raise ValueError("duplex stream in-flight WRITE byte budget exceeded")
            if duplex_write_total_bytes + byte_count > MAX_RELAY_TOTAL_INFLIGHT_WRITE_BYTES:
                raise ValueError("relay aggregate in-flight WRITE byte budget exceeded")
            duplex_write_pending_counts[stream_id] = pending_count + 1
            duplex_write_pending_bytes[stream_id] = pending_bytes + byte_count
            duplex_write_total_bytes += byte_count

        def release_duplex_write(stream_id: int, byte_count: int) -> None:
            nonlocal duplex_write_total_bytes
            pending_count = duplex_write_pending_counts.get(stream_id, 0) - 1
            pending_bytes = duplex_write_pending_bytes.get(stream_id, 0) - byte_count
            duplex_write_total_bytes = max(0, duplex_write_total_bytes - byte_count)
            if pending_count <= 0:
                duplex_write_pending_counts.pop(stream_id, None)
            else:
                duplex_write_pending_counts[stream_id] = pending_count
            if pending_bytes <= 0:
                duplex_write_pending_bytes.pop(stream_id, None)
            else:
                duplex_write_pending_bytes[stream_id] = pending_bytes

        def track_duplex_write_task(task: asyncio.Task[None]) -> None:
            duplex_write_tasks.add(task)
            task.add_done_callback(duplex_write_tasks.discard)

        async def queue_forwarded_duplex_write(
            sequence: int, stream_id: int, child_sequence: int, child_stream_id: int,
            inner_packet: bytes,
        ) -> None:
            """Queue an ordered child WRITE, then await its ACK in a background task.

            Enqueuing the child frame before returning to the parent read loop keeps
            per-hop sequence order. Waiting for the child's ACK in a task allows the
            relay to accept a bounded number of subsequent WRITE commands.
            """
            if stream_id == 0 or child_stream_id == 0:
                raise ValueError("duplex stream IDs must be nonzero")
            if parent_to_child_streams.get(stream_id) != child_stream_id:
                raise ValueError("WRITE does not match an active child stream mapping")
            accounted_bytes = len(inner_packet)
            reserve_duplex_write(stream_id, accounted_bytes)
            try:
                key, future = await queue_downstream_packet(
                    child_sequence, child_stream_id, inner_packet
                )
            except Exception:
                release_duplex_write(stream_id, accounted_bytes)
                raise

            async def finish_forwarded_write() -> None:
                released = False
                try:
                    reply_payload = await await_downstream_response(key, future)
                    # Downstream ACK proves its WRITE drain completed; release the
                    # admission slot before exposing that ACK upstream so HALF_CLOSE
                    # cannot race with cleanup of this task.
                    release_duplex_write(stream_id, accounted_bytes)
                    released = True
                    await send_reply(sequence, stream_id, reply_payload)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # An unfulfillable WRITE ACK makes this circuit unusable.
                    writer.close()
                finally:
                    if not released:
                        release_duplex_write(stream_id, accounted_bytes)

            task = asyncio.create_task(finish_forwarded_write())
            track_duplex_write_task(task)

        async def downstream_response_dispatcher() -> None:
            assert downstream_reader is not None
            while True:
                wire = await read_frame(downstream_reader)
                sequence, stream_id, kind, envelope = _decode_link_message(wire)
                if kind in (LINK_EVENT_DATA, LINK_EVENT_EOF):
                    parent_stream_id = child_to_parent_streams.get(stream_id)
                    if parent_stream_id is None:
                        if stream_id in ignored_child_streams:
                            continue
                        raise ValueError("event arrived for an unknown downstream stream")
                    await send_forwarded_stream_event(
                        parent_stream_id, sequence, stream_id, kind, envelope
                    )
                    continue
                key = (sequence, stream_id)
                future = downstream_pending.pop(key, None)
                if future is None:
                    if key in ignored_downstream:
                        ignored_downstream.discard(key)
                        continue
                    raise ValueError("unmatched downstream stream response")
                if not future.done():
                    future.set_result(envelope)

        async def queue_downstream_packet(
            downstream_sequence: int, downstream_stream_id: int, inner_packet: bytes
        ) -> tuple[tuple[int, int], asyncio.Future[bytes]]:
            """Queue a child command before allowing a later CANCEL command to overtake it."""
            if downstream_writer is None or downstream_reader is None:
                raise ValueError("cannot forward before a successful extension")
            key = (downstream_sequence, downstream_stream_id)
            if key in downstream_pending:
                raise ValueError("duplicate downstream response correlation key")
            future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
            downstream_pending[key] = future
            try:
                async with downstream_write_lock:
                    downstream_writer.write(frame(inner_packet))
                    await downstream_writer.drain()
                return key, future
            except Exception:
                downstream_pending.pop(key, None)
                if not future.done():
                    future.cancel()
                raise

        async def await_downstream_response(
            key: tuple[int, int], future: asyncio.Future[bytes]
        ) -> bytes:
            started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
            try:
                return await asyncio.wait_for(future, timeout=10)
            except asyncio.CancelledError:
                if downstream_pending.pop(key, None) is not None:
                    ignored_downstream.add(key)
                if not future.done():
                    future.cancel()
                raise
            except Exception:
                downstream_pending.pop(key, None)
                if not future.done():
                    future.cancel()
                raise
            finally:
                if self.collect_relay_metrics:
                    self._record_relay_metric(
                        "downstream_response_wait", time.perf_counter_ns() - started_ns
                    )

        async def forward_packet(
            downstream_sequence: int, downstream_stream_id: int, inner_packet: bytes
        ) -> bytes:
            key, future = await queue_downstream_packet(
                downstream_sequence, downstream_stream_id, inner_packet
            )
            return await await_downstream_response(key, future)

        async def forward_duplex_command(
            sequence: int, stream_id: int, child_sequence: int, child_stream_id: int,
            kind: int, inner_packet: bytes,
        ) -> None:
            """Forward a duplex-stream control/data command through this relay."""
            if stream_id == 0 or child_stream_id == 0:
                raise ValueError("duplex stream IDs must be nonzero")
            is_open = kind == FORWARD_OPEN_STREAM
            if is_open:
                if stream_id in parent_to_child_streams or child_stream_id in child_to_parent_streams:
                    raise ValueError("duplex stream ID is already active")
                if len(parent_to_child_streams) >= self.max_active_streams:
                    raise ValueError("relay active-stream limit exceeded")
                # Register before sending OPEN: the child can send early events
                # after START, and their reverse mapping must already exist.
                parent_to_child_streams[stream_id] = child_stream_id
                child_to_parent_streams[child_stream_id] = stream_id
                event_sequences.setdefault(stream_id, 0)
            else:
                if parent_to_child_streams.get(stream_id) != child_stream_id:
                    raise ValueError("duplex command does not match an active stream mapping")
                if kind in (FORWARD_HALF_CLOSE_STREAM, FORWARD_CLOSE_STREAM) and duplex_write_pending_counts.get(stream_id, 0):
                    raise ValueError("stream control command cannot overtake in-flight WRITE commands")
            try:
                reply_payload = await forward_packet(child_sequence, child_stream_id, inner_packet)
                await send_reply(sequence, stream_id, reply_payload)
            except Exception:
                if is_open:
                    parent_to_child_streams.pop(stream_id, None)
                    child_to_parent_streams.pop(child_stream_id, None)
                    event_sequences.pop(stream_id, None)
                    queued_events.pop(stream_id, None)
                raise
            if kind == FORWARD_START_STREAM:
                ready_streams.add(stream_id)
                await flush_queued_stream_events(stream_id)
            elif kind == FORWARD_CLOSE_STREAM:
                ready_streams.discard(stream_id)
                parent_to_child_streams.pop(stream_id, None)
                child_to_parent_streams.pop(child_stream_id, None)
                ignored_child_streams.add(child_stream_id)
                event_sequences.pop(stream_id, None)
                queued_events.pop(stream_id, None)

        async def run_data_command(
            sequence: int, stream_id: int, operation: int, body: bytes,
            forwarded_response: tuple[tuple[int, int], asyncio.Future[bytes]] | None = None,
        ) -> None:
            try:
                if operation == ord("F"):
                    if len(body) < _FORWARD_HEADER.size:
                        raise ValueError("forward command is truncated")
                    child_sequence, child_stream_id, kind, length = _FORWARD_HEADER.unpack_from(body)
                    inner_packet = body[_FORWARD_HEADER.size:]
                    if kind != FORWARD_DATA:
                        raise ValueError("invalid forward kind for data task")
                    if length != len(inner_packet) or length > MAX_FRAME_BYTES:
                        raise ValueError("forward command length is invalid")
                    self.observations.append(RelayObservation("forward", None))
                    if forwarded_response is None:
                        reply_payload = await forward_packet(child_sequence, child_stream_id, inner_packet)
                    else:
                        response_key, response_future = forwarded_response
                        reply_payload = await await_downstream_response(response_key, response_future)
                elif operation == ord("D"):
                    if downstream_writer is not None:
                        raise ValueError("DATA is only permitted at the final relay")
                    host, port, payload = _decode_data_body(body)
                    _ensure_loopback(host)
                    if (host, port) not in self.allowed_destinations:
                        raise ValueError("destination is not allowlisted by this lab exit")
                    self.observations.append(RelayObservation("data", port))
                    destination_reader, destination_writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port), timeout=3
                    )
                    try:
                        destination_writer.write(frame(payload))
                        await destination_writer.drain()
                        reply_payload = await asyncio.wait_for(read_frame(destination_reader), timeout=5)
                    finally:
                        destination_writer.close()
                        with contextlib.suppress(ConnectionError, OSError):
                            await destination_writer.wait_closed()
                else:
                    raise ValueError("unsupported multiplexed command")
                await send_reply(sequence, stream_id, reply_payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never return route-specific errors on the wire. Fail this
                # circuit closed; do not leave an unobserved task exception.
                writer.close()
            finally:
                current = asyncio.current_task()
                if stream_tasks.get(stream_id) is current:
                    stream_tasks.pop(stream_id, None)

        async def run_forward_cancel(
            sequence: int, stream_id: int, body: bytes
        ) -> None:
            if len(body) < _FORWARD_HEADER.size:
                raise ValueError("cancel-forward command is truncated")
            child_sequence, child_stream_id, kind, length = _FORWARD_HEADER.unpack_from(body)
            inner_packet = body[_FORWARD_HEADER.size:]
            if kind != FORWARD_CANCEL or length != len(inner_packet) or length > MAX_FRAME_BYTES:
                raise ValueError("cancel-forward body is invalid")
            old_task = stream_tasks.pop(stream_id, None)
            if old_task is not None and old_task is not asyncio.current_task():
                old_task.cancel()
                await asyncio.gather(old_task, return_exceptions=True)
            self.observations.append(RelayObservation("cancel", None))
            reply_payload = await forward_packet(child_sequence, child_stream_id, inner_packet)
            await send_reply(sequence, stream_id, reply_payload)

        try:
            bootstrap = await asyncio.wait_for(read_frame(reader), timeout=3)
            if bootstrap.startswith(LINK_HELLO):
                await self._answer_link_hello(bootstrap, writer)
                bootstrap = await asyncio.wait_for(read_frame(reader), timeout=3)
            if not bootstrap.startswith(BOOTSTRAP_CREATE) or len(bootstrap) != 1 + CLIENT_HANDSHAKE_BYTES:
                raise ValueError("invalid CREATE bootstrap")
            relay_reply, keys = relay_respond(
                bootstrap[1:], self.identity_digest, self.onion_private_key,
                replay_guard=self.replay_guard,
            )
            writer.write(frame(BOOTSTRAP_CREATED + relay_reply))
            await writer.drain()

            expected_sequence = 0
            while True:
                try:
                    envelope = await asyncio.wait_for(read_frame(reader), timeout=30)
                except asyncio.IncompleteReadError as exc:
                    if exc.partial:
                        raise ValueError("truncated telescoping frame") from exc
                    break
                plaintext = open_sealed(
                    keys.request_key, envelope,
                    _aad(REQUEST_AAD_PREFIX, self.descriptor.relay_id),
                )
                if len(plaintext) < _COMMAND_HEADER.size:
                    raise ValueError("truncated command header")
                sequence, stream_id, operation = _COMMAND_HEADER.unpack_from(plaintext)
                if sequence != expected_sequence:
                    raise ValueError("telescoping sequence mismatch")
                if expected_sequence >= MAX_COMMANDS_PER_CIRCUIT:
                    raise ValueError("circuit command budget exhausted; circuit must be rebuilt")
                expected_sequence += 1
                body = plaintext[_COMMAND_HEADER.size:]
                command_dispatch_started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
                operation_names = {
                    ord("E"): "extend", ord("F"): "forward", ord("D"): "data",
                    ord("O"): "open_stream", ord("B"): "start_stream", ord("W"): "write",
                    ord("H"): "half_close", ord("V"): "window_update", ord("X"): "close_stream",
                }
                operation_name = operation_names.get(operation, "unknown")

                if operation == ord("E"):
                    if stream_id != 0 or stream_tasks:
                        raise ValueError("EXTEND requires stream zero and no active streams")
                    if extension_used:
                        raise ValueError("only one next-hop extension is allowed per relay")
                    host, port, identity, onion_key, identity_public_key, client_handshake = _decode_extension(body)
                    _ensure_loopback(host)
                    if port == self.port:
                        raise ValueError("relay cannot extend to itself")
                    if client_handshake[:20] != identity or client_handshake[20:52] != onion_key:
                        raise ValueError("extension descriptor does not match its handshake")
                    target_descriptor = RelayDescriptor(host, port, identity, onion_key, identity_public_key)
                    if identity_public_key is not None and self.identity_private_key is None:
                        raise ValueError("relay-to-relay authenticated transport requires the initiating relay identity key")
                    self.observations.append(RelayObservation("extend", port))
                    downstream_reader, downstream_writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port), timeout=3
                    )
                    await _authenticate_relay_endpoint(
                        downstream_reader, downstream_writer, target_descriptor,
                        initiator_identity_private_key=(self.identity_private_key if identity_public_key is not None else None),
                        initiator_directory_descriptor=(self.directory_descriptor_json if identity_public_key is not None else None),
                    )
                    downstream_writer.write(frame(BOOTSTRAP_CREATE + client_handshake))
                    await downstream_writer.drain()
                    downstream_reply = await asyncio.wait_for(read_frame(downstream_reader), timeout=3)
                    if not downstream_reply.startswith(BOOTSTRAP_CREATED) or len(downstream_reply) < 2:
                        raise ValueError("next relay rejected CREATE")
                    extension_used = True
                    reply_payload = downstream_reply[1:]
                    downstream_read_task = asyncio.create_task(downstream_response_dispatcher())
                    await send_reply(sequence, stream_id, reply_payload)
                elif operation == ord("F"):
                    if downstream_writer is None or downstream_reader is None:
                        raise ValueError("cannot forward before a successful extension")
                    if len(body) < _FORWARD_HEADER.size:
                        raise ValueError("forward command is truncated")
                    child_sequence, child_stream_id, kind, length = _FORWARD_HEADER.unpack_from(body)
                    inner_packet = body[_FORWARD_HEADER.size:]
                    if length != len(inner_packet) or length > MAX_FRAME_BYTES:
                        raise ValueError("forward command length is invalid")
                    if kind == FORWARD_CANCEL:
                        if stream_id == 0:
                            raise ValueError("cancel stream id cannot be zero")
                        await run_forward_cancel(sequence, stream_id, body)
                    elif kind == FORWARD_WRITE_STREAM:
                        await queue_forwarded_duplex_write(
                            sequence, stream_id, child_sequence, child_stream_id, inner_packet
                        )
                    elif kind in (
                        FORWARD_OPEN_STREAM, FORWARD_START_STREAM,
                        FORWARD_HALF_CLOSE_STREAM, FORWARD_CLOSE_STREAM, FORWARD_WINDOW_UPDATE,
                    ):
                        await forward_duplex_command(
                            sequence, stream_id, child_sequence, child_stream_id, kind, inner_packet
                        )
                    elif kind == FORWARD_DATA:
                        if stream_id == 0:
                            # Stream zero is reserved for serialized extensions.
                            self.observations.append(RelayObservation("forward", None))
                            reply_payload = await forward_packet(child_sequence, child_stream_id, inner_packet)
                            await send_reply(sequence, stream_id, reply_payload)
                        else:
                            if stream_id in stream_tasks:
                                raise ValueError("stream id is already active on this relay")
                            if len(stream_tasks) >= self.max_active_streams:
                                raise ValueError("relay active-stream limit exceeded")
                            # Reserve the child sequence and enqueue the child command before
                            # returning to the incoming loop. Otherwise a subsequent CANCEL
                            # could overtake this packet on the next hop and desynchronize it.
                            child_ref = await queue_downstream_packet(
                                child_sequence, child_stream_id, inner_packet
                            )
                            task = asyncio.create_task(
                                run_data_command(sequence, stream_id, operation, body, child_ref)
                            )
                            stream_tasks[stream_id] = task
                    else:
                        raise ValueError("unsupported forwarding kind")
                elif operation == ord("D"):
                    if stream_id == 0:
                        raise ValueError("DATA requires a nonzero stream id")
                    if stream_id in stream_tasks:
                        raise ValueError("stream id is already active on this relay")
                    if len(stream_tasks) >= self.max_active_streams:
                        raise ValueError("relay active-stream limit exceeded")
                    task = asyncio.create_task(run_data_command(sequence, stream_id, operation, body))
                    stream_tasks[stream_id] = task
                elif operation == ord("O"):
                    if downstream_writer is not None:
                        raise ValueError("OPEN_STREAM is only permitted at the final relay")
                    if stream_id == 0 or stream_id in duplex_streams or len(duplex_streams) >= self.max_active_streams:
                        raise ValueError("invalid or excessive active stream count")
                    host, port = _decode_stream_open_body(body)
                    if (host, port) not in self.allowed_destinations:
                        raise ValueError("destination is not allowlisted by this lab exit")
                    self.observations.append(RelayObservation("stream_open", port))
                    destination_reader, destination_writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port), timeout=3
                    )
                    duplex_streams[stream_id] = RelayDuplexState(destination_reader, destination_writer)
                    event_sequences[stream_id] = 0
                    await send_reply(sequence, stream_id, b"STREAM_OPENED")
                elif operation == ord("B"):
                    state = duplex_streams.get(stream_id)
                    if stream_id == 0 or state is None or body or state.read_task is not None:
                        raise ValueError("START_STREAM does not match an unopened stream")
                    await send_reply(sequence, stream_id, b"STREAM_STARTED")
                    state.read_task = asyncio.create_task(pump_destination_stream(stream_id, state))
                elif operation == ord("W"):
                    state = duplex_streams.get(stream_id)
                    if stream_id == 0 or state is None or state.write_closed:
                        raise ValueError("WRITE requires an active writable stream")
                    payload = _decode_stream_write_body(body)
                    reserve_duplex_write(stream_id, len(payload))
                    # StreamWriter.write is synchronous and called in command sequence
                    # order; drain/ACK can complete in background to permit a bounded
                    # pipeline of subsequent writes on this circuit.
                    try:
                        state.writer.write(payload)
                    except Exception:
                        release_duplex_write(stream_id, len(payload))
                        raise

                    async def finish_local_write(
                        command_sequence: int, command_stream_id: int,
                        byte_count: int, target_state: RelayDuplexState,
                    ) -> None:
                        released = False
                        drain_started_ns = time.perf_counter_ns() if self.collect_relay_metrics else 0
                        try:
                            await target_state.writer.drain()
                            if self.collect_relay_metrics:
                                self._record_relay_metric(
                                    "destination_write_drain", time.perf_counter_ns() - drain_started_ns
                                )
                            # The local destination drain is complete. Release the
                            # pending-write count before sending the ACK so a valid
                            # HALF_CLOSE immediately after the ACK cannot race cleanup.
                            release_duplex_write(command_stream_id, byte_count)
                            released = True
                            await send_reply(
                                command_sequence, command_stream_id,
                                b"WROTE" + _LEN32.pack(byte_count),
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            writer.close()
                        finally:
                            if not released:
                                release_duplex_write(command_stream_id, byte_count)

                    task = asyncio.create_task(
                        finish_local_write(sequence, stream_id, len(payload), state)
                    )
                    track_duplex_write_task(task)
                elif operation == ord("H"):
                    state = duplex_streams.get(stream_id)
                    if stream_id == 0 or state is None or body or state.write_closed:
                        raise ValueError("HALF_CLOSE requires an active writable stream")
                    if duplex_write_pending_counts.get(stream_id, 0):
                        raise ValueError("HALF_CLOSE cannot overtake in-flight WRITE commands")
                    if not state.writer.can_write_eof():
                        raise ValueError("destination transport does not support half-close")
                    state.writer.write_eof()
                    await state.writer.drain()
                    state.write_closed = True
                    await send_reply(sequence, stream_id, b"WRITE_EOF")
                elif operation == ord("V"):
                    state = duplex_streams.get(stream_id)
                    if stream_id == 0 or state is None:
                        raise ValueError("WINDOW_UPDATE requires an active stream")
                    amount = _decode_window_update_body(body)
                    self.observations.append(RelayObservation("window_update", None))
                    if not state.read_closed:
                        async with state.credit_condition:
                            if state.read_credit + amount > MAX_STREAM_WINDOW_BYTES:
                                raise ValueError("stream read window exceeds its maximum")
                            state.read_credit += amount
                            state.credit_condition.notify_all()
                    await send_reply(sequence, stream_id, b"WINDOW_UPDATED")
                elif operation == ord("X"):
                    if stream_id == 0 or len(body) != _STREAM_ID.size:
                        raise ValueError("CANCEL requires a nonzero target stream id")
                    target_stream_id = _STREAM_ID.unpack(body)[0]
                    if target_stream_id != stream_id:
                        raise ValueError("CANCEL stream id mismatch")
                    if duplex_write_pending_counts.get(stream_id, 0):
                        raise ValueError("CLOSE cannot overtake in-flight WRITE commands")
                    was_duplex = await close_duplex_state(target_stream_id)
                    task = stream_tasks.pop(target_stream_id, None)
                    was_active = was_duplex or (task is not None and task is not asyncio.current_task())
                    if task is not None and task is not asyncio.current_task():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    self.observations.append(RelayObservation("stream_close" if was_duplex else "cancel", None))
                    await send_reply(sequence, stream_id, b"STREAM_CLOSED" if was_duplex else (b"CANCELLED" if was_active else b"NOT_ACTIVE"))
                else:
                    raise ValueError("unsupported telescoping command")

                if self.collect_relay_metrics:
                    self._record_relay_metric(
                        "command_dispatch", time.perf_counter_ns() - command_dispatch_started_ns,
                        operation=operation_name,
                    )
                if downstream_read_task is not None and downstream_read_task.done():
                    # A broken downstream response channel makes this circuit unusable.
                    downstream_read_task.result()
        except (
            asyncio.IncompleteReadError, ConnectionError, OSError, TimeoutError,
            ValueError, InvalidTag,
        ):
            pass
        finally:
            for task in list(stream_tasks.values()):
                task.cancel()
            if stream_tasks:
                await asyncio.gather(*stream_tasks.values(), return_exceptions=True)
            active_write_tasks = list(duplex_write_tasks)
            for task in active_write_tasks:
                task.cancel()
            if active_write_tasks:
                await asyncio.gather(*active_write_tasks, return_exceptions=True)
            if downstream_read_task is not None:
                downstream_read_task.cancel()
                await asyncio.gather(downstream_read_task, return_exceptions=True)
            for future in downstream_pending.values():
                if not future.done():
                    future.cancel()
            for duplex_stream_id in list(duplex_streams):
                with contextlib.suppress(Exception):
                    await close_duplex_state(duplex_stream_id)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            if downstream_writer is not None:
                downstream_writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await downstream_writer.wait_closed()
            self._active_connections -= 1


def _encode_extension(
    sequence: int, target: RelayDescriptor, client_handshake: bytes, *, stream_id: int = 0
) -> bytes:
    if not 0 <= sequence < (1 << 64) or not 0 <= stream_id < (1 << 32):
        raise ValueError("sequence or stream id is outside its wire range")
    host = target.host.encode("ascii")
    if len(host) > 255 or len(client_handshake) != CLIENT_HANDSHAKE_BYTES:
        raise ValueError("extension fields have invalid lengths")
    identity_public_key = target.identity_public_key or b""
    return (
        _COMMAND_HEADER.pack(sequence, stream_id, ord("E"))
        + bytes([len(host)]) + host + _PORT.pack(target.port)
        + target.identity_digest + target.onion_public_key
        + bytes([len(identity_public_key)]) + identity_public_key
        + _LEN16.pack(len(client_handshake)) + client_handshake
    )


def _decode_extension(body: bytes) -> tuple[str, int, bytes, bytes, bytes | None, bytes]:
    if not body:
        raise ValueError("extension body is empty")
    host_length = body[0]
    fixed_offset = 1 + host_length
    required = fixed_offset + 2 + 20 + 32 + 1 + 2
    if len(body) < required:
        raise ValueError("extension descriptor is truncated")
    try:
        host = body[1:fixed_offset].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("extension host must be ASCII") from exc
    port = _PORT.unpack_from(body, fixed_offset)[0]
    identity_start = fixed_offset + 2
    identity = body[identity_start:identity_start + 20]
    key_start = identity_start + 20
    onion_key = body[key_start:key_start + 32]
    identity_key_length_offset = key_start + 32
    identity_key_length = body[identity_key_length_offset]
    if identity_key_length not in (0, 32):
        raise ValueError("extension identity public key length must be zero or 32")
    identity_key_start = identity_key_length_offset + 1
    identity_public_key = body[identity_key_start:identity_key_start + identity_key_length] or None
    handshake_start = identity_key_start + identity_key_length
    if len(body) < handshake_start + 2:
        raise ValueError("extension handshake length is missing")
    handshake_length = _LEN16.unpack_from(body, handshake_start)[0]
    handshake = body[handshake_start + 2:]
    if handshake_length != len(handshake) or len(handshake) != CLIENT_HANDSHAKE_BYTES:
        raise ValueError("extension handshake length is invalid")
    RelayDescriptor(host, port, identity, onion_key, identity_public_key)
    return host, port, identity, onion_key, identity_public_key, handshake


def _encode_forward(
    sequence: int, stream_id: int, downstream_sequence: int,
    downstream_stream_id: int, inner_packet: bytes, *, kind: int = FORWARD_DATA,
) -> bytes:
    if any(not 0 <= value < (1 << 64) for value in (sequence, downstream_sequence)):
        raise ValueError("sequence must be an unsigned 64-bit integer")
    if any(not 0 <= value < (1 << 32) for value in (stream_id, downstream_stream_id)):
        raise ValueError("stream id must be an unsigned 32-bit integer")
    if kind not in (FORWARD_DATA, FORWARD_CANCEL, FORWARD_OPEN_STREAM, FORWARD_START_STREAM, FORWARD_WRITE_STREAM, FORWARD_HALF_CLOSE_STREAM, FORWARD_CLOSE_STREAM, FORWARD_WINDOW_UPDATE):
        raise ValueError("unsupported forward kind")
    if len(inner_packet) > MAX_FRAME_BYTES:
        raise ValueError("forwarded packet exceeds size limit")
    return (
        _COMMAND_HEADER.pack(sequence, stream_id, ord("F"))
        + _FORWARD_HEADER.pack(downstream_sequence, downstream_stream_id, kind, len(inner_packet))
        + inner_packet
    )


def _encode_data(sequence: int, stream_id: int, host: str, port: int, payload: bytes) -> bytes:
    _ensure_loopback(host)
    if not 1 <= port <= 65535:
        raise ValueError("destination port must be within 1..65535")
    if not 1 <= stream_id < (1 << 32):
        raise ValueError("DATA requires a nonzero 32-bit stream id")
    if len(payload) > MAX_DATA_BYTES:
        raise ValueError(f"data payload exceeds the {MAX_DATA_BYTES}-byte lab limit")
    host_bytes = host.encode("ascii")
    if len(host_bytes) > 255:
        raise ValueError("destination host name is too long")
    return (
        _COMMAND_HEADER.pack(sequence, stream_id, ord("D"))
        + bytes([len(host_bytes)]) + host_bytes + _PORT.pack(port)
        + _LEN32.pack(len(payload)) + payload
    )


def _decode_data_body(body: bytes) -> tuple[str, int, bytes]:
    if not body:
        raise ValueError("data command is empty")
    host_length = body[0]
    port_offset = 1 + host_length
    if len(body) < port_offset + 2 + 4:
        raise ValueError("data command is truncated")
    try:
        host = body[1:port_offset].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("data destination host must be ASCII") from exc
    port = _PORT.unpack_from(body, port_offset)[0]
    if not 1 <= port <= 65535:
        raise ValueError("data destination port is invalid")
    length = _LEN32.unpack_from(body, port_offset + 2)[0]
    payload = body[port_offset + 6:]
    if length != len(payload) or length > MAX_DATA_BYTES:
        raise ValueError("data command payload length is invalid")
    return host, port, payload


def _encode_stream_open_body(host: str, port: int) -> bytes:
    _ensure_loopback(host)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("destination port must be within 1..65535")
    host_bytes = host.encode("ascii")
    if not host_bytes or len(host_bytes) > 255:
        raise ValueError("stream destination host length is invalid")
    return bytes([len(host_bytes)]) + host_bytes + _PORT.pack(port)


def _decode_stream_open_body(body: bytes) -> tuple[str, int]:
    if not body:
        raise ValueError("stream open body is empty")
    host_length = body[0]
    if not 1 <= host_length <= 255 or len(body) != 1 + host_length + 2:
        raise ValueError("stream open body length is invalid")
    try:
        host = body[1:1 + host_length].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("stream destination host must be ASCII") from exc
    _ensure_loopback(host)
    port = _PORT.unpack_from(body, 1 + host_length)[0]
    if not 1 <= port <= 65535:
        raise ValueError("stream destination port is invalid")
    return host, port


def _encode_stream_write_body(payload: bytes) -> bytes:
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= STREAM_WRITE_MAX_BYTES:
        raise ValueError(f"stream writes must contain 1..{STREAM_WRITE_MAX_BYTES} bytes")
    return _LEN32.pack(len(payload)) + payload


def _decode_stream_write_body(body: bytes) -> bytes:
    if len(body) < _LEN32.size:
        raise ValueError("stream write body is truncated")
    length = _LEN32.unpack_from(body)[0]
    payload = body[_LEN32.size:]
    if not 1 <= length <= STREAM_WRITE_MAX_BYTES or length != len(payload):
        raise ValueError("stream write length is invalid")
    return payload


def _encode_window_update_body(amount: int) -> bytes:
    if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= MAX_STREAM_WINDOW_BYTES:
        raise ValueError(f"window update must be within 1..{MAX_STREAM_WINDOW_BYTES}")
    return _LEN32.pack(amount)


def _decode_window_update_body(body: bytes) -> int:
    if len(body) != _LEN32.size:
        raise ValueError("window update body length is invalid")
    amount = _LEN32.unpack(body)[0]
    if not 1 <= amount <= MAX_STREAM_WINDOW_BYTES:
        raise ValueError("window update amount is invalid")
    return amount


class CircuitStream:
    """One-shot multiplexed request/response stream on a persistent circuit.

    This v0.13 lab abstraction carries one bounded application request and its
    response. It is not yet a general byte-stream socket API.
    """

    def __init__(
        self, client: "TelescopingClient", logical_id: int,
        hop_stream_ids: dict[str, int], used_sequences: dict[str, int],
        response_future: asyncio.Future[bytes],
    ) -> None:
        self._client = client
        self.logical_id = logical_id
        self.hop_stream_ids = dict(hop_stream_ids)
        self.used_sequences = dict(used_sequences)
        self._response_future = response_future
        self._finished = False
        self._cancelled = False

    @property
    def stream_id(self) -> int:
        """Entry-hop stream ID, useful for diagnostics in this lab."""
        if not self._client.hops:
            raise ValueError("circuit is closed")
        return self.hop_stream_ids[self._client.hops[0].descriptor.relay_id]

    async def result(self, timeout: float = 10.0) -> bytes:
        if self._finished:
            if self._cancelled:
                raise asyncio.CancelledError("stream was cancelled")
            raise ValueError("stream result has already been consumed")
        try:
            envelope = await asyncio.wait_for(asyncio.shield(self._response_future), timeout=timeout)
            response = envelope
            for hop in self._client.hops:
                relay_id = hop.descriptor.relay_id
                response = _open_reply(
                    hop.keys.response_key, relay_id, self.used_sequences[relay_id],
                    response, self.hop_stream_ids[relay_id],
                )
            await self._client._check_after_stream_response()
            self._client._touch_activity()
            self._finished = True
            self._client._active_streams.pop(self.logical_id, None)
            return response
        except asyncio.CancelledError:
            # Leave the stream registered so the caller (or request_echo) can
            # send an explicit protocol cancellation instead of orphaning it.
            raise
        except Exception:
            self._finished = True
            self._client._active_streams.pop(self.logical_id, None)
            await self._client.close()
            raise

    async def cancel(self) -> bool:
        """Cancel this in-flight request on each relay; returns whether it was pending."""
        if self._finished:
            return False
        return await self._client._cancel_stream(self)


class DuplexCircuitStream:
    """Experimental full-duplex byte stream multiplexed over a lab circuit.

    Reads return up to one authenticated chunk. The exit is given a bounded
    read-credit window; each consumed chunk returns credit so a slow reader
    naturally backpressures its destination TCP socket. Client writes are capped
    at STREAM_WRITE_MAX_BYTES (256 KiB) per acknowledged command.
    """

    def __init__(
        self, client: "TelescopingClient", logical_id: int,
        hop_stream_ids: dict[str, int],
    ) -> None:
        self._client = client
        self.logical_id = logical_id
        self.hop_stream_ids = dict(hop_stream_ids)
        self._event_sequences = {hop.descriptor.relay_id: 0 for hop in client.hops}
        self._receive_buffer = bytearray()
        self._receive_signal = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._eof = False  # EOF has been consumed by read_chunk()
        self._remote_eof_received = False  # EOF event has arrived behind buffered data
        self._write_closed = False
        self._closed = False
        self._error: BaseException | None = None
        self._pending_window_credit = 0

    @property
    def stream_id(self) -> int:
        """Entry-hop ID for diagnostics in this local testbed."""
        if not self._client.hops:
            raise ValueError("circuit is closed")
        return self.hop_stream_ids[self._client.hops[0].descriptor.relay_id]

    async def _accept_event(self, sequence: int, kind: int, envelope: bytes) -> None:
        if self._closed:
            raise ValueError("event received for a closed stream")
        if self._remote_eof_received:
            raise ValueError("stream data received after remote EOF")
        current_sequence = sequence
        current_stream_id = self.hop_stream_ids[self._client.hops[0].descriptor.relay_id]
        current_kind = kind
        current_envelope = envelope
        final_payload = b""
        for index, hop in enumerate(self._client.hops):
            relay_id = hop.descriptor.relay_id
            expected_sequence = self._event_sequences[relay_id]
            if current_sequence != expected_sequence:
                raise ValueError("duplex event sequence mismatch")
            expected_sid = self.hop_stream_ids[relay_id]
            if current_stream_id != expected_sid:
                raise ValueError("duplex event stream mapping mismatch")
            payload = _open_reply(
                hop.keys.response_key, relay_id, expected_sequence,
                current_envelope, expected_sid,
            )
            self._event_sequences[relay_id] += 1
            if index == len(self._client.hops) - 1:
                final_payload = payload
                break
            if len(payload) < _EVENT_FORWARD_HEADER.size:
                raise ValueError("forwarded duplex event is truncated")
            child_sequence, child_stream_id, child_kind, child_length = _EVENT_FORWARD_HEADER.unpack_from(payload)
            child_envelope = payload[_EVENT_FORWARD_HEADER.size:]
            if child_kind != current_kind or child_length != len(child_envelope) or child_length > MAX_FRAME_BYTES:
                raise ValueError("forwarded duplex event metadata is invalid")
            child_hop = self._client.hops[index + 1]
            if child_stream_id != self.hop_stream_ids[child_hop.descriptor.relay_id]:
                raise ValueError("forwarded duplex event names an unexpected child stream")
            current_sequence, current_stream_id = child_sequence, child_stream_id
            current_kind, current_envelope = child_kind, child_envelope
        if current_kind == LINK_EVENT_DATA:
            if not final_payload or len(final_payload) > STREAM_CHUNK_BYTES:
                raise ValueError("duplex data event has an invalid payload length")
            if len(self._receive_buffer) + len(final_payload) > MAX_STREAM_WINDOW_BYTES:
                raise ValueError("duplex receive window exceeded; refusing unbounded buffering")
            self._receive_buffer.extend(final_payload)
            self._receive_signal.set()
        elif current_kind == LINK_EVENT_EOF:
            if final_payload:
                raise ValueError("duplex EOF event must be empty")
            self._remote_eof_received = True
            self._receive_signal.set()
        else:
            raise ValueError("unknown duplex event type")
        self._client._touch_activity()

    def _fail(self, exc: BaseException) -> None:
        self._error = exc
        self._receive_signal.set()

    async def write(self, data: bytes) -> int:
        """Write one chunk and wait for its authenticated acknowledgement."""
        if self._closed or self._write_closed:
            raise ValueError("duplex stream write side is closed")
        if not isinstance(data, bytes) or not 1 <= len(data) <= STREAM_WRITE_MAX_BYTES:
            raise ValueError(f"write requires 1..{STREAM_WRITE_MAX_BYTES} bytes")
        async with self._write_lock:
            replies = await self._client._send_duplex_write_batch(self, [data])
            self._validate_write_ack(data, replies[0])
            return len(data)

    @staticmethod
    def _validate_write_ack(data: bytes, reply: bytes) -> None:
        if len(reply) != 9 or reply[:5] != b"WROTE" or _LEN32.unpack_from(reply, 5)[0] != len(data):
            raise ValueError("invalid duplex write acknowledgement")

    async def write_pipelined(
        self, data: bytes, *, chunk_bytes: int = 64 * 1024, max_in_flight: int = MAX_PIPELINE_DEPTH
    ) -> int:
        """Write a bounded payload with several WRITE commands in flight.

        Commands are allocated monotonically and sent in order, then their ACKs
        are correlated by per-hop sequence. At most ``max_in_flight`` chunks are
        retained by this operation at once. This is experimental protocol behavior,
        not a general-purpose production stream implementation.
        """
        if self._closed or self._write_closed:
            raise ValueError("duplex stream write side is closed")
        if (not isinstance(data, bytes) or not 1 <= len(data) <= MAX_PIPELINED_WRITE_PAYLOAD_BYTES):
            raise ValueError(
                f"pipelined write requires 1..{MAX_PIPELINED_WRITE_PAYLOAD_BYTES} bytes"
            )
        if (not isinstance(chunk_bytes, int) or isinstance(chunk_bytes, bool)
                or not 1 <= chunk_bytes <= STREAM_WRITE_MAX_BYTES):
            raise ValueError(f"chunk_bytes must be within 1..{STREAM_WRITE_MAX_BYTES}")
        if (not isinstance(max_in_flight, int) or isinstance(max_in_flight, bool)
                or not 1 <= max_in_flight <= MAX_PIPELINE_DEPTH):
            raise ValueError(f"max_in_flight must be within 1..{MAX_PIPELINE_DEPTH}")
        command_count = (len(data) + chunk_bytes - 1) // chunk_bytes
        if command_count > MAX_PIPELINED_WRITE_COMMANDS:
            raise ValueError(
                f"pipelined write would exceed {MAX_PIPELINED_WRITE_COMMANDS} commands"
            )

        written = 0
        async with self._write_lock:
            for batch_start in range(0, len(data), chunk_bytes * max_in_flight):
                batch_end = min(len(data), batch_start + chunk_bytes * max_in_flight)
                payloads = [
                    data[offset:min(offset + chunk_bytes, batch_end)]
                    for offset in range(batch_start, batch_end, chunk_bytes)
                ]
                replies = await self._client._send_duplex_write_batch(self, payloads)
                for payload, reply in zip(payloads, replies, strict=True):
                    self._validate_write_ack(payload, reply)
                    written += len(payload)
        return written

    async def read_chunk(self) -> bytes:
        """Return one bounded chunk and coalesce consumed-byte window credits.

        Credits are sent when the configured batch threshold is reached. If the
        application is waiting for more data with a smaller pending credit, a
        short timer flushes it so a sparse stream cannot deadlock waiting for
        credit. EOF/close discards unused pending credit because the stream is
        no longer eligible to receive more destination bytes.
        """
        while True:
            if self._error is not None:
                raise ConnectionError("duplex circuit failed") from self._error
            if self._receive_buffer:
                result = bytes(self._receive_buffer[:STREAM_CHUNK_BYTES])
                del self._receive_buffer[:len(result)]
                self._pending_window_credit += len(result)
                if self._pending_window_credit >= self._client.window_update_batch_bytes:
                    await self._flush_window_credit()
                return result
            if self._eof or self._remote_eof_received:
                self._eof = True
                self._pending_window_credit = 0
                return b""
            # No await occurs between checking state and clearing the event, so
            # _accept_event cannot race this clear on the same asyncio loop.
            self._receive_signal.clear()
            if self._pending_window_credit:
                try:
                    await asyncio.wait_for(
                        self._receive_signal.wait(),
                        timeout=self._client.window_update_max_delay_seconds,
                    )
                except asyncio.TimeoutError:
                    await self._flush_window_credit()
                continue
            await self._receive_signal.wait()

    async def _flush_window_credit(self) -> None:
        amount = self._pending_window_credit
        if amount <= 0:
            return
        if self._closed or self._remote_eof_received:
            self._pending_window_credit = 0
            return
        # Reserve the batch before awaiting I/O so concurrently delivered events
        # cannot be included twice. On transport failure, the circuit is unusable.
        self._pending_window_credit = 0
        reply = await self._client._send_duplex_command(
            self, "V", _encode_window_update_body(amount), FORWARD_WINDOW_UPDATE
        )
        if reply != b"WINDOW_UPDATED":
            raise ValueError("invalid stream-window acknowledgement")

    async def write_eof(self) -> None:
        # EOF may not overtake any pipelined WRITE on this stream.
        async with self._write_lock:
            if self._closed or self._write_closed:
                return
            reply = await self._client._send_duplex_command(self, "H", b"", FORWARD_HALF_CLOSE_STREAM)
            if reply != b"WRITE_EOF":
                raise ValueError("invalid half-close acknowledgement")
            self._write_closed = True

    async def close(self) -> bool:
        # Closing under the same lock prevents a concurrent pipeline from being
        # truncated after only a prefix of its acknowledgements has arrived.
        async with self._write_lock:
            if self._closed:
                return False
            reply = await self._client._send_duplex_command(
                self, "X", _STREAM_ID.pack(self.hop_stream_ids[self._client.hops[-1].descriptor.relay_id]),
                FORWARD_CLOSE_STREAM,
            )
            if reply != b"STREAM_CLOSED":
                raise ValueError("invalid stream-close acknowledgement")
            self._closed = True
            self._fail(ConnectionError("duplex stream closed by caller"))
            self._client._active_duplex_streams.pop(self.logical_id, None)
            self._client._ignored_events.update(
                (sequence, self.hop_stream_ids[self._client.hops[0].descriptor.relay_id])
                for sequence in range(self._event_sequences[self._client.hops[0].descriptor.relay_id],
                                      self._event_sequences[self._client.hops[0].descriptor.relay_id] + 8)
            )
            return True


@dataclass(slots=True)
class _ScheduledWriteTicket:
    used_sequences: dict[str, int]
    used_stream_ids: dict[str, int]
    response_key: tuple[int, int]
    response_future: asyncio.Future[bytes]


@dataclass(slots=True)
class _QueuedDuplexWrite:
    logical_stream_id: int
    payload: bytes
    sent_future: asyncio.Future[_ScheduledWriteTicket]
    enqueued_ns: int = 0


class TelescopingClient:
    """Loopback-only client with multiplexed one-shot streams and bounded lifetime.

    A single reader dispatches per-link response frames to pending futures. Each
    request has a distinct stream ID at each hop, while a send lock preserves
    monotonically increasing per-hop command sequences. Response waits do not
    hold that lock, so independent streams can be in flight concurrently.
    """

    def __init__(
        self,
        *,
        idle_timeout_seconds: float = 300.0,
        max_lifetime_seconds: float = 3600.0,
        max_active_streams: int = MAX_ACTIVE_STREAMS,
        window_update_batch_bytes: int = WINDOW_UPDATE_BATCH_BYTES,
        window_update_max_delay_seconds: float = WINDOW_UPDATE_MAX_DELAY_SECONDS,
        fair_write_scheduling: bool = False,
        collect_write_metrics: bool = False,
    ) -> None:
        for name, value in (
            ("idle_timeout_seconds", idle_timeout_seconds),
            ("max_lifetime_seconds", max_lifetime_seconds),
        ):
            if (
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        if not isinstance(max_active_streams, int) or isinstance(max_active_streams, bool) or not 1 <= max_active_streams <= 4096:
            raise ValueError("max_active_streams must be within 1..4096")
        if (
            not isinstance(window_update_batch_bytes, int)
            or isinstance(window_update_batch_bytes, bool)
            or not 1 <= window_update_batch_bytes <= MAX_STREAM_WINDOW_BYTES
        ):
            raise ValueError(f"window_update_batch_bytes must be within 1..{MAX_STREAM_WINDOW_BYTES}")
        if (
            not isinstance(window_update_max_delay_seconds, (int, float))
            or isinstance(window_update_max_delay_seconds, bool)
            or not math.isfinite(window_update_max_delay_seconds)
            or not 0 < window_update_max_delay_seconds <= 1.0
        ):
            raise ValueError("window_update_max_delay_seconds must be finite and within (0, 1.0]")
        self.idle_timeout_seconds = float(idle_timeout_seconds)
        self.max_lifetime_seconds = float(max_lifetime_seconds)
        if not isinstance(fair_write_scheduling, bool):
            raise ValueError("fair_write_scheduling must be a boolean")
        if not isinstance(collect_write_metrics, bool):
            raise ValueError("collect_write_metrics must be a boolean")
        self.max_active_streams = max_active_streams
        self.window_update_batch_bytes = window_update_batch_bytes
        self.window_update_max_delay_seconds = float(window_update_max_delay_seconds)
        self.fair_write_scheduling = fair_write_scheduling
        self.collect_write_metrics = collect_write_metrics
        self.hops: list[ClientHop] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._verified_route: Any | None = None
        self._created_at: float | None = None
        self._last_activity: float | None = None
        self._io_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._stream_open_lock = asyncio.Lock()
        self._pending_replies: dict[tuple[int, int], asyncio.Future[bytes]] = {}
        self._ignored_replies: set[tuple[int, int]] = set()
        self._ignored_events: set[tuple[int, int]] = set()
        self._active_streams: dict[int, CircuitStream] = {}
        self._active_duplex_streams: dict[int, DuplexCircuitStream] = {}
        self._write_queue_lock = asyncio.Lock()
        self._write_scheduler_event = asyncio.Event()
        self._write_queues: dict[int, deque[_QueuedDuplexWrite]] = {}
        self._write_ready: deque[int] = deque()
        self._write_ready_set: set[int] = set()
        self._scheduled_write_commands = 0
        self._scheduled_write_bytes = 0
        self._write_scheduler_task: asyncio.Task[None] | None = None
        # Optional timing diagnostics. This bounded trace contains counts and
        # durations only; it never retains payloads or network addresses.
        self._write_metric_events: deque[dict[str, Any]] = deque(maxlen=4096)
        self._write_metric_dropped_events = 0
        # Bounded test/diagnostic trace; contains ephemeral logical IDs only, never payloads.
        self._write_scheduler_trace: deque[int] = deque(maxlen=MAX_SCHEDULER_TRACE_ITEMS)
        self._next_logical_id = 1
        self.direct_connections_opened = 0

    def _record_write_metric(self, event: dict[str, Any]) -> None:
        if not self.collect_write_metrics:
            return
        if len(self._write_metric_events) == self._write_metric_events.maxlen:
            self._write_metric_dropped_events += 1
        self._write_metric_events.append(dict(event))

    def write_metrics_snapshot(self) -> dict[str, Any]:
        """Return bounded scheduler-stage timings without payload contents."""
        events = [dict(event) for event in self._write_metric_events]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(str(event.get("event", "unknown")), []).append(event)

        summaries: dict[str, Any] = {}
        for event_name, event_rows in grouped.items():
            fields = sorted({
                key for row in event_rows for key, value in row.items()
                if key.endswith("_ms") and isinstance(value, (int, float))
            })
            field_summary: dict[str, Any] = {}
            for field_name in fields:
                samples = sorted(float(row[field_name]) for row in event_rows if field_name in row)
                if not samples:
                    continue
                p95_index = min(len(samples) - 1, math.ceil((len(samples) - 1) * 0.95))
                field_summary[field_name] = {
                    "samples": len(samples),
                    "median": samples[len(samples) // 2] if len(samples) % 2 else (
                        samples[len(samples) // 2 - 1] + samples[len(samples) // 2]
                    ) / 2,
                    "p95": samples[p95_index],
                }
            summaries[event_name] = {"events": len(event_rows), "metrics": field_summary}
        return {
            "enabled": self.collect_write_metrics,
            "event_count": len(events),
            "dropped_events": self._write_metric_dropped_events,
            "summary_by_event": summaries,
            "events": events,
        }

    def _touch_activity(self) -> None:
        now = time.monotonic()
        if self._created_at is None:
            self._created_at = now
        self._last_activity = now

    async def _response_reader_loop(self) -> None:
        try:
            assert self._reader is not None
            while True:
                wire = await read_frame(self._reader)
                sequence, stream_id, kind, envelope = _decode_link_message(wire)
                if kind in (LINK_EVENT_DATA, LINK_EVENT_EOF):
                    if not self.hops:
                        raise ValueError("stream event received after circuit shutdown")
                    guard_id = self.hops[0].descriptor.relay_id
                    stream = next((
                        item for item in self._active_duplex_streams.values()
                        if item.hop_stream_ids.get(guard_id) == stream_id
                    ), None)
                    if stream is None:
                        if (sequence, stream_id) in self._ignored_events:
                            self._ignored_events.discard((sequence, stream_id))
                            continue
                        raise ValueError("event received for an unknown duplex stream")
                    await stream._accept_event(sequence, kind, envelope)
                    continue
                key = (sequence, stream_id)
                future = self._pending_replies.pop(key, None)
                if future is None:
                    if key in self._ignored_replies:
                        self._ignored_replies.discard(key)
                        continue
                    raise ValueError("unmatched response frame; circuit state is invalid")
                if not future.done():
                    future.set_result(envelope)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = ConnectionError("circuit response dispatcher failed")
            for future in self._pending_replies.values():
                if not future.done():
                    future.set_exception(failure)
            self._pending_replies.clear()
            for stream in self._active_duplex_streams.values():
                stream._fail(failure)
            if self._writer is not None:
                self._writer.close()

    async def _assert_route_current_unlocked(self) -> None:
        if self._verified_route is None:
            return
        try:
            self._verified_route.assert_usable()
        except Exception:
            await self._close_unlocked()
            raise

    async def _assert_max_lifetime_unlocked(self) -> None:
        now = time.monotonic()
        if self._created_at is not None and now - self._created_at >= self.max_lifetime_seconds:
            await self._close_unlocked()
            raise ValueError("circuit maximum lifetime exceeded; rebuild the circuit")

    async def _assert_circuit_usable_unlocked(self) -> None:
        if self._writer is None or self._reader is None or not self.hops:
            raise ValueError("client has no active circuit")
        await self._assert_max_lifetime_unlocked()
        now = time.monotonic()
        if self._last_activity is not None and now - self._last_activity >= self.idle_timeout_seconds:
            await self._close_unlocked()
            raise ValueError("circuit idle timeout exceeded; rebuild the circuit")
        await self._assert_route_current_unlocked()

    async def _check_after_stream_response(self) -> None:
        await self._assert_max_lifetime_unlocked()
        await self._assert_route_current_unlocked()

    def _register_pending(self, sequence: int, stream_id: int) -> asyncio.Future[bytes]:
        key = (sequence, stream_id)
        if key in self._pending_replies:
            raise ValueError("duplicate client response correlation key")
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._pending_replies[key] = future
        return future

    async def connect_verified_route(self, route: Any) -> None:
        from .directory import VerifiedCircuitRoute
        if not isinstance(route, VerifiedCircuitRoute):
            raise ValueError("a DirectoryVerifier-issued VerifiedCircuitRoute is required")
        route.assert_usable()
        descriptors = route.descriptors
        if not descriptors:
            raise ValueError("verified route is empty")
        if any(descriptor.identity_public_key is None for descriptor in descriptors):
            raise ValueError("verified route is missing relay identity public keys")
        async with self._io_lock:
            if self._writer is not None or self.hops:
                raise ValueError("client already has a circuit")
            self._verified_route = route
            try:
                route.assert_usable()
                await self._connect_guard_unlocked(descriptors[0])
                route.assert_usable()
                for descriptor in descriptors[1:]:
                    await self._extend_unlocked(descriptor)
                    route.assert_usable()
                await self._assert_route_current_unlocked()
            except Exception:
                await self._close_unlocked()
                raise

    async def connect_guard(self, guard: RelayDescriptor) -> None:
        async with self._io_lock:
            try:
                await self._connect_guard_unlocked(guard)
            except Exception:
                await self._close_unlocked()
                raise

    async def _connect_guard_unlocked(self, guard: RelayDescriptor) -> None:
        if self._writer is not None or self.hops:
            raise ValueError("client already has a circuit")
        if self._verified_route is not None:
            self._verified_route.assert_usable()
        reader, writer = await asyncio.open_connection(guard.host, guard.port)
        self.direct_connections_opened += 1
        try:
            await _authenticate_relay_endpoint(reader, writer, guard)
            if self._verified_route is not None:
                self._verified_route.assert_usable()
            state, handshake = client_start(guard.identity_digest, guard.onion_public_key)
            writer.write(frame(BOOTSTRAP_CREATE + handshake))
            await writer.drain()
            reply = await asyncio.wait_for(read_frame(reader), timeout=3)
            if not reply.startswith(BOOTSTRAP_CREATED) or len(reply) < 2:
                raise ValueError("guard rejected CREATE")
            keys = client_finish(state, reply[1:])
            self._reader, self._writer = reader, writer
            self.hops.append(ClientHop(guard, keys))
            self._touch_activity()
            self._reader_task = asyncio.create_task(self._response_reader_loop())
            if self._verified_route is not None:
                self._verified_route.assert_usable()
        except Exception:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            if self._writer is writer:
                self._reader = None
                self._writer = None
                self.hops.clear()
                self._created_at = None
                self._last_activity = None
            raise

    async def _ensure_command_budget(self) -> None:
        if any(hop.next_sequence >= MAX_COMMANDS_PER_CIRCUIT for hop in self.hops):
            await self._close_unlocked()
            raise ValueError("circuit command budget exhausted; rebuild the circuit")

    async def extend(self, target: RelayDescriptor) -> None:
        async with self._io_lock:
            if self._writer is not None:
                await self._assert_circuit_usable_unlocked()
            await self._extend_unlocked(target)

    async def _extend_unlocked(self, target: RelayDescriptor) -> None:
        async with self._send_lock:
            if self._writer is None or self._reader is None or not self.hops:
                raise ValueError("connect to a guard before extending")
            if self._active_streams or self._active_duplex_streams:
                raise ValueError("cannot extend a circuit while streams are active")
            await self._ensure_command_budget()
            if len(self.hops) >= MAX_HOPS:
                raise ValueError("maximum laboratory circuit length reached")
            if any(hop.descriptor.identity_digest == target.identity_digest for hop in self.hops):
                raise ValueError("relay already exists in this circuit")
            if self._verified_route is not None:
                self._verified_route.assert_usable()
            last = self.hops[-1]
            state, client_handshake = client_start(target.identity_digest, target.onion_public_key)
            used_sequences = {last.descriptor.relay_id: last.next_sequence}
            used_stream_ids = {last.descriptor.relay_id: 0}
            body = _encode_extension(last.next_sequence, target, client_handshake, stream_id=0)
            packet = seal(last.keys.request_key, body, _aad(REQUEST_AAD_PREFIX, last.descriptor.relay_id))
            last.next_sequence += 1
            for index in range(len(self.hops) - 2, -1, -1):
                hop = self.hops[index]
                child = self.hops[index + 1]
                used_sequences[hop.descriptor.relay_id] = hop.next_sequence
                used_stream_ids[hop.descriptor.relay_id] = 0
                body = _encode_forward(
                    hop.next_sequence, 0, used_sequences[child.descriptor.relay_id], 0, packet,
                )
                packet = seal(hop.keys.request_key, body, _aad(REQUEST_AAD_PREFIX, hop.descriptor.relay_id))
                hop.next_sequence += 1
            guard = self.hops[0]
            future = self._register_pending(used_sequences[guard.descriptor.relay_id], 0)
            try:
                self._touch_activity()
                self._writer.write(frame(packet))
                await self._writer.drain()
                response = await asyncio.wait_for(future, timeout=10)
                for hop in self.hops:
                    rid = hop.descriptor.relay_id
                    response = _open_reply(
                        hop.keys.response_key, rid, used_sequences[rid], response,
                        used_stream_ids[rid],
                    )
                new_keys = client_finish(state, response)
                await self._assert_max_lifetime_unlocked()
                if self._verified_route is not None:
                    self._verified_route.assert_usable()
            except Exception:
                self._pending_replies.pop((used_sequences[guard.descriptor.relay_id], 0), None)
                await self._close_unlocked()
                raise
            self.hops.append(ClientHop(target, new_keys))
            self._touch_activity()

    def _allocate_logical_id(self) -> int:
        candidate = self._next_logical_id
        self._next_logical_id = (self._next_logical_id + 1) & ((1 << 63) - 1)
        if self._next_logical_id == 0:
            self._next_logical_id = 1
        return candidate

    def _allocate_hop_stream_ids(self) -> dict[str, int]:
        active = [set() for _ in self.hops]
        for stream in (*self._active_streams.values(), *self._active_duplex_streams.values()):
            for index, hop in enumerate(self.hops):
                active[index].add(stream.hop_stream_ids[hop.descriptor.relay_id])
        assigned: dict[str, int] = {}
        for index, hop in enumerate(self.hops):
            while True:
                stream_id = int.from_bytes(os.urandom(4), "big")
                if stream_id != 0 and stream_id not in active[index]:
                    assigned[hop.descriptor.relay_id] = stream_id
                    break
        return assigned

    async def start_echo(self, destination_host: str, destination_port: int, payload: bytes) -> CircuitStream:
        """Start a bounded request/response stream without waiting for its reply.

        Independent streams are multiplexed over the same persistent circuit.
        The current lab stream is one request and one response, not an arbitrary
        duplex byte stream yet.
        """
        async with self._send_lock:
            await self._assert_circuit_usable_unlocked()
            if len(self._active_streams) >= self.max_active_streams:
                raise ValueError("client active-stream limit exceeded")
            if len(payload) > MAX_DATA_BYTES:
                raise ValueError(f"data payload exceeds the {MAX_DATA_BYTES}-byte lab limit")
            await self._ensure_command_budget()
            assert self._writer is not None
            last = self.hops[-1]
            used_sequences = {last.descriptor.relay_id: last.next_sequence}
            hop_stream_ids = self._allocate_hop_stream_ids()
            used_stream_ids = {last.descriptor.relay_id: hop_stream_ids[last.descriptor.relay_id]}
            body = _encode_data(
                last.next_sequence, used_stream_ids[last.descriptor.relay_id],
                destination_host, destination_port, payload,
            )
            packet = seal(last.keys.request_key, body, _aad(REQUEST_AAD_PREFIX, last.descriptor.relay_id))
            last.next_sequence += 1
            for index in range(len(self.hops) - 2, -1, -1):
                hop = self.hops[index]
                child = self.hops[index + 1]
                used_sequences[hop.descriptor.relay_id] = hop.next_sequence
                used_stream_ids[hop.descriptor.relay_id] = hop_stream_ids[hop.descriptor.relay_id]
                body = _encode_forward(
                    hop.next_sequence, used_stream_ids[hop.descriptor.relay_id],
                    used_sequences[child.descriptor.relay_id], used_stream_ids[child.descriptor.relay_id],
                    packet,
                )
                packet = seal(hop.keys.request_key, body, _aad(REQUEST_AAD_PREFIX, hop.descriptor.relay_id))
                hop.next_sequence += 1
            guard = self.hops[0]
            guard_id = guard.descriptor.relay_id
            future = self._register_pending(used_sequences[guard_id], used_stream_ids[guard_id])
            logical_id = self._allocate_logical_id()
            stream = CircuitStream(self, logical_id, hop_stream_ids, used_sequences, future)
            self._active_streams[logical_id] = stream
            try:
                self._touch_activity()
                self._writer.write(frame(packet))
                await self._writer.drain()
            except Exception:
                self._pending_replies.pop((used_sequences[guard_id], used_stream_ids[guard_id]), None)
                self._active_streams.pop(logical_id, None)
                if not future.done():
                    future.cancel()
                await self._close_unlocked()
                raise
            return stream

    async def _send_duplex_write_batch(
        self, stream: DuplexCircuitStream, payloads: list[bytes], *, timeout: float = 10.0,
    ) -> list[bytes]:
        """Dispatch WRITE batches using the baseline or experimental fair scheduler.

        The baseline remains the default because local A/B measurements did not
        establish a robust fairness or throughput gain for round-robin scheduling.
        """
        if self.fair_write_scheduling:
            return await self._send_duplex_write_batch_fair(stream, payloads, timeout=timeout)
        return await self._send_duplex_write_batch_direct(stream, payloads, timeout=timeout)

    async def _send_duplex_write_batch_direct(
        self, stream: DuplexCircuitStream, payloads: list[bytes], *, timeout: float = 10.0,
    ) -> list[bytes]:
        """Send bounded WRITE commands in-order without awaiting each ACK in turn.

        Per-hop command sequences and response correlation keys are reserved under
        the circuit send lock. The complete batch is queued in order, one drain is
        awaited, and individual authenticated ACKs may then arrive in any order.
        """
        if not 1 <= len(payloads) <= MAX_PIPELINE_DEPTH:
            raise ValueError(f"write batch must contain 1..{MAX_PIPELINE_DEPTH} commands")
        for payload in payloads:
            if not isinstance(payload, bytes) or not 1 <= len(payload) <= STREAM_WRITE_MAX_BYTES:
                raise ValueError(f"each pipelined write must contain 1..{STREAM_WRITE_MAX_BYTES} bytes")

        batch_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
        lock_acquired_ns = encode_started_ns = encode_finished_ns = 0
        drain_started_ns = drain_finished_ns = 0
        records: list[tuple[dict[str, int], dict[str, int], tuple[int, int], asyncio.Future[bytes]]] = []
        async with self._send_lock:
            if self.collect_write_metrics:
                lock_acquired_ns = time.perf_counter_ns()
            await self._assert_circuit_usable_unlocked()
            if any(hop.next_sequence + len(payloads) > MAX_COMMANDS_PER_CIRCUIT for hop in self.hops):
                await self._close_unlocked()
                raise ValueError("pipeline would exceed the circuit command budget; rebuild the circuit")
            assert self._writer is not None
            try:
                if self.collect_write_metrics:
                    encode_started_ns = time.perf_counter_ns()
                for payload in payloads:
                    last = self.hops[-1]
                    used_sequences: dict[str, int] = {last.descriptor.relay_id: last.next_sequence}
                    used_stream_ids = dict(stream.hop_stream_ids)
                    last_sid = used_stream_ids[last.descriptor.relay_id]
                    plaintext = _COMMAND_HEADER.pack(last.next_sequence, last_sid, ord("W")) + _encode_stream_write_body(payload)
                    packet = seal(
                        last.keys.request_key, plaintext, _aad(REQUEST_AAD_PREFIX, last.descriptor.relay_id)
                    )
                    last.next_sequence += 1
                    for index in range(len(self.hops) - 2, -1, -1):
                        hop = self.hops[index]
                        child = self.hops[index + 1]
                        used_sequences[hop.descriptor.relay_id] = hop.next_sequence
                        packet_body = _encode_forward(
                            hop.next_sequence, used_stream_ids[hop.descriptor.relay_id],
                            used_sequences[child.descriptor.relay_id], used_stream_ids[child.descriptor.relay_id],
                            packet, kind=FORWARD_WRITE_STREAM,
                        )
                        packet = seal(
                            hop.keys.request_key, packet_body, _aad(REQUEST_AAD_PREFIX, hop.descriptor.relay_id)
                        )
                        hop.next_sequence += 1
                    guard = self.hops[0]
                    key = (used_sequences[guard.descriptor.relay_id], used_stream_ids[guard.descriptor.relay_id])
                    future = self._register_pending(*key)
                    records.append((used_sequences, used_stream_ids, key, future))
                    self._writer.write(frame(packet))
                if self.collect_write_metrics:
                    encode_finished_ns = time.perf_counter_ns()
                self._touch_activity()
                if self.collect_write_metrics:
                    drain_started_ns = time.perf_counter_ns()
                await self._writer.drain()
                if self.collect_write_metrics:
                    drain_finished_ns = time.perf_counter_ns()
            except Exception:
                for _, _, key, future in records:
                    self._pending_replies.pop(key, None)
                    if not future.done():
                        future.cancel()
                await self._close_unlocked()
                raise

        try:
            ack_wait_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            envelopes = await asyncio.wait_for(
                asyncio.gather(*(future for _, _, _, future in records)), timeout=timeout
            )
            ack_wait_finished_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            decode_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            responses: list[bytes] = []
            for (used_sequences, used_stream_ids, _, _), envelope in zip(records, envelopes, strict=True):
                response = envelope
                for hop in self.hops:
                    relay_id = hop.descriptor.relay_id
                    response = _open_reply(
                        hop.keys.response_key, relay_id, used_sequences[relay_id],
                        response, used_stream_ids[relay_id],
                    )
                responses.append(response)
            await self._check_after_stream_response()
            self._touch_activity()
            if self.collect_write_metrics:
                decode_finished_ns = time.perf_counter_ns()
                self._record_write_metric({
                    "event": "write_batch",
                    "scheduler": "baseline",
                    "commands": len(payloads),
                    "bytes": sum(len(payload) for payload in payloads),
                    "lock_wait_ms": (lock_acquired_ns - batch_started_ns) / 1_000_000,
                    "frame_prepare_ms": (encode_finished_ns - encode_started_ns) / 1_000_000,
                    "socket_drain_ms": (drain_finished_ns - drain_started_ns) / 1_000_000,
                    "response_wait_ms": (ack_wait_finished_ns - ack_wait_started_ns) / 1_000_000,
                    "response_decode_ms": (decode_finished_ns - decode_started_ns) / 1_000_000,
                    "total_ms": (decode_finished_ns - batch_started_ns) / 1_000_000,
                })
            return responses
        except Exception:
            await self.close()
            raise

    async def _send_duplex_write_batch_fair(
        self, stream: DuplexCircuitStream, payloads: list[bytes], *, timeout: float = 10.0,
    ) -> list[bytes]:
        """Send WRITE commands through a circuit-wide round-robin scheduler.

        Commands from each stream stay FIFO, while the scheduler takes one command
        per ready stream per round and drains a bounded cross-stream batch. ACKs are
        awaited only after all selected commands have been sent. The scheduler's
        aggregate queue budget is fail-closed and includes queued and dispatching
        payloads; it never stores application payloads in diagnostic traces.
        """
        if not 1 <= len(payloads) <= MAX_PIPELINE_DEPTH:
            raise ValueError(f"write batch must contain 1..{MAX_PIPELINE_DEPTH} commands")
        for payload in payloads:
            if not isinstance(payload, bytes) or not 1 <= len(payload) <= STREAM_WRITE_MAX_BYTES:
                raise ValueError(f"each pipelined write must contain 1..{STREAM_WRITE_MAX_BYTES} bytes")
        if stream._closed or stream.logical_id not in self._active_duplex_streams:
            raise ValueError("duplex stream is not active")

        # Admission/backpressure failures occur before any frame is sent and do not
        # poison the circuit; transport failures after admission still fail closed.
        batch_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
        sent_futures = await self._enqueue_duplex_writes(stream, payloads)
        tickets: list[_ScheduledWriteTicket] = []
        try:
            tickets = await asyncio.wait_for(asyncio.gather(*sent_futures), timeout=timeout)
            dispatch_finished_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            ack_wait_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            envelopes = await asyncio.wait_for(
                asyncio.gather(*(ticket.response_future for ticket in tickets)), timeout=timeout
            )
            ack_wait_finished_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            decode_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            responses: list[bytes] = []
            for ticket, envelope in zip(tickets, envelopes, strict=True):
                response = envelope
                for hop in self.hops:
                    relay_id = hop.descriptor.relay_id
                    response = _open_reply(
                        hop.keys.response_key, relay_id, ticket.used_sequences[relay_id],
                        response, ticket.used_stream_ids[relay_id],
                    )
                responses.append(response)
            await self._check_after_stream_response()
            self._touch_activity()
            if self.collect_write_metrics:
                decode_finished_ns = time.perf_counter_ns()
                self._record_write_metric({
                    "event": "write_batch",
                    "scheduler": "round_robin",
                    "commands": len(payloads),
                    "bytes": sum(len(payload) for payload in payloads),
                    "queue_to_dispatch_ms": (dispatch_finished_ns - batch_started_ns) / 1_000_000,
                    "response_wait_ms": (ack_wait_finished_ns - ack_wait_started_ns) / 1_000_000,
                    "response_decode_ms": (decode_finished_ns - decode_started_ns) / 1_000_000,
                    "total_ms": (decode_finished_ns - batch_started_ns) / 1_000_000,
                })
            return responses
        except asyncio.CancelledError:
            # Canceling an ACK wait after frames are on the circuit would otherwise
            # leave replies unmatched and desynchronize the single reader. Fail closed.
            await asyncio.shield(self.close())
            raise
        except Exception:
            await self.close()
            raise

    async def _enqueue_duplex_writes(
        self, stream: DuplexCircuitStream, payloads: list[bytes]
    ) -> list[asyncio.Future[_ScheduledWriteTicket]]:
        loop = asyncio.get_running_loop()
        total_bytes = sum(len(payload) for payload in payloads)
        async with self._write_queue_lock:
            if self._writer is None or not self.hops or stream._closed:
                raise ValueError("client has no active circuit or stream")
            if self._scheduled_write_commands + len(payloads) > MAX_SCHEDULED_WRITE_COMMANDS:
                raise ValueError("circuit write scheduler command budget exceeded; retry after backpressure")
            if self._scheduled_write_bytes + total_bytes > MAX_SCHEDULED_WRITE_BYTES:
                raise ValueError("circuit write scheduler byte budget exceeded; retry after backpressure")
            stream_id = stream.logical_id
            queue = self._write_queues.get(stream_id)
            if queue is None:
                queue = deque()
                self._write_queues[stream_id] = queue
            if stream_id not in self._write_ready_set:
                self._write_ready.append(stream_id)
                self._write_ready_set.add(stream_id)
            futures: list[asyncio.Future[_ScheduledWriteTicket]] = []
            enqueued_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
            for payload in payloads:
                future: asyncio.Future[_ScheduledWriteTicket] = loop.create_future()
                queue.append(_QueuedDuplexWrite(stream_id, payload, future, enqueued_ns))
                futures.append(future)
            self._scheduled_write_commands += len(payloads)
            self._scheduled_write_bytes += total_bytes
            task = self._write_scheduler_task
            if task is None or task.done():
                self._write_scheduler_task = asyncio.create_task(
                    self._write_scheduler_loop(), name="aegis-fair-write-scheduler"
                )
            self._write_scheduler_event.set()
            return futures

    async def _write_scheduler_loop(self) -> None:
        current_task = asyncio.current_task()
        try:
            while True:
                await self._write_scheduler_event.wait()
                jobs: list[_QueuedDuplexWrite] = []
                async with self._write_queue_lock:
                    while self._write_ready and len(jobs) < MAX_SCHEDULER_DRAIN_COMMANDS:
                        stream_id = self._write_ready.popleft()
                        self._write_ready_set.discard(stream_id)
                        queue = self._write_queues.get(stream_id)
                        if queue is None:
                            continue
                        while queue and queue[0].sent_future.cancelled():
                            discarded = queue.popleft()
                            self._scheduled_write_commands -= 1
                            self._scheduled_write_bytes -= len(discarded.payload)
                        if not queue:
                            self._write_queues.pop(stream_id, None)
                            continue
                        jobs.append(queue.popleft())
                        if queue:
                            self._write_ready.append(stream_id)
                            self._write_ready_set.add(stream_id)
                        else:
                            self._write_queues.pop(stream_id, None)
                    if self._write_ready:
                        self._write_scheduler_event.set()
                    else:
                        self._write_scheduler_event.clear()
                if not jobs:
                    continue
                try:
                    dispatch_started_ns = time.perf_counter_ns() if self.collect_write_metrics else 0
                    await self._send_scheduled_write_round(jobs, dispatch_started_ns=dispatch_started_ns)
                except asyncio.CancelledError:
                    for job in jobs:
                        if not job.sent_future.done():
                            job.sent_future.cancel()
                    raise
                except Exception as exc:
                    for job in jobs:
                        if not job.sent_future.done():
                            job.sent_future.set_exception(exc)
                    await self._fail_queued_writes(exc)
                    return
                finally:
                    await self._release_scheduled_write_budget(jobs)
        finally:
            if self._write_scheduler_task is current_task:
                self._write_scheduler_task = None

    async def _send_scheduled_write_round(
        self, jobs: list[_QueuedDuplexWrite], *, dispatch_started_ns: int = 0,
    ) -> None:
        records: list[tuple[_QueuedDuplexWrite, _ScheduledWriteTicket]] = []
        if self.collect_write_metrics and not dispatch_started_ns:
            dispatch_started_ns = time.perf_counter_ns()
        lock_acquired_ns = encode_started_ns = encode_finished_ns = 0
        drain_started_ns = drain_finished_ns = 0
        try:
            async with self._send_lock:
                if self.collect_write_metrics:
                    lock_acquired_ns = time.perf_counter_ns()
                await self._assert_circuit_usable_unlocked()
                if any(hop.next_sequence + len(jobs) > MAX_COMMANDS_PER_CIRCUIT for hop in self.hops):
                    raise ValueError("fair write round would exceed the circuit command budget; rebuild the circuit")
                assert self._writer is not None
                if self.collect_write_metrics:
                    encode_started_ns = time.perf_counter_ns()
                for job in jobs:
                    if job.sent_future.cancelled():
                        continue
                    stream = self._active_duplex_streams.get(job.logical_stream_id)
                    if stream is None or stream._closed or stream._write_closed:
                        raise ValueError("scheduled WRITE refers to a closed stream")
                    last = self.hops[-1]
                    used_sequences: dict[str, int] = {last.descriptor.relay_id: last.next_sequence}
                    used_stream_ids = dict(stream.hop_stream_ids)
                    last_sid = used_stream_ids[last.descriptor.relay_id]
                    plaintext = _COMMAND_HEADER.pack(last.next_sequence, last_sid, ord("W")) + _encode_stream_write_body(job.payload)
                    packet = seal(
                        last.keys.request_key, plaintext, _aad(REQUEST_AAD_PREFIX, last.descriptor.relay_id)
                    )
                    last.next_sequence += 1
                    for index in range(len(self.hops) - 2, -1, -1):
                        hop = self.hops[index]
                        child = self.hops[index + 1]
                        used_sequences[hop.descriptor.relay_id] = hop.next_sequence
                        packet_body = _encode_forward(
                            hop.next_sequence, used_stream_ids[hop.descriptor.relay_id],
                            used_sequences[child.descriptor.relay_id], used_stream_ids[child.descriptor.relay_id],
                            packet, kind=FORWARD_WRITE_STREAM,
                        )
                        packet = seal(
                            hop.keys.request_key, packet_body, _aad(REQUEST_AAD_PREFIX, hop.descriptor.relay_id)
                        )
                        hop.next_sequence += 1
                    guard = self.hops[0]
                    response_key = (
                        used_sequences[guard.descriptor.relay_id],
                        used_stream_ids[guard.descriptor.relay_id],
                    )
                    response_future = self._register_pending(*response_key)
                    ticket = _ScheduledWriteTicket(
                        used_sequences, used_stream_ids, response_key, response_future
                    )
                    records.append((job, ticket))
                    self._writer.write(frame(packet))
                    self._write_scheduler_trace.append(job.logical_stream_id)
                if self.collect_write_metrics:
                    encode_finished_ns = time.perf_counter_ns()
                if records:
                    self._touch_activity()
                    if self.collect_write_metrics:
                        drain_started_ns = time.perf_counter_ns()
                    await self._writer.drain()
                    if self.collect_write_metrics:
                        drain_finished_ns = time.perf_counter_ns()
                    if self.collect_write_metrics:
                        queue_wait_samples = sorted(
                            max(0, dispatch_started_ns - job.enqueued_ns) / 1_000_000
                            for job, _ in records if job.enqueued_ns
                        )
                        if queue_wait_samples:
                            p95_index = min(
                                len(queue_wait_samples) - 1,
                                math.ceil((len(queue_wait_samples) - 1) * 0.95),
                            )
                            middle = len(queue_wait_samples) // 2
                            queue_wait_median = (
                                queue_wait_samples[middle] if len(queue_wait_samples) % 2
                                else (queue_wait_samples[middle - 1] + queue_wait_samples[middle]) / 2
                            )
                            self._record_write_metric({
                                "event": "dispatch_round",
                                "scheduler": "round_robin",
                                "commands": len(records),
                                "bytes": sum(len(job.payload) for job, _ in records),
                                "queue_wait_median_ms": queue_wait_median,
                                "queue_wait_p95_ms": queue_wait_samples[p95_index],
                                "queue_wait_max_ms": queue_wait_samples[-1],
                                "send_lock_wait_ms": (lock_acquired_ns - dispatch_started_ns) / 1_000_000,
                                "frame_prepare_ms": (encode_finished_ns - encode_started_ns) / 1_000_000,
                                "socket_drain_ms": (drain_finished_ns - drain_started_ns) / 1_000_000,
                            })
                for job, ticket in records:
                    if not job.sent_future.done():
                        job.sent_future.set_result(ticket)
        except Exception:
            for _, ticket in records:
                self._pending_replies.pop(ticket.response_key, None)
                if not ticket.response_future.done():
                    ticket.response_future.cancel()
            # Some bytes may already be queued to the socket. Never continue using
            # a circuit whose outbound sequence allocation or write status is uncertain.
            await self._close_unlocked()
            raise

    async def _release_scheduled_write_budget(self, jobs: list[_QueuedDuplexWrite]) -> None:
        async with self._write_queue_lock:
            self._scheduled_write_commands = max(0, self._scheduled_write_commands - len(jobs))
            self._scheduled_write_bytes = max(
                0, self._scheduled_write_bytes - sum(len(job.payload) for job in jobs)
            )

    async def _fail_queued_writes(self, error: BaseException) -> None:
        async with self._write_queue_lock:
            for queue in self._write_queues.values():
                for job in queue:
                    self._scheduled_write_commands = max(0, self._scheduled_write_commands - 1)
                    self._scheduled_write_bytes = max(0, self._scheduled_write_bytes - len(job.payload))
                    if not job.sent_future.done():
                        job.sent_future.set_exception(error)
            self._write_queues.clear()
            self._write_ready.clear()
            self._write_ready_set.clear()
            self._write_scheduler_event.clear()

    def _discard_queued_writes_sync(self, error: BaseException) -> None:
        """Discard queued (not currently-dispatched) writes during circuit shutdown."""
        for queue in self._write_queues.values():
            for job in queue:
                self._scheduled_write_commands = max(0, self._scheduled_write_commands - 1)
                self._scheduled_write_bytes = max(0, self._scheduled_write_bytes - len(job.payload))
                if not job.sent_future.done():
                    job.sent_future.set_exception(error)
        self._write_queues.clear()
        self._write_ready.clear()
        self._write_ready_set.clear()
        self._write_scheduler_event.clear()

    async def _send_duplex_command(
        self, stream: DuplexCircuitStream, operation: str, body: bytes, forward_kind: int,
        *, timeout: float = 10.0,
    ) -> bytes:
        if len(self.hops) < 1 or self._writer is None:
            raise ValueError("client has no active circuit")
        async with self._send_lock:
            await self._assert_circuit_usable_unlocked()
            await self._ensure_command_budget()
            assert self._writer is not None
            last = self.hops[-1]
            used_sequences: dict[str, int] = {last.descriptor.relay_id: last.next_sequence}
            used_stream_ids = dict(stream.hop_stream_ids)
            last_sid = used_stream_ids[last.descriptor.relay_id]
            plaintext = _COMMAND_HEADER.pack(last.next_sequence, last_sid, ord(operation)) + body
            packet = seal(last.keys.request_key, plaintext, _aad(REQUEST_AAD_PREFIX, last.descriptor.relay_id))
            last.next_sequence += 1
            for index in range(len(self.hops) - 2, -1, -1):
                hop = self.hops[index]
                child = self.hops[index + 1]
                used_sequences[hop.descriptor.relay_id] = hop.next_sequence
                packet_body = _encode_forward(
                    hop.next_sequence, used_stream_ids[hop.descriptor.relay_id],
                    used_sequences[child.descriptor.relay_id], used_stream_ids[child.descriptor.relay_id],
                    packet, kind=forward_kind,
                )
                packet = seal(hop.keys.request_key, packet_body, _aad(REQUEST_AAD_PREFIX, hop.descriptor.relay_id))
                hop.next_sequence += 1
            guard = self.hops[0]
            guard_id = guard.descriptor.relay_id
            key = (used_sequences[guard_id], used_stream_ids[guard_id])
            future = self._register_pending(*key)
            try:
                self._touch_activity()
                self._writer.write(frame(packet))
                await self._writer.drain()
            except Exception:
                self._pending_replies.pop(key, None)
                if not future.done():
                    future.cancel()
                await self._close_unlocked()
                raise
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            for hop in self.hops:
                rid = hop.descriptor.relay_id
                response = _open_reply(
                    hop.keys.response_key, rid, used_sequences[rid], response,
                    used_stream_ids[rid],
                )
            await self._check_after_stream_response()
            self._touch_activity()
            return response
        except Exception:
            await self.close()
            raise

    async def open_stream(self, destination_host: str, destination_port: int) -> DuplexCircuitStream:
        """Open an experimental full-duplex TCP stream through a built circuit.

        The destination is still restricted to an allowlisted literal loopback
        endpoint on the exit relay. Reads are bounded by a 64 KiB per-stream
        credit window; writes are bounded to one 256 KiB command per acknowledgement.
        """
        _ensure_loopback(destination_host)
        if not isinstance(destination_port, int) or isinstance(destination_port, bool) or not 1 <= destination_port <= 65535:
            raise ValueError("destination port must be within 1..65535")
        async with self._stream_open_lock:
            if len(self._active_streams) + len(self._active_duplex_streams) >= self.max_active_streams:
                raise ValueError("client active-stream limit exceeded")
            hop_stream_ids = self._allocate_hop_stream_ids()
            stream = DuplexCircuitStream(self, self._allocate_logical_id(), hop_stream_ids)
            # Reserve IDs before the first await so concurrent one-shot and
            # duplex opens cannot allocate the same per-hop stream ID.
            self._active_duplex_streams[stream.logical_id] = stream
            try:
                reply = await self._send_duplex_command(
                    stream, "O", _encode_stream_open_body(destination_host, destination_port), FORWARD_OPEN_STREAM
                )
                if reply != b"STREAM_OPENED":
                    raise ValueError("invalid stream-open acknowledgement")
                reply = await self._send_duplex_command(stream, "B", b"", FORWARD_START_STREAM)
                if reply != b"STREAM_STARTED":
                    raise ValueError("invalid stream-start acknowledgement")
                return stream
            except Exception:
                self._active_duplex_streams.pop(stream.logical_id, None)
                stream._closed = True
                await self.close()
                raise

    async def request_echo(self, destination_host: str, destination_port: int, payload: bytes) -> bytes:
        stream = await self.start_echo(destination_host, destination_port, payload)
        try:
            return await stream.result()
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await stream.cancel()
            raise

    async def _cancel_stream(self, stream: CircuitStream) -> bool:
        if stream._finished or stream.logical_id not in self._active_streams:
            return False
        if stream._response_future.done():
            return False
        async with self._send_lock:
            await self._assert_circuit_usable_unlocked()
            await self._ensure_command_budget()
            assert self._writer is not None
            # The stream ID on each hop is hop-local; cancellation follows the
            # already-built circuit and carries only the next-hop correlation.
            last = self.hops[-1]
            used_sequences = {last.descriptor.relay_id: last.next_sequence}
            used_stream_ids = {last.descriptor.relay_id: stream.hop_stream_ids[last.descriptor.relay_id]}
            body = _STREAM_ID.pack(used_stream_ids[last.descriptor.relay_id])
            packet = seal(
                last.keys.request_key,
                _COMMAND_HEADER.pack(last.next_sequence, used_stream_ids[last.descriptor.relay_id], ord("X")) + body,
                _aad(REQUEST_AAD_PREFIX, last.descriptor.relay_id),
            )
            last.next_sequence += 1
            for index in range(len(self.hops) - 2, -1, -1):
                hop = self.hops[index]
                child = self.hops[index + 1]
                used_sequences[hop.descriptor.relay_id] = hop.next_sequence
                used_stream_ids[hop.descriptor.relay_id] = stream.hop_stream_ids[hop.descriptor.relay_id]
                body = _encode_forward(
                    hop.next_sequence, used_stream_ids[hop.descriptor.relay_id],
                    used_sequences[child.descriptor.relay_id], used_stream_ids[child.descriptor.relay_id],
                    packet, kind=FORWARD_CANCEL,
                )
                packet = seal(hop.keys.request_key, body, _aad(REQUEST_AAD_PREFIX, hop.descriptor.relay_id))
                hop.next_sequence += 1
            guard = self.hops[0]
            guard_id = guard.descriptor.relay_id
            cancel_future = self._register_pending(
                used_sequences[guard_id], used_stream_ids[guard_id]
            )
            try:
                self._touch_activity()
                self._writer.write(frame(packet))
                await self._writer.drain()
            except Exception:
                self._pending_replies.pop((used_sequences[guard_id], used_stream_ids[guard_id]), None)
                if not cancel_future.done():
                    cancel_future.cancel()
                await self._close_unlocked()
                raise
        try:
            envelope = await asyncio.wait_for(cancel_future, timeout=10)
            response = envelope
            for hop in self.hops:
                rid = hop.descriptor.relay_id
                response = _open_reply(
                    hop.keys.response_key, rid, used_sequences[rid], response,
                    used_stream_ids[rid],
                )
            if not response.startswith((b"CANCELLED", b"NOT_ACTIVE")):
                raise ValueError("invalid stream cancellation acknowledgement")
        except Exception:
            await self.close()
            raise
        original_guard = self.hops[0].descriptor.relay_id if self.hops else None
        original_key = (
            stream.used_sequences[original_guard], stream.hop_stream_ids[original_guard]
        ) if original_guard is not None else None
        original_future = stream._response_future
        completed_before_cancel = original_future.done() and not original_future.cancelled()
        if completed_before_cancel:
            # A response may win the race while the cancellation acknowledgement
            # is travelling back. Preserve it for result() rather than claiming
            # the cancellation succeeded.
            self._touch_activity()
            return False
        if original_key is not None and not original_future.done():
            self._pending_replies.pop(original_key, None)
            self._ignored_replies.add(original_key)
            original_future.cancel()
        self._active_streams.pop(stream.logical_id, None)
        stream._finished = True
        stream._cancelled = True
        self._touch_activity()
        return response == b"CANCELLED"

    async def close(self) -> None:
        async with self._io_lock:
            async with self._send_lock:
                await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        task = self._reader_task
        self._reader_task = None
        scheduler_task = self._write_scheduler_task
        self._write_scheduler_task = None
        self._discard_queued_writes_sync(ConnectionError("circuit closed before scheduled WRITE dispatch"))
        if scheduler_task is not None and scheduler_task is not asyncio.current_task():
            scheduler_task.cancel()
        self.hops.clear()
        self._verified_route = None
        self._created_at = None
        self._last_activity = None
        for future in self._pending_replies.values():
            if not future.done():
                future.cancel()
        self._pending_replies.clear()
        self._ignored_replies.clear()
        self._ignored_events.clear()
        for stream in self._active_streams.values():
            stream._finished = True
            if not stream._response_future.done():
                stream._response_future.cancel()
        self._active_streams.clear()
        for stream in self._active_duplex_streams.values():
            stream._fail(ConnectionError("circuit was closed"))
            stream._closed = True
        self._active_duplex_streams.clear()
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if scheduler_task is not None and scheduler_task is not asyncio.current_task():
            await asyncio.gather(scheduler_task, return_exceptions=True)
        if writer is not None:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()


async def serve_node(node: RelayNode, host: str = "127.0.0.1", port: int = 0) -> asyncio.AbstractServer:
    _ensure_loopback(host)
    server = await asyncio.start_server(node.handle, host, port, limit=MAX_FRAME_BYTES + 4)
    node.port = int(server.sockets[0].getsockname()[1])
    node.bound_host = host
    return server


async def build_three_hop_lab_circuit(
    descriptors: list[RelayDescriptor],
) -> dict[str, Any]:
    """Build a circuit in a running testbed; intended for the CLI smoke test."""
    if not descriptors or len(descriptors) > MAX_HOPS:
        raise ValueError(f"descriptor list must contain 1..{MAX_HOPS} hops")
    client = TelescopingClient()
    await client.connect_guard(descriptors[0])
    try:
        for descriptor in descriptors[1:]:
            await client.extend(descriptor)
        return {
            "hops_built": len(client.hops),
            "direct_client_connections": client.direct_connections_opened,
            "relay_ids": [hop.descriptor.relay_id for hop in client.hops],
            "all_directional_keys_distinct": len({
                hop.keys.request_key for hop in client.hops
            }) == len(client.hops) and len({
                hop.keys.response_key for hop in client.hops
            }) == len(client.hops),
        }
    finally:
        await client.close()
