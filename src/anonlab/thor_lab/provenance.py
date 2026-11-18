"""Run provenance: code revision, environment and configuration digest.

A measurement without provenance is not evidence. Every THOR run writes one
manifest containing the exact ``git`` revision, whether the working tree was
dirty, the interpreter and platform, the dependency versions that can change a
measurement, the seed and a canonical digest of the full configuration. The
summary repeats the revision and refuses to compare artifacts whose digests do
not match the ones recorded in their manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "canonical_digest",
    "code_revision",
    "environment",
    "manifest",
    "repository_root",
]

_GIT_TIMEOUT_S = 20.0


def repository_root(start: Path | None = None) -> Path | None:
    """Walk up from this file to the checkout that contains it, if any."""
    candidate = (start or Path(__file__).resolve()).resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _run_git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def code_revision(root: Path | None = None) -> dict[str, object]:
    """Return ``{"revision", "dirty", "describe"}`` for the checkout, or nulls.

    A dirty tree is not an error for exploratory runs, but the artifact is then
    labelled ``dirty`` and the report must not present it as reproducible.
    """
    checkout = root or repository_root()
    if checkout is None:
        return {"revision": None, "dirty": None, "describe": None, "source": "no_git_checkout"}
    revision = _run_git(checkout, "rev-parse", "HEAD")
    status = _run_git(checkout, "status", "--porcelain", "--untracked-files=no")
    describe = _run_git(checkout, "describe", "--always", "--dirty")
    return {
        "revision": revision,
        "dirty": None if status is None else bool(status),
        "describe": describe,
        "source": "git",
        "checkout": str(checkout),
    }


def _package_version() -> str | None:
    try:
        from .. import __version__  # noqa: PLC0415 - avoids an import cycle at module load
    except Exception:  # noqa: BLE001 - packaging metadata is optional
        return None
    return str(__version__)


def _optional_version(module: str) -> str | None:
    try:
        imported = __import__(module)
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    return str(getattr(imported, "__version__", "unknown"))


def environment() -> dict[str, object]:
    """Host and interpreter facts that can change a measurement."""
    cpu_count = os.cpu_count()
    return {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or None,
        "cpu_count": cpu_count,
        "pid": os.getpid(),
        "aegis_version": _package_version(),
        "dependencies": {
            "cryptography": _optional_version("cryptography"),
            "psutil": _optional_version("psutil"),
        },
    }


def canonical_digest(payload: Mapping[str, object] | list[object] | str | int | float | bool | None) -> str:
    """SHA-256 over a canonical JSON encoding (sorted keys, no whitespace)."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest(
    *,
    configuration: Mapping[str, object],
    seed: int,
    tier: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the manifest written next to every raw trial file."""
    if tier not in {"lab", "emulated", "public"}:
        raise ValueError("tier must be one of lab, emulated, public")
    created = time.time()
    payload: dict[str, object] = {
        "schema_version": 1,
        "created_unix": created,
        "created_local": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(created)),
        "tier": tier,
        "seed": seed,
        "code": code_revision(),
        "environment": environment(),
        "configuration": dict(configuration),
        "configuration_digest": canonical_digest(dict(configuration)),
        "claim_scope": (
            "Measurement artifact. It does not establish anonymity, security, "
            "Tor equivalence, or public-network performance."
        ),
    }
    if extra:
        payload["extra"] = dict(extra)
    return payload
