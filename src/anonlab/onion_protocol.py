"""AEGIS experimental binary onion envelopes for the loopback lab only.

Protocol v2 adds per-circuit identifiers, monotonically increasing sequence
numbers, and response-side sequence validation. Keys are still pre-shared, so
this remains a lab harness rather than a secure public-network protocol.
"""
from __future__ import annotations

import os
import struct

try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
except ImportError as exc:  # pragma: no cover - exercised without optional extra
    raise RuntimeError(
        "The encrypted onion prototype requires the optional dependency: "
        "python -m pip install 'rea-anon-lab[onion-lab]'"
    ) from exc

VERSION = 2
NONCE_BYTES = 12
TAG_BYTES = 16
CIRCUIT_ID_BYTES = 16
MAX_SEQUENCE = (1 << 64) - 1
MAX_FRAME_BYTES = 16 * 1024 * 1024
# Encrypted request header: version(1), flags(1), next_port(2), payload_len(4),
# circuit_id(16), sequence(8). Sequence and identifier remain hidden by AEAD.
_REQUEST_HEADER = struct.Struct("!BBHI16sQ")
# Encrypted response header: version(1), circuit_id(16), sequence(8), payload_len(4).
_RESPONSE_HEADER = struct.Struct("!B16sQI")
REQUEST_PREFIX = b"MALEBOLGE/2/request/"
RESPONSE_PREFIX = b"MALEBOLGE/2/response/"


class CircuitReplayGuard:
    """Process-local, fail-closed circuit-id registry for the lab harness.

    IDs are never evicted while the relay process is alive. This makes captured
    first frames fail on reconnect but intentionally limits process lifetime;
    production should use fresh ephemeral circuit keys and a reviewed replay
    window rather than treating this registry as a distributed solution.
    """

    def __init__(self, max_circuits: int = 100_000) -> None:
        if max_circuits < 1:
            raise ValueError("max_circuits must be positive")
        self._max_circuits = max_circuits
        self._seen: set[bytes] = set()

    def claim(self, circuit_id: bytes) -> None:
        if not isinstance(circuit_id, bytes) or len(circuit_id) != CIRCUIT_ID_BYTES:
            raise ValueError("circuit_id must contain exactly 16 bytes")
        if circuit_id in self._seen:
            raise ValueError("replayed circuit identifier")
        if len(self._seen) >= self._max_circuits:
            raise ValueError("circuit replay registry is full; relay must fail closed")
        self._seen.add(circuit_id)

    @property
    def count(self) -> int:
        return len(self._seen)


def _aad(direction: bytes, relay_id: str) -> bytes:
    if not relay_id or len(relay_id) > 80 or not relay_id.isascii():
        raise ValueError("relay_id must be 1..80 ASCII characters")
    return direction + relay_id.encode("ascii")


def _validate_circuit_fields(circuit_id: bytes, sequence: int) -> None:
    if not isinstance(circuit_id, bytes) or len(circuit_id) != CIRCUIT_ID_BYTES:
        raise ValueError("circuit_id must contain exactly 16 bytes")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= MAX_SEQUENCE:
        raise ValueError("sequence must be an unsigned 64-bit integer")


def seal(key: bytes, plaintext: bytes, associated_data: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("ChaCha20-Poly1305 keys must contain exactly 32 bytes")
    nonce = os.urandom(NONCE_BYTES)
    return nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, associated_data)


def open_sealed(key: bytes, envelope: bytes, associated_data: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("ChaCha20-Poly1305 keys must contain exactly 32 bytes")
    if len(envelope) < NONCE_BYTES + TAG_BYTES:
        raise ValueError("encrypted envelope is too short")
    return ChaCha20Poly1305(key).decrypt(envelope[:NONCE_BYTES], envelope[NONCE_BYTES:], associated_data)


def frame(payload: bytes) -> bytes:
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError(f"frame exceeds maximum of {MAX_FRAME_BYTES} bytes")
    return struct.pack("!I", len(payload)) + payload


def parse_request_layer(key: bytes, relay_id: str, packet: bytes) -> dict[str, object]:
    plaintext = open_sealed(key, packet, _aad(REQUEST_PREFIX, relay_id))
    if len(plaintext) < _REQUEST_HEADER.size:
        raise ValueError("request layer is shorter than its binary header")
    version, flags, next_port, payload_length, circuit_id, sequence = _REQUEST_HEADER.unpack_from(plaintext)
    if version != VERSION:
        raise ValueError("unsupported onion envelope version")
    if flags not in (0, 1):
        raise ValueError("unsupported request-layer flags")
    if not 1 <= next_port <= 65535:
        raise ValueError("next_port is invalid")
    _validate_circuit_fields(circuit_id, sequence)
    payload = plaintext[_REQUEST_HEADER.size :]
    if payload_length != len(payload) or payload_length > MAX_FRAME_BYTES:
        raise ValueError("request payload length is invalid")
    return {
        "terminal": bool(flags),
        "next_host": "127.0.0.1",
        "next_port": next_port,
        "payload": payload,
        "circuit_id": circuit_id,
        "sequence": sequence,
    }


def build_request(
    payload: bytes,
    relay_ports: list[int],
    keys: list[bytes],
    destination_port: int,
    *,
    circuit_id: bytes,
    sequence: int = 0,
) -> bytes:
    """Create nested binary layers; relays authenticate/decrypt only their own layer."""
    if not relay_ports or len(relay_ports) != len(keys):
        raise ValueError("relay_ports and keys must have the same non-zero length")
    if any(not 1 <= port <= 65535 for port in relay_ports):
        raise ValueError("relay port outside the TCP port range")
    if not 1 <= destination_port <= 65535:
        raise ValueError("destination port outside the TCP port range")
    if any(len(key) != 32 for key in keys):
        raise ValueError("every relay key must contain 32 bytes")
    _validate_circuit_fields(circuit_id, sequence)
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError(f"payload exceeds maximum of {MAX_FRAME_BYTES} bytes")

    inner = payload
    for index in range(len(relay_ports) - 1, -1, -1):
        terminal = index == len(relay_ports) - 1
        next_port = destination_port if terminal else relay_ports[index + 1]
        header = _REQUEST_HEADER.pack(VERSION, int(terminal), next_port, len(inner), circuit_id, sequence)
        inner = seal(keys[index], header + inner, _aad(REQUEST_PREFIX, f"relay-{index + 1}"))
    return inner


def wrap_response(
    key: bytes,
    relay_id: str,
    payload: bytes,
    *,
    circuit_id: bytes,
    sequence: int,
) -> bytes:
    _validate_circuit_fields(circuit_id, sequence)
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError(f"response exceeds maximum of {MAX_FRAME_BYTES} bytes")
    header = _RESPONSE_HEADER.pack(VERSION, circuit_id, sequence, len(payload))
    return seal(key, header + payload, _aad(RESPONSE_PREFIX, relay_id))


def unwrap_response(
    key: bytes,
    relay_id: str,
    envelope: bytes,
    *,
    circuit_id: bytes,
    expected_sequence: int,
) -> bytes:
    _validate_circuit_fields(circuit_id, expected_sequence)
    plaintext = open_sealed(key, envelope, _aad(RESPONSE_PREFIX, relay_id))
    if len(plaintext) < _RESPONSE_HEADER.size:
        raise ValueError("response layer is shorter than its binary header")
    version, actual_circuit_id, sequence, payload_length = _RESPONSE_HEADER.unpack_from(plaintext)
    if version != VERSION:
        raise ValueError("unsupported response envelope version")
    if actual_circuit_id != circuit_id:
        raise ValueError("response circuit identifier mismatch")
    if sequence != expected_sequence:
        raise ValueError("response sequence mismatch (replay, reordering, or circuit desynchronization)")
    payload = plaintext[_RESPONSE_HEADER.size :]
    if payload_length != len(payload) or payload_length > MAX_FRAME_BYTES:
        raise ValueError("response payload length is invalid")
    return payload
