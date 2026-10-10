"""Runnable loopback-only signed-directory demonstration for AEGIS."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization

from .directory import (
    DirectoryAuthority,
    DirectoryVerifier,
    create_relay_descriptor,
    descriptor_from_json,
    descriptor_to_json,
)


def _raw_x25519_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def run_demo() -> dict[str, Any]:
    """Exercise issuance, rotation, persistent reload, route invalidation and revocation."""
    now = int(time.time())
    authority = DirectoryAuthority.generate()
    relay_identity = Ed25519PrivateKey.generate()
    onion_key_v1 = X25519PrivateKey.generate()
    onion_key_v2 = X25519PrivateKey.generate()

    with tempfile.TemporaryDirectory(prefix="aegis-directory-demo-") as state_directory:
        state_path = Path(state_directory) / "directory-state.json"
        verifier = DirectoryVerifier(authority.public_key_bytes, state_path=state_path)
        empty_revocations = authority.sign_revocations([], epoch=1, now=now)
        verifier.apply_revocations(empty_revocations, now=now)

        descriptor_v1 = authority.certify(
            create_relay_descriptor(
                relay_identity, _raw_x25519_public(onion_key_v1), "127.0.0.1", 19001,
                now=now, valid_for_seconds=1800, sequence=1,
            ),
            now=now,
        )
        verified_v1 = verifier.verify_descriptor(
            descriptor_from_json(descriptor_to_json(descriptor_v1)), now=now
        )
        lab_descriptor = verified_v1.to_telescoping_descriptor()

        descriptor_v2 = authority.certify(
            create_relay_descriptor(
                relay_identity, _raw_x25519_public(onion_key_v2), "127.0.0.1", 19001,
                now=now, valid_for_seconds=1800, sequence=2,
            ),
            now=now,
        )
        verified_v2 = verifier.verify_descriptor(descriptor_v2, now=now)
        route_v2 = verifier.verify_circuit_route([descriptor_v2], now=now)

        # Simulate process restart: the high-water mark and signed snapshot are reloaded.
        restarted = DirectoryVerifier(authority.public_key_bytes, state_path=state_path)
        restarted.apply_revocations(empty_revocations, now=now)
        persistent_state_reloaded = restarted.verify_descriptor(descriptor_v2, now=now).sequence == 2
        rollback_rejected = False
        try:
            restarted.verify_descriptor(descriptor_v1, now=now)
        except ValueError as exc:
            rollback_rejected = "rollback" in str(exc)

        revocations = authority.sign_revocations(
            [verified_v2.relay_id], epoch=2, now=now + 1, valid_for_seconds=1800
        )
        # Advance both still-running and restarted verifier instances over the
        # same durable state so the extant in-memory route must become stale.
        verifier.apply_revocations(revocations, now=now + 1)
        restarted.apply_revocations(revocations, now=now + 1)
        revoked_rejected = False
        try:
            restarted.verify_descriptor(descriptor_v2, now=now + 1)
        except ValueError as exc:
            revoked_rejected = "revoked" in str(exc)
        route_invalidated = False
        try:
            route_v2.assert_usable(now=now + 1)
        except ValueError as exc:
            route_invalidated = "invalidated" in str(exc)

        return {
            "component": "AEGIS signed relay directory demo",
            "is_live_network_test": False,
            "is_security_proof": False,
            "authority_public_key_pinned_out_of_band": True,
            "descriptor_v1_verified": True,
            "descriptor_v1_converted_to_loopback_circuit_type": (
                lab_descriptor.host == "127.0.0.1" and lab_descriptor.port == 19001
            ),
            "descriptor_v2_onion_key_rotation_verified": verified_v2.sequence == 2,
            "persistent_state_reloaded": persistent_state_reloaded,
            "descriptor_rollback_rejected_after_restart": rollback_rejected,
            "revoked_descriptor_rejected": revoked_rejected,
            "verified_route_invalidated_after_revocation_update": route_invalidated,
            "revocation_epoch": restarted.revocation_epoch,
            "limitations": [
                "loopback-only descriptors",
                "authority key is generated per demo and must be pinned through a separate trusted channel",
                "state file is local application state, not hardware-backed monotonic storage",
                "restoring an older valid state file can roll back observed freshness state",
                "directory authority is centralized in this experiment",
                "no multi-authority consensus, WAN transport, or independent audit",
            ],
        }


def main() -> None:
    print(json.dumps(run_demo(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
