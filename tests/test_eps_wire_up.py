"""Wire-up invariant: every ``data-hk`` / ``data-derived`` reference in
the EPS preview HTML must resolve against the 48-field manifest at
``docs/eps-port/eps_fields.json``.

Run via ``verify_eps_port.sh --python`` (or directly). Fails the build
if the preview references a field name that is not in the manifest, or
a derived name that is not in the manifest's ``derived`` list.

This mirrors ``verify_eps_port.sh --wire-up`` (same check, invoked from
a different entry point) so CI can't forget either path.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestEpsWireUp(unittest.TestCase):
    def setUp(self) -> None:
        self.preview = (ROOT / "docs" / "eps-preview.html").read_text()
        self.manifest = json.loads(
            (ROOT / "docs" / "eps-port" / "eps_fields.json").read_text()
        )

    def test_data_hk_references_resolve(self) -> None:
        legal = {f["name"] for f in self.manifest["fields"]}
        hk_refs = set(re.findall(r'data-hk="([A-Z0-9_]+)"', self.preview))
        hk_refs.discard("FIELDNAME")  # preview template placeholder
        bad = hk_refs - legal
        self.assertFalse(bad, f"data-hk values not in manifest: {sorted(bad)}")
        self.assertGreater(len(hk_refs), 0, "preview has no data-hk references")

    def test_data_derived_references_resolve(self) -> None:
        derived = {d["name"] for d in self.manifest["derived"]}
        derived_refs = set(re.findall(r'data-derived="([A-Z0-9_]+)"', self.preview))
        bad = derived_refs - derived
        self.assertFalse(bad, f"data-derived values not in manifest: {sorted(bad)}")
        self.assertGreater(len(derived_refs), 0, "preview has no data-derived references")

    def test_manifest_has_48_fields(self) -> None:
        self.assertEqual(len(self.manifest["fields"]), 48)
        self.assertEqual(self.manifest["wire_bytes"], 96)

    def test_manifest_field_names_match_decoder(self) -> None:
        sys.path.insert(0, str(ROOT))
        from mav_gss_lib.missions.maveric.telemetry.semantics.eps import _EPS_HK_NAMES
        manifest_names = [f["name"] for f in self.manifest["fields"]]
        self.assertEqual(
            manifest_names, list(_EPS_HK_NAMES),
            "fields.json order must match _EPS_HK_NAMES wire order",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
