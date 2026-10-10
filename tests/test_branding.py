from __future__ import annotations

import contextlib
import io
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from anonlab import cli, directory, ntor_experiment, telescoping

ROOT = Path(__file__).resolve().parents[1]


class AegisBrandingTests(unittest.TestCase):
    def test_cli_uses_aegis_as_canonical_program_name(self) -> None:
        self.assertEqual(cli.build_parser().prog, "aegis")

    def test_simulator_output_uses_current_brand(self) -> None:
        stdout = io.StringIO()
        with patch("sys.argv", ["aegis", "--duration", "1", "--request-rate", "1.4", "--seed", "7", "--bin-ms", "100"]):
            with contextlib.redirect_stdout(stdout):
                cli.main()
        import json
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["metadata"]["simulator"], "AEGIS Anonymous Encrypted Garlic-routed Internet Shield Research Lab")
        self.assertFalse(payload["metadata"]["is_live_network_test"])
        self.assertFalse(payload["metadata"]["is_security_proof"])

    def test_distribution_and_compatibility_scripts_are_declared(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["name"], "aegis-anon-lab")
        scripts = config["project"]["scripts"]
        self.assertEqual(scripts["aegis"], "anonlab.cli:main")
        self.assertEqual(scripts["aegis-window-update-timer-bench"], "anonlab.window_update_timer_benchmark:main")
        self.assertEqual(scripts["rea-anon-lab"], "anonlab.cli:main")
        self.assertEqual(scripts["rea-anon-window-update-timer-bench"], "anonlab.window_update_timer_benchmark:main")


    def test_every_legacy_console_script_has_a_matching_aegis_alias(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = config["project"]["scripts"]
        legacy_entries = {name: target for name, target in scripts.items() if name.startswith("rea-anon-")}
        self.assertGreaterEqual(len(legacy_entries), 18)
        for legacy_name, target in legacy_entries.items():
            suffix = legacy_name[len("rea-anon-"):]
            aegis_name = "aegis" if legacy_name == "rea-anon-lab" else f"aegis-{suffix}"
            self.assertEqual(scripts.get(aegis_name), target, f"missing/mismatched alias for {legacy_name}")


    def test_v025_experimental_components_are_declared(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["project"]["version"], "0.26.0")
        scripts = config["project"]["scripts"]
        self.assertEqual(scripts["aegis-route-select"], "anonlab.route_selection:main")
        self.assertEqual(scripts["aegis-pir-demo"], "anonlab.pir:main")
        self.assertEqual(scripts["aegis-share-demo"], "anonlab.secret_sharing:main")
        self.assertEqual(scripts["aegis-pir-rpc-demo"], "anonlab.pir_rpc_demo:main")
        self.assertEqual(scripts["aegis-pir-rpc-tls-demo"], "anonlab.pir_rpc_tls_demo:main")

    def test_v1_protocol_domain_separation_is_preserved(self) -> None:
        # Branding must not silently change key derivation, AAD or relay identities.
        self.assertEqual(telescoping.LINK_CLIENT_DOMAIN, b"MALEBOLGE/link-auth/client/v1\x00")
        self.assertEqual(directory.PROTOCOL, "malebolge-lab-ntor-v1")
        self.assertIn(b"MALEBOLGE_AEAD_v1", ntor_experiment._MALEBOLGE_KDF_INFO)

    def test_brand_transition_documents_garlic_routing_status(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        transition = (ROOT / "docs" / "BRAND_TRANSITION.md").read_text(encoding="utf-8")
        self.assertIn("Anonymous Encrypted Garlic-routed Internet Shield", readme)
        self.assertIn("does **not** yet implement garlic routing", transition)
        self.assertIn("domain-separation strings", transition)


if __name__ == "__main__":
    unittest.main()
