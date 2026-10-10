#!/usr/bin/env python3
"""Apply a narrowly scoped safety overlay to the recovered AEGIS PIR research snapshot.

The archived source is verified before this overlay is applied. The overlay does not
implement verifiable PIR; it blocks remote retrieval by default until the caller
explicitly opts into unverified research behavior.
"""
from __future__ import annotations

from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise SystemExit(f"Could not apply PIR hardening overlay: expected {label} not found")
    return source.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_remote_pir_guard.py RECOVERED_SOURCE_ROOT")
    root = Path(sys.argv[1]).resolve()
    pir_path = root / "src" / "anonlab" / "pir_rpc.py"
    source = pir_path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "    expected_snapshot_sha256: str | None = None,\n) -> PirRpcTransfer:",
        "    expected_snapshot_sha256: str | None = None,\n"
        "    allow_unverified_remote: bool = False,\n) -> PirRpcTransfer:",
        "two-server function signature",
    )
    source = replace_once(
        source,
        "    is retained only for local research compatibility.",
        "    is retained only for local research compatibility. TLS does not prove correct\n"
        "    PIR computation. Remote retrieval is fail-closed unless a caller explicitly\n"
        "    opts into unverified research mode; opting in does not make it secure.",
        "two-server security docstring",
    )
    source = replace_once(
        source,
        "    if not isinstance(item_count, int) or isinstance(item_count, bool) or not 1 <= item_count <= MAX_RECORDS:",
        "    if not isinstance(allow_unverified_remote, bool):\n"
        "        raise ValueError(\"allow_unverified_remote must be a bool\")\n"
        "    if not isinstance(item_count, int) or isinstance(item_count, bool) or not 1 <= item_count <= MAX_RECORDS:",
        "two-server input validation",
    )
    source = replace_once(
        source,
        "    a, b = endpoints\n    if a.server_id == b.server_id:",
        "    a, b = endpoints\n"
        "    if any(not ipaddress.ip_address(endpoint.host).is_loopback for endpoint in endpoints) and not allow_unverified_remote:\n"
        "        raise PirRpcProtocolError(\n"
        "            \"remote PIR computation is not cryptographically verifiable; \"\n"
        "            \"remote research mode requires allow_unverified_remote=True and must not be used for sensitive data\"\n"
        "        )\n"
        "    if a.server_id == b.server_id:",
        "remote endpoint guard",
    )
    source = replace_once(
        source,
        "    expected_snapshot_sha256: str | None = None,\n) -> RedundantPirRpcTransfer:",
        "    expected_snapshot_sha256: str | None = None,\n"
        "    allow_unverified_remote: bool = False,\n) -> RedundantPirRpcTransfer:",
        "four-server function signature",
    )
    source = replace_once(
        source,
        "            expected_snapshot_sha256=expected_snapshot_sha256,\n"
        "        ),\n"
        "        retrieve_two_server_pir_rpc(",
        "            expected_snapshot_sha256=expected_snapshot_sha256,\n"
        "            allow_unverified_remote=allow_unverified_remote,\n"
        "        ),\n"
        "        retrieve_two_server_pir_rpc(",
        "first four-server delegation",
    )
    source = replace_once(
        source,
        "            expected_snapshot_sha256=expected_snapshot_sha256,\n"
        "        ),\n"
        "    )\n"
        "    if not hmac.compare_digest(first.snapshot_sha256, second.snapshot_sha256):",
        "            expected_snapshot_sha256=expected_snapshot_sha256,\n"
        "            allow_unverified_remote=allow_unverified_remote,\n"
        "        ),\n"
        "    )\n"
        "    if not hmac.compare_digest(first.snapshot_sha256, second.snapshot_sha256):",
        "second four-server delegation",
    )
    pir_path.write_text(source, encoding="utf-8")

    test_path = root / "tests" / "test_pir_remote_fail_closed.py"
    test_lines = [
        "from __future__ import annotations",
        "",
        "import ssl",
        "import unittest",
        "",
        "from anonlab.pir_rpc import PirRpcEndpoint, PirRpcProtocolError, retrieve_two_server_pir_rpc, retrieve_four_server_pir_rpc_checked",
        "",
        "",
        "class RemotePirFailClosedTests(unittest.IsolatedAsyncioTestCase):",
        "    def setUp(self):",
        "        context = ssl.create_default_context()",
        "        context.minimum_version = ssl.TLSVersion.TLSv1_2",
        "        self.endpoints = tuple(",
        "            PirRpcEndpoint(f\"remote-{i}\", host, 443, ssl_context=context, server_hostname=\"pir.example.invalid\")",
        "            for i, host in enumerate((\"192.0.2.1\", \"192.0.2.2\", \"192.0.2.3\", \"192.0.2.4\"))",
        "        )",
        "",
        "    async def test_two_server_remote_pir_is_rejected_by_default_before_network_io(self):",
        "        with self.assertRaisesRegex(PirRpcProtocolError, \"not cryptographically verifiable\"):",
        "            await retrieve_two_server_pir_rpc(self.endpoints[:2], 8, 3, record_bytes=16)",
        "",
        "    async def test_four_server_remote_pir_is_rejected_by_default_before_network_io(self):",
        "        with self.assertRaisesRegex(PirRpcProtocolError, \"not cryptographically verifiable\"):",
        "            await retrieve_four_server_pir_rpc_checked(self.endpoints, 8, 3, record_bytes=16)",
        "",
        "    async def test_remote_research_mode_must_be_explicitly_boolean(self):",
        "        with self.assertRaisesRegex(ValueError, \"must be a bool\"):",
        "            await retrieve_two_server_pir_rpc(self.endpoints[:2], 8, 3, record_bytes=16, allow_unverified_remote=1)",
        "",
        "",
        "if __name__ == \"__main__\":",
        "    unittest.main()",
        "",
    ]
    test_path.write_text("\n".join(test_lines), encoding="utf-8")
    print("Applied remote PIR fail-closed guard and 3 regression tests.")


if __name__ == "__main__":
    main()
