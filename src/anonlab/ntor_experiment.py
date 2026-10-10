"""Experimental ntor-based per-relay key agreement for the AEGIS lab.

The handshake message layout and ntor authentication transcript follow the
published Tor ntor v1 specification. The final key expansion is intentionally
MALEBOLGE-specific because this lab uses ChaCha20-Poly1305 envelope keys rather
than Tor relay-cell keys. This module is not wire-compatible with Tor and is not
approved for use outside the local research harness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey,
        X25519PublicKey,
    )
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
except ImportError as exc:  # pragma: no cover - exercised without optional extra
    raise RuntimeError(
        "The ntor experiment requires the optional dependency: "
        "python -m pip install 'rea-anon-lab[onion-lab]'"
    ) from exc

PROTOID = b"ntor-curve25519-sha256-1"
_T_MAC = PROTOID + b":mac"
_T_KEY = PROTOID + b":key_extract"
_T_VERIFY = PROTOID + b":verify"
# Legacy v1 domain-separation label is intentionally retained after the AEGIS rebrand; changing it changes derived keys.
_MALEBOLGE_KDF_INFO = PROTOID + b":key_expand:MALEBOLGE_AEAD_v1"
IDENTITY_DIGEST_BYTES = 20
PUBLIC_KEY_BYTES = 32
AUTH_BYTES = 32
CLIENT_HANDSHAKE_BYTES = IDENTITY_DIGEST_BYTES + PUBLIC_KEY_BYTES * 2
SERVER_HANDSHAKE_BYTES = PUBLIC_KEY_BYTES + AUTH_BYTES
KEY_BYTES = 32


def _raw_public_key(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _validate_identity(identity_digest: bytes) -> None:
    if not isinstance(identity_digest, bytes) or len(identity_digest) != IDENTITY_DIGEST_BYTES:
        raise ValueError(f"relay identity digest must be exactly {IDENTITY_DIGEST_BYTES} bytes")


def _validate_public_key(key: bytes, label: str) -> None:
    if not isinstance(key, bytes) or len(key) != PUBLIC_KEY_BYTES:
        raise ValueError(f"{label} must be exactly {PUBLIC_KEY_BYTES} bytes")


def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def _secret_input(
    ephemeral_shared: bytes,
    static_shared: bytes,
    identity_digest: bytes,
    onion_public_key: bytes,
    client_public_key: bytes,
    relay_ephemeral_public_key: bytes,
) -> bytes:
    return (
        ephemeral_shared
        + static_shared
        + identity_digest
        + onion_public_key
        + client_public_key
        + relay_ephemeral_public_key
        + PROTOID
    )


@dataclass(frozen=True, slots=True)
class NtorSessionKeys:
    """Separate AEAD keys for client-to-relay and relay-to-client traffic."""

    request_key: bytes
    response_key: bytes

    def __post_init__(self) -> None:
        if len(self.request_key) != KEY_BYTES or len(self.response_key) != KEY_BYTES:
            raise ValueError("session keys must each be 32 bytes")
        if hmac.compare_digest(self.request_key, self.response_key):
            raise ValueError("directional session keys must be independent")


@dataclass(slots=True)
class NtorClientState:
    """One-shot client state; discard after ``client_finish`` succeeds or fails."""

    identity_digest: bytes
    onion_public_key: bytes
    client_public_key: bytes
    client_handshake: bytes
    ephemeral_private_key: X25519PrivateKey = field(repr=False)
    _finished: bool = field(default=False, init=False, repr=False)


def _derive_session_keys(secret_input: bytes) -> NtorSessionKeys:
    # The ntor transcript/key extraction is standard; the info string is
    # deliberately MALEBOLGE-specific to avoid cross-protocol key reuse.
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES * 2,
        salt=_T_KEY,
        info=_MALEBOLGE_KDF_INFO,
    ).derive(secret_input)
    return NtorSessionKeys(material[:KEY_BYTES], material[KEY_BYTES:])


class NtorReplayGuard:
    """Bounded fail-closed replay guard for client ephemeral handshakes.

    The guard is process-local and resets on restart. It intentionally has no
    eviction: when full, the relay rejects new handshakes instead of forgetting
    replay history. Production needs a reviewed DoS/rate-limit strategy.
    """

    def __init__(self, max_handshakes: int = 100_000) -> None:
        if not isinstance(max_handshakes, int) or isinstance(max_handshakes, bool) or max_handshakes < 1:
            raise ValueError("max_handshakes must be a positive integer")
        self._max_handshakes = max_handshakes
        self._seen: set[tuple[bytes, bytes]] = set()

    def claim(self, identity_digest: bytes, client_public_key: bytes) -> None:
        _validate_identity(identity_digest)
        _validate_public_key(client_public_key, "client public key")
        token = (identity_digest, client_public_key)
        if token in self._seen:
            raise ValueError("replayed ntor client ephemeral key")
        if len(self._seen) >= self._max_handshakes:
            raise ValueError("ntor replay guard is full; relay must fail closed")
        self._seen.add(token)

    @property
    def count(self) -> int:
        return len(self._seen)


def client_start(identity_digest: bytes, onion_public_key: bytes) -> tuple[NtorClientState, bytes]:
    """Begin a one-hop ntor handshake using a pinned relay descriptor.

    The caller must obtain ``identity_digest`` and ``onion_public_key`` from an
    authenticated directory/descriptor. The handshake itself does not create
    trust in arbitrary caller-supplied directory data.
    """
    _validate_identity(identity_digest)
    _validate_public_key(onion_public_key, "relay onion public key")
    # Parse immediately; X25519.exchange performs the definitive low-order check.
    X25519PublicKey.from_public_bytes(onion_public_key)
    private_key = X25519PrivateKey.generate()
    public_key = _raw_public_key(private_key.public_key())
    message = identity_digest + onion_public_key + public_key
    return (
        NtorClientState(
            identity_digest=identity_digest,
            onion_public_key=onion_public_key,
            client_public_key=public_key,
            client_handshake=message,
            ephemeral_private_key=private_key,
        ),
        message,
    )


def relay_respond(
    client_handshake: bytes,
    expected_identity_digest: bytes,
    onion_private_key: X25519PrivateKey,
    *,
    replay_guard: NtorReplayGuard | None = None,
) -> tuple[bytes, NtorSessionKeys]:
    """Respond to the v1 ntor handshake and derive this hop's session keys."""
    _validate_identity(expected_identity_digest)
    if not isinstance(client_handshake, bytes) or len(client_handshake) != CLIENT_HANDSHAKE_BYTES:
        raise ValueError("client ntor handshake has an invalid length")

    identity_digest = client_handshake[:IDENTITY_DIGEST_BYTES]
    onion_public_key = client_handshake[IDENTITY_DIGEST_BYTES : IDENTITY_DIGEST_BYTES + PUBLIC_KEY_BYTES]
    client_public_bytes = client_handshake[IDENTITY_DIGEST_BYTES + PUBLIC_KEY_BYTES :]
    if not hmac.compare_digest(identity_digest, expected_identity_digest):
        raise ValueError("client handshake names a different relay identity")

    local_onion_public = _raw_public_key(onion_private_key.public_key())
    if not hmac.compare_digest(onion_public_key, local_onion_public):
        raise ValueError("client handshake contains a stale or incorrect relay onion key")

    client_public_key = X25519PublicKey.from_public_bytes(client_public_bytes)
    # Compute the static DH before claiming replay state so malformed low-order
    # points do not consume entries in the guard.
    try:
        static_shared = onion_private_key.exchange(client_public_key)
    except ValueError as exc:
        raise ValueError("client supplied an invalid/low-order Curve25519 public key") from exc

    if replay_guard is not None:
        replay_guard.claim(identity_digest, client_public_bytes)

    relay_ephemeral_private = X25519PrivateKey.generate()
    relay_ephemeral_public = _raw_public_key(relay_ephemeral_private.public_key())
    try:
        ephemeral_shared = relay_ephemeral_private.exchange(client_public_key)
    except ValueError as exc:  # pragma: no cover - same peer point, checked above
        raise ValueError("client supplied an invalid/low-order Curve25519 public key") from exc

    secret = _secret_input(
        ephemeral_shared,
        static_shared,
        identity_digest,
        onion_public_key,
        client_public_bytes,
        relay_ephemeral_public,
    )
    verify = _hmac_sha256(_T_VERIFY, secret)
    auth_input = (
        verify
        + identity_digest
        + onion_public_key
        + relay_ephemeral_public
        + client_public_bytes
        + PROTOID
        + b"Server"
    )
    auth = _hmac_sha256(_T_MAC, auth_input)
    return relay_ephemeral_public + auth, _derive_session_keys(secret)


def client_finish(state: NtorClientState, relay_handshake: bytes) -> NtorSessionKeys:
    """Authenticate the relay response and derive matching directional keys."""
    if state._finished:
        raise ValueError("ntor client state is one-shot and has already been consumed")
    state._finished = True
    if not isinstance(relay_handshake, bytes) or len(relay_handshake) != SERVER_HANDSHAKE_BYTES:
        raise ValueError("relay ntor handshake has an invalid length")

    relay_ephemeral_public = relay_handshake[:PUBLIC_KEY_BYTES]
    received_auth = relay_handshake[PUBLIC_KEY_BYTES:]
    relay_public_key = X25519PublicKey.from_public_bytes(relay_ephemeral_public)
    static_public_key = X25519PublicKey.from_public_bytes(state.onion_public_key)
    try:
        ephemeral_shared = state.ephemeral_private_key.exchange(relay_public_key)
        static_shared = state.ephemeral_private_key.exchange(static_public_key)
    except ValueError as exc:
        raise ValueError("relay supplied an invalid/low-order Curve25519 public key") from exc

    secret = _secret_input(
        ephemeral_shared,
        static_shared,
        state.identity_digest,
        state.onion_public_key,
        state.client_public_key,
        relay_ephemeral_public,
    )
    verify = _hmac_sha256(_T_VERIFY, secret)
    auth_input = (
        verify
        + state.identity_digest
        + state.onion_public_key
        + relay_ephemeral_public
        + state.client_public_key
        + PROTOID
        + b"Server"
    )
    expected_auth = _hmac_sha256(_T_MAC, auth_input)
    if not hmac.compare_digest(received_auth, expected_auth):
        raise ValueError("relay ntor authentication failed")
    return _derive_session_keys(secret)
