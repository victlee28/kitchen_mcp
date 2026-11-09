"""Backsplash (ốp đá): default for designs made from a description or a template, 600 mm vs up-to-upper height,
stored in the spec and identical in the 3D geometry and the Three.js scene."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import geometry, intent, threejs_export  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import dump_spec, load_spec  # noqa: E402


def _heights(spec):
    """(3D geometry, Three.js) backsplash heights, rounded, one entry per wall run."""
    scene = geometry.compile_spec(spec)
    g = sorted(round(p.max[1] - p.min[1]) for p in scene.parts if p.type == "wall-tile")
    doc = threejs_export.export(spec, "d", 1)
    t = sorted(round(a["dimensions"]["height"]) for a in doc["accessories"] if a["type"] == "Backsplash_Tile")
    return g, t


def _spec(**kw):
    return intent.from_template(intent.KitchenTemplate(**kw))


class TestBacksplash(unittest.TestCase):
    def test_default_exists_for_template_and_prompt(self):
        for spec in (_spec(), _spec(geometry_edit="L"), intent.from_template(intent.parse_prompt("bếp chữ L 3m x 2.4m")[0])):
            self.assertTrue(spec.common.material.get("wallTile"))
            g, t = _heights(spec)
            self.assertTrue(g and g == t, (g, t))
            self.assertEqual(set(g), {600})
            self.assertEqual(spec.common.backsplashHeight, "standard")

    def test_height_option_is_stored_in_spec(self):
        spec = _spec(backsplashHeight="to-upper")
        self.assertEqual(spec.common.backsplashHeight, "to-upper")
        again = load_spec(json.loads(json.dumps(dump_spec(spec))))
        self.assertEqual(again.common.backsplashHeight, "to-upper")
        with self.assertRaises(Exception):
            _spec(backsplashHeight="whatever")

    def test_standard_stays_600_even_when_uppers_move(self):
        spec = _spec()
        for m in spec.module:
            if m.storey == "upper":
                m.y = 1700
        g, t = _heights(spec)
        self.assertEqual((set(g), set(t)), ({600}, {600}))

    def test_to_upper_follows_lowest_upper_in_3d_and_threejs(self):
        spec = _spec(backsplashHeight="to-upper")
        self.assertEqual(_heights(spec)[0], _heights(spec)[1])
        for m in spec.module:
            if m.storey == "upper":
                m.y = spec.common.countertop + 700
        g, t = _heights(spec)
        self.assertEqual((set(g), set(t)), ({700}, {700}), "3D and Three.js must agree")

    def test_to_upper_without_upper_cabinets_uses_upper_bottom(self):
        spec = _spec(backsplashHeight="to-upper")
        spec.module = [m for m in spec.module if m.storey != "upper"]
        spec.common.upperBottom = spec.common.countertop + 800
        g, t = _heights(spec)
        self.assertEqual((set(g), set(t)), ({800}, {800}))

    def test_threejs_document_stays_valid_and_http_roundtrip(self):
        tmp = Path(tempfile.mkdtemp(prefix="bs-"))
        try:
            svc = KitchenService(tmp / "k.db", tmp / "renders")
            did = svc.create_from_template({"backsplashHeight": "to-upper"})["id"]
            self.assertEqual(svc.get(did)["spec"]["common"]["backsplashHeight"], "to-upper")
            doc = svc.threejs(did, None, None)
            self.assertEqual(threejs_export.integrity(doc), [])
            self.assertTrue(any(a["type"] == "Backsplash_Tile" for a in doc["accessories"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestBacksplashUi(unittest.TestCase):
    def test_form_sends_the_option(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "design-create-panel.js").read_text(encoding="utf-8")
        self.assertIn('id="mBacksplash"', html)
        for value in ("standard", "to-upper"):
            self.assertIn(f'value="{value}"', html)
        self.assertIn("backsplashHeight: $('mBacksplash').value", js)


if __name__ == "__main__":
    unittest.main()
