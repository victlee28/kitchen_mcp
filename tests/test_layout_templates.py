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


if __name__ == "__main__":
    unittest.main()
