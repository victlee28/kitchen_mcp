"""Stage 6: kitchen layouts are templates (catalog kinds layout-template and layout-rules) laid out by one solver."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import layout_solver  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402


class TestLayoutTemplates(unittest.TestCase):
    def test_builtin_templates_compile(self):
        self.assertEqual(sorted(layout_solver.templates()), ["I", "L", "U"])
        self.assertEqual(layout_solver.template("I").peninsula_uses, "L")
        with self.assertRaises(InvalidInput):
            layout_solver.template("Z")

    def test_a_bad_formula_names_the_template_and_the_place(self):
        with self.assertRaises(InvalidInput) as e:
            layout_solver._compile("X", {"label": {"vi": "x"}, "steps": [{"do": "upper-run", "wall": "back", "start": "0", "end": "back -"}]})
        self.assertEqual((e.exception.code, e.exception.params["where"]), ("layout-template-formula", "steps[0].end"))

    def test_the_workshop_changes_a_layout(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            s = KitchenService(db_path=tmp / "k.db", render_dir=tmp / "r")
            before = s.get(s.create_from_template({"geometry_edit": "L", "backWallLength": 3000, "rightWallLength": 2400}, "")["id"])["spec"]
            self.assertTrue(any(m["type"] == "corner-shelf" for m in before["module"]))
            row = next(i for i in s.catalog_list("layout-template", "workshop")["items"] if i["id"] == "L")
            steps = [st for st in row["data"]["steps"] if st["do"] != "corner-shelf"]
            s.catalog_put("layout-template", "L", {**row["data"], "steps": steps}, "workshop")
            after = s.get(s.create_from_template({"geometry_edit": "L", "backWallLength": 3000, "rightWallLength": 2400}, "")["id"])["spec"]
            self.assertFalse(any(m["type"] == "corner-shelf" for m in after["module"]))
            self.assertEqual(len(after["module"]), len(before["module"]) - 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_straight_kitchen_with_a_wine_cabinet_at_the_end_needs_no_code(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            s = KitchenService(db_path=tmp / "k.db", render_dir=tmp / "r")
            s.catalog_put("cabinet-type", "base-wine", {"storey": "base", "label": {"vi": "Tủ rượu", "en": "Wine cabinet"}, "like": "base",
                                                        "prompt": "wine rack base cabinet"}, "workshop")
            row = next(i for i in s.catalog_list("layout-template", "user")["items"] if i["id"] == "I")
            data = {**row["data"], "label": {"vi": "Bếp I có tủ rượu cuối dãy"}}
            data["steps"] = [{**st, "extras": [{"type": "base-wine", "width": "450", "at": "end"}]} if st["do"] == "base-run" else st for st in data["steps"]]
            preview = s.layout_template_preview("I-wine", data, "user", {"fridge": True})
            self.assertTrue(all(any(m["type"] == "base-wine" for m in x["modules"]) for x in preview["samples"]))
            s.catalog_put("layout-template", "I-wine", data, "user")
            spec = s.get(s.create_from_template({"geometry_edit": "I-wine", "backWallLength": 3600, "fridge": True}, "")["id"])["spec"]
            mods = {m["type"]: m for m in spec["module"]}
            wine, fridge = mods["base-wine"], mods["tall-fridge"]
            self.assertEqual(wine["name"], "Tủ rượu")
            touching = {wine["fromCorner"] + wine["width"], wine["fromCorner"] - fridge["width"]}
            self.assertIn(fridge["fromCorner"], touching)        # the wine cabinet ends the run next to the fridge, which stays outermost
            lo, hi = fridge["fromCorner"], fridge["fromCorner"] + fridge["width"]
            uppers = [m for m in spec["module"] if m["type"].startswith("upper")]
            self.assertTrue(all(m["fromCorner"] + m["width"] <= lo + 0.5 or m["fromCorner"] >= hi - 0.5 for m in uppers))   # none in front of the fridge
            with self.assertRaises(InvalidInput):
                s.create_from_template({"geometry_edit": "nope"}, "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
