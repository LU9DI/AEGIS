"""Optional ``cryptography`` dependency separation: crypto-free and crypto-full.

The suite must behave identically in both supported environments:

* environment A -- ``pip install .`` without the ``onion-lab`` extra, where
  ``importlib.util.find_spec("cryptography")`` is ``None``;
* environment B -- ``pip install '.[onion-lab]'`` with real primitives.

Tests that need the real library are skipped in environment A; the crypto-free
tests run everywhere because they block the package through ``sys.modules`` in a
fresh interpreter (a subprocess), which cannot leak state into the test process.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from anonlab import _crypto
from anonlab._crypto import (
    INSTALL_COMMAND,
    MissingCryptoDependency,
    MissingCryptographyError,
    available,
    missing_symbol,
    requires_crypto,
)

CRYPTO_AVAILABLE = available()
needs_crypto = pytest.mark.skipif(
    not CRYPTO_AVAILABLE,
    reason="install aegis-anon-lab[onion-lab] for real-cryptography assertions",
)

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

# Modules that mix pure and cryptographic functionality. Every one must import
# without the optional dependency.
MIXED_MODULES = (
    "anonlab._crypto",
    "anonlab.directory",
    "anonlab.directory_demo",
    "anonlab.duplex_benchmark",
    "anonlab.mixed_workload_benchmark",
    "anonlab.mixed_workload_matrix",
    "anonlab.network_impairment_benchmark",
    "anonlab.ntor_benchmark",
    "anonlab.ntor_experiment",
    "anonlab.onion_protocol",
    "anonlab.onion_relay",
    "anonlab.pir_manifest",
    "anonlab.telescoping",
    "anonlab.telescoping_benchmark",
    "anonlab.concurrency_benchmark",
    "anonlab.multiplex_benchmark",
    "anonlab.privacy_eval",
    "anonlab.cli",
)


def _run_without_cryptography(body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` in a fresh interpreter where ``cryptography`` cannot import."""
    script = textwrap.dedent(
        """
        import sys

        # A ``None`` entry makes ``import cryptography...`` raise ImportError and
        # ``anonlab._crypto.available()`` report False without touching disk.
        sys.modules["cryptography"] = None
        for _name in [name for name in sys.modules if name.startswith("cryptography.")]:
            del sys.modules[_name]
        """
    ) + textwrap.dedent(body)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_ROOT)
    env.pop("AEGIS_SIGNED", None)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )


def _run_in_subprocess(body: str, pythonpath: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath
    env.pop("AEGIS_SIGNED", None)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )


def _run_with_broken_cryptography(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` where a fake ``cryptography`` is installed but unimportable."""
    package = tmp_path / "cryptography"
    package.mkdir()
    (package / "__init__.py").write_text(
        'raise ImportError("libssl.so.3: cannot open shared object file")\n',
        encoding="utf-8",
    )
    return _run_in_subprocess(body, os.pathsep.join((str(tmp_path), str(SRC_ROOT))))


def test_crypto_modules_import_without_dependency() -> None:
    module_list = ", ".join(repr(name) for name in MIXED_MODULES)
    completed = _run_without_cryptography(
        f"""
        import importlib
        from anonlab._crypto import available, installed

        assert installed() is False, "the absence probe must not see the package"
        assert available() is False, "the optional dependency leaked into the test process"
        for name in ({module_list},):
            importlib.import_module(name)
        print("imported", len(({module_list},)))
        """
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"imported {len(MIXED_MODULES)}"


def test_guarded_entry_points_fail_closed_without_dependency() -> None:
    completed = _run_without_cryptography(
        f"""
        from anonlab._crypto import MissingCryptoDependency
        from anonlab import directory, ntor_experiment, onion_protocol, pir_manifest, telescoping

        install_hint = {INSTALL_COMMAND!r}
        attempts = {{
            "DirectoryAuthority.generate": lambda: directory.DirectoryAuthority.generate(),
            "create_relay_descriptor": lambda: directory.create_relay_descriptor(
                None, b"\\x01" * 32, "127.0.0.1", 19001
            ),
            "DirectoryVerifier": lambda: directory.DirectoryVerifier(b"\\x02" * 32),
            "client_start": lambda: ntor_experiment.client_start(b"\\x03" * 20, b"\\x04" * 32),
            "sign_snapshot_manifest": lambda: pir_manifest.sign_snapshot_manifest(
                private_key=None, snapshot_id="s", sequence=1, created_at=1,
                record_count=1, merkle_root=b"\\x05" * 32,
            ),
            "verify_snapshot_manifest": lambda: pir_manifest.verify_snapshot_manifest(None, None),
            "seal": lambda: onion_protocol.seal(b"k" * 32, b"payload", b"aad"),
            "_link_hello": lambda: telescoping._link_hello(None),
        }}
        for label, call in attempts.items():
            try:
                call()
            except MissingCryptoDependency as exc:
                assert "cryptography" in str(exc), (label, str(exc))
                assert install_hint in str(exc), (label, str(exc))
            else:
                raise AssertionError(f"{{label}} produced a result without cryptography")
        print("blocked", len(attempts))
        """
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "blocked 8"


def test_pure_functionality_survives_without_dependency() -> None:
    completed = _run_without_cryptography(
        """
        import hashlib
        from anonlab import directory, duplex_benchmark, onion_protocol, pir_manifest, telescoping
        from anonlab.model import ExperimentConfig
        from anonlab.profiles import DEFAULT_PROFILES
        from anonlab.simulator import run_suite

        digest = directory.relay_identity_digest(b"\\x07" * 32)
        assert digest == hashlib.sha256(b"MALEBOLGE/relay-identity/v1\\x00" + b"\\x07" * 32).digest()[:20]
        assert onion_protocol.frame(b"payload")[4:] == b"payload"
        manifest = pir_manifest.SnapshotManifest(1, "snap", 3, 10, 2, b"\\x08" * 32, b"\\x09" * 64)
        assert manifest.payload()["merkle_root"] == (b"\\x08" * 32).hex()
        assert telescoping.relay_id_for(b"m" * 20) == "6d" * 20
        assert duplex_benchmark._percentile([1.0, 2.0], 0.5) == 2.0
        # The privacy evaluation harness and simulator are dependency-free.
        results = run_suite(
            ExperimentConfig(duration_s=0.5, request_rate_per_s=1.0, seed=7), DEFAULT_PROFILES
        )
        assert results, "the dependency-free simulator produced no results"
        print("pure-ok", len(results))
        """
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("pure-ok")


def test_missing_symbol_never_simulates_cryptography() -> None:
    symbol = missing_symbol("X25519PrivateKey", "gossip test feature")
    with pytest.raises(MissingCryptoDependency) as call_error:
        symbol()
    assert "gossip test feature" in str(call_error.value)
    with pytest.raises(MissingCryptoDependency):
        symbol.generate()
    assert "unavailable cryptography.X25519PrivateKey" in repr(symbol)


def test_requires_crypto_guards_functions_methods_and_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    @requires_crypto("guarded function")
    def plain(value: int = 1) -> int:
        """Guarded function docstring."""
        calls.append("plain")
        return value

    class Guarded:
        @requires_crypto("guarded method")
        def method(self, value: int = 2) -> int:
            calls.append("method")
            return value

        @classmethod
        @requires_crypto("guarded classmethod")
        def build(cls, value: int = 3) -> int:
            calls.append("classmethod")
            return value

        @staticmethod
        @requires_crypto("guarded staticmethod")
        def static(value: int = 4) -> int:
            calls.append("staticmethod")
            return value

        @property
        @requires_crypto("guarded property")
        def prop(self) -> int:
            calls.append("property")
            return 5

        @requires_crypto("guarded init")
        def __init__(self) -> None:
            calls.append("init")

    monkeypatch.setattr(_crypto, "available", lambda: False)

    guarded_calls = [
        lambda: plain(),
        lambda: Guarded().method(),
        lambda: Guarded.build(),
        lambda: Guarded.static(),
        lambda: Guarded().prop,
        lambda: Guarded(),
    ]
    for call in guarded_calls:
        with pytest.raises(MissingCryptoDependency):
            call()
    assert calls == [], "a guarded body ran without cryptography"

    monkeypatch.setattr(_crypto, "available", lambda: True)
    assert plain() == 1
    instance = Guarded()
    assert instance.method() == 2
    assert Guarded.build() == 3
    assert Guarded.static() == 4
    assert instance.prop == 5
    assert calls == ["plain", "init", "method", "classmethod", "staticmethod", "property"]


def test_requires_crypto_preserves_coroutine_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from anonlab.duplex_benchmark import run_duplex_benchmark

    assert inspect.iscoroutinefunction(run_duplex_benchmark)
    monkeypatch.setattr(_crypto, "available", lambda: False)

    async def call() -> None:
        await run_duplex_benchmark(stream_count=1, payload_bytes=1024)

    with pytest.raises(MissingCryptoDependency):
        asyncio.run(call())


def test_requires_crypto_preserves_metadata_and_signature() -> None:
    from anonlab import directory, ntor_experiment, pir_manifest

    decorated = (
        directory.create_relay_descriptor,
        directory._public_bytes,
        directory.DirectoryAuthority.certify,
        directory.DirectoryAuthority.public_key_bytes,
        directory.DirectoryVerifier.__init__,
        ntor_experiment.client_start,
        pir_manifest.verify_snapshot_manifest,
    )
    for function in decorated:
        is_property = isinstance(function, property)
        target = function.fget if is_property else getattr(function, "__func__", function)
        if is_property:
            assert function.fget.__name__ == "public_key_bytes"
        else:
            assert target.__name__ == function.__name__
            assert target.__qualname__ == function.__qualname__
            assert target.__doc__ == function.__doc__
            assert target.__module__ == function.__module__
            assert list(target.__annotations__) == list(function.__annotations__)
        assert inspect.signature(target) == inspect.signature(target.__wrapped__)

    assert str(inspect.signature(directory.create_relay_descriptor)).startswith(
        "(identity_private_key"
    )
    assert "relay_signed_descriptor" in str(inspect.signature(directory.DirectoryAuthority.certify))


def test_broken_install_is_not_reported_as_missing(tmp_path: Path) -> None:
    """A present but unimportable ``cryptography`` must not look like an absent extra."""
    completed = _run_with_broken_cryptography(
        tmp_path,
        """
        from anonlab import directory
        from anonlab._crypto import (
            BrokenCryptoDependency, MissingCryptoDependency, available, installed,
        )

        assert installed() is True, "a present package must be discoverable"
        assert available() is True, "a broken install still lets guarded bodies run"
        # Pure helpers keep working while the install stays broken.
        assert len(directory.relay_identity_digest(b"k" * 32)) == 20
        try:
            directory.DirectoryAuthority.generate()
        except BrokenCryptoDependency as exc:
            assert not isinstance(exc, MissingCryptoDependency)
            assert "installed and failed to import" in str(exc), str(exc)
            assert "cannot open shared object file" in str(exc), str(exc)
            assert isinstance(exc.__cause__, ImportError), repr(exc.__cause__)
            assert "cannot open shared object file" in str(exc.__cause__)
        else:
            raise AssertionError("a broken install produced a working authority")
        print("broken-install-ok")
        """,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "broken-install-ok"


def test_broken_install_is_reported_by_every_guarded_module(tmp_path: Path) -> None:
    completed = _run_with_broken_cryptography(
        tmp_path,
        """
        from anonlab._crypto import BrokenCryptoDependency
        from anonlab import ntor_experiment, onion_protocol, pir_manifest

        attempts = {
            "client_start": lambda: ntor_experiment.client_start(b"\\x03" * 20, b"\\x04" * 32),
            "seal": lambda: onion_protocol.seal(b"k" * 32, b"payload", b"aad"),
            "sign_manifest": lambda: pir_manifest.sign_snapshot_manifest(
                private_key=pir_manifest.Ed25519PrivateKey, snapshot_id="s",
                sequence=1, created_at=1, record_count=1, merkle_root=b"\\x05" * 32,
            ),
        }
        for label, call in attempts.items():
            try:
                call()
            except BrokenCryptoDependency as exc:
                assert exc.__cause__ is not None, label
            else:
                raise AssertionError(f"{label} did not report the broken install")
        print("reported", len(attempts))
        """,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "reported 3"


def test_every_optional_dependency_skip_documents_its_reason() -> None:
    """No test may be skipped without a reason that names the missing extra.

    Skips conditioned on key material must name the ``onion-lab`` extra; other
    environmental skips (for example a missing OpenSSL CLI) only have to carry a
    non-empty, human-readable reason.
    """
    import re

    tests_root = Path(__file__).resolve().parent
    skip_call = re.compile(
        r"(?:skipIf|skipUnless|skipif|skipunless)\((?P<body>[^()]*(?:\([^()]*\)[^()]*)*)\)",
        re.DOTALL,
    )
    crypto_condition = re.compile(
        r"cryptography|Ed25519|X25519|InvalidTag|InvalidSignature|HAS_CRYPTO|CRYPTO_AVAILABLE|needs_crypto"
    )
    reason_literal = re.compile(r"\"[^\"]{10,}\"|'[^']{10,}'")
    importorskip = re.compile(r"importorskip\((?P<body>[^)]*)\)", re.DOTALL)

    inspected = crypto_inspected = 0
    for path in sorted(tests_root.glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        for match in skip_call.finditer(source):
            inspected += 1
            body = match.group("body")
            reason = reason_literal.search(body)
            assert reason, f"{path.name}: skip without a usable reason: {body.strip()[:80]}"
            if crypto_condition.search(body):
                crypto_inspected += 1
                assert "onion-lab" in reason.group(0), f"{path.name}: {reason.group(0)}"
        for match in importorskip.finditer(source):
            inspected += 1
            body = match.group("body")
            assert "reason=" in body, f"{path.name}: importorskip without a reason"
            if "cryptography" in body:
                crypto_inspected += 1
                assert "onion-lab" in body, f"{path.name}: {body}"

    assert inspected >= 15, f"the scanner only found {inspected} skip declarations"
    assert crypto_inspected >= 12, f"the scanner only found {crypto_inspected} crypto skips"


def test_guarded_callable_exceptions_propagate_unchanged() -> None:
    class Boom(ValueError):
        pass

    @requires_crypto("exception passthrough")
    def explode() -> None:
        raise Boom("original failure")

    if not CRYPTO_AVAILABLE:
        pytest.skip("install aegis-anon-lab[onion-lab] to reach the wrapped body")
    with pytest.raises(Boom, match="original failure"):
        explode()


@needs_crypto
def test_blocked_import_matches_real_absence() -> None:
    """The in-process probe and the blocked subprocess agree about availability."""
    assert importlib.util.find_spec("cryptography") is not None
    completed = _run_without_cryptography(
        "from anonlab._crypto import available; print(available())"
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "False"


@needs_crypto
def test_ed25519_signature_round_trip_and_rejection() -> None:
    import dataclasses
    import time

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from anonlab.pir_commitment import AuthenticatedSnapshot
    from anonlab.pir_manifest import (
        ManifestError,
        sign_snapshot_manifest,
        verify_snapshot_manifest,
    )

    key = Ed25519PrivateKey.generate()
    snapshot = AuthenticatedSnapshot.build([b"row-a", b"row-b"])
    manifest = sign_snapshot_manifest(
        private_key=key,
        snapshot_id="snapshot-1",
        sequence=1,
        created_at=int(time.time()),
        record_count=snapshot.record_count,
        merkle_root=snapshot.root,
    )
    verify_snapshot_manifest(manifest, key.public_key(), max_age_seconds=3600)

    flipped = bytes([manifest.signature[0] ^ 1]) + manifest.signature[1:]
    tampered = dataclasses.replace(manifest, signature=flipped)
    with pytest.raises(ManifestError, match="signature verification failed"):
        verify_snapshot_manifest(tampered, key.public_key())


@needs_crypto
def test_missing_and_malformed_keys_are_rejected() -> None:
    import time

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from anonlab.directory import DirectoryVerifier, relay_identity_digest
    from anonlab.pir_commitment import AuthenticatedSnapshot
    from anonlab.pir_manifest import (
        ManifestError,
        sign_snapshot_manifest,
        verify_snapshot_manifest,
    )

    snapshot = AuthenticatedSnapshot.build([b"row-a"])
    key = Ed25519PrivateKey.generate()
    manifest = sign_snapshot_manifest(
        private_key=key, snapshot_id="snapshot-2", sequence=2,
        created_at=int(time.time()), record_count=snapshot.record_count,
        merkle_root=snapshot.root,
    )

    # A missing signing key must fail instead of yielding an unsigned manifest.
    with pytest.raises((AttributeError, TypeError)):
        sign_snapshot_manifest(
            private_key=None, snapshot_id="snapshot-3", sequence=3,
            created_at=int(time.time()), record_count=1, merkle_root=b"\x00" * 32,
        )
    # A missing verification key is reported as a malformed manifest.
    with pytest.raises(ManifestError, match="malformed snapshot manifest"):
        verify_snapshot_manifest(manifest, None)
    # A malformed verification key is also malformed, never silently accepted.
    with pytest.raises(ManifestError, match="malformed snapshot manifest"):
        verify_snapshot_manifest(manifest, b"\x00" * 31)

    with pytest.raises(ValueError, match="trusted authority public key"):
        DirectoryVerifier(None)
    with pytest.raises(ValueError, match="trusted authority public key"):
        DirectoryVerifier(b"\x00" * 31)
    # Pure validation without any key material keeps working.
    assert len(relay_identity_digest(b"\x0b" * 32)) == 20


@needs_crypto
@pytest.mark.parametrize("toggle", ["1", "0", ""])
def test_signed_state_env_toggle_cannot_disable_verification(
    monkeypatch: pytest.MonkeyPatch, toggle: str
) -> None:
    """``AEGIS_SIGNED`` is not a switch in this codebase.

    No module reads it, and these assertions pin that down: setting it to any
    value must neither enable an unsigned fast path nor suppress a bad
    signature. Signature verification therefore fails closed at all times.
    """
    import dataclasses
    import time

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from anonlab import directory, pir_manifest
    from anonlab.pir_commitment import AuthenticatedSnapshot
    from anonlab.pir_manifest import (
        ManifestError,
        sign_snapshot_manifest,
        verify_snapshot_manifest,
    )

    monkeypatch.setenv("AEGIS_SIGNED", toggle)
    # No production module reads this variable, so it cannot gate verification.
    for module in (directory, pir_manifest):
        assert "AEGIS_SIGNED" not in inspect.getsource(module)

    key = Ed25519PrivateKey.generate()
    snapshot = AuthenticatedSnapshot.build([b"row"])
    manifest = sign_snapshot_manifest(
        private_key=key,
        snapshot_id="snapshot-env",
        sequence=1,
        created_at=int(time.time()),
        record_count=snapshot.record_count,
        merkle_root=snapshot.root,
    )
    verify_snapshot_manifest(manifest, key.public_key())
    forged = dataclasses.replace(manifest, signature=b"\x00" * 64)
    with pytest.raises(ManifestError):
        verify_snapshot_manifest(forged, key.public_key())


@needs_crypto
def test_ntor_handshake_round_trip_with_dependency() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from anonlab.ntor_experiment import client_finish, client_start, relay_respond

    identity = b"\x0c" * 20
    relay_private = X25519PrivateKey.generate()
    relay_public = relay_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    state, message = client_start(identity, relay_public)
    reply, relay_keys = relay_respond(message, identity, relay_private)
    assert client_finish(state, reply) == relay_keys


@needs_crypto
def test_benchmark_smoke_with_dependency() -> None:
    import asyncio

    from anonlab.ntor_benchmark import run_ntor_benchmark

    result = asyncio.run(run_ntor_benchmark(rounds=2))
    assert result["config"]["rounds"] == 2
    assert result["results"]["all_key_agreements_verified"] is True


def test_missing_cryptography_error_is_a_runtime_error() -> None:
    """Existing callers that catch RuntimeError keep working."""
    assert issubclass(MissingCryptoDependency, RuntimeError)
    assert issubclass(MissingCryptographyError, Exception)
    with pytest.raises(RuntimeError):
        raise MissingCryptoDependency("a guarded feature")


def test_optional_exception_symbols_are_exception_classes_not_placeholders() -> None:
    """A placeholder bound to an ``except`` target would mask the real error.

    ``except <placeholder>`` raises ``TypeError: catching classes that do not
    inherit from BaseException is not allowed`` while handling the dependency
    error, replacing ``MissingCryptoDependency`` with an unrelated bug.
    """
    completed = _run_without_cryptography(
        """
        from anonlab import directory, onion_relay, pir_manifest, telescoping

        for module, names in (
            (directory, ("InvalidSignature",)),
            (pir_manifest, ("InvalidSignature",)),
            (telescoping, ("InvalidSignature", "InvalidTag")),
            (onion_relay, ("InvalidTag",)),
        ):
            for name in names:
                symbol = getattr(module, name)
                assert isinstance(symbol, type), f"{module.__name__}.{name} is {symbol!r}"
                assert issubclass(symbol, BaseException), f"{module.__name__}.{name} is not an exception"
        print("ok")
        """
    )
    assert completed.returncode == 0, completed.stderr


def test_relay_reports_a_dependency_error_not_a_type_error() -> None:
    """A client frame on a crypto-free relay must surface the dependency error."""
    completed = _run_without_cryptography(
        """
        import asyncio

        from anonlab.onion_relay import _handle

        class Reader:
            def __init__(self):
                self.buffer = (64).to_bytes(4, "big") + bytes(64)

            async def readexactly(self, n):
                if len(self.buffer) < n:
                    raise asyncio.IncompleteReadError(self.buffer, n)
                chunk, self.buffer = self.buffer[:n], self.buffer[n:]
                return chunk

        class Writer:
            def __init__(self):
                self.written = b""
                self.closed = False

            def write(self, data):
                self.written += data

            async def drain(self):
                return None

            def close(self):
                self.closed = True

            async def wait_closed(self):
                return None

        writer = Writer()

        async def drive():
            await _handle(Reader(), writer, "relay-1", b"k" * 32, 2, True)

        try:
            asyncio.run(drive())
        except BaseException as exc:
            assert type(exc).__name__ == "MissingCryptoDependency", type(exc).__name__
            assert writer.written == b"", "relay answered a request it could not authenticate"
            print("ok")
        else:
            raise SystemExit("relay accepted a frame without cryptography")
        """
    )
    assert completed.returncode == 0, completed.stderr
