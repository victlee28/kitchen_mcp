"""Stage 5: cabinet types are formulas (catalog kind ``cabinet-type``), compiled once per catalog and run by geometry."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import builtin, cabinet_types, geometry  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.spec import KitchenSpec, MODULE_TYPES  # noqa: E402


def _fixture() -> KitchenSpec:
    return KitchenSpec.model_validate(json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8")))


class TestCabinetTypes(unittest.TestCase):
    def test_every_module_type_has_a_compiled_type(self):
        table = cabinet_types.table()
        self.assertEqual(sorted(table), sorted(MODULE_TYPES))
        self.assertEqual(table["upper-loft"].storey, "loft")
        self.assertEqual(table["base-sink"].steps, table["base"].steps)          # "like": the same steps

    def test_a_bad_formula_names_the_type_the_step_and_the_position(self):
        raw = {"t": {"storey": "base", "parts": [{"part": "carcass", "s": ["0", "width +"], "d": ["0", "depth"], "y": ["0", "top"]}]}}
        with self.assertRaises(InvalidInput) as e:
            cabinet_types._compile("t", raw["t"], raw)
        self.assertEqual(e.exception.code, "cabinet-type-formula")
        self.assertEqual(e.exception.params["where"], "parts[0].s[1]")
        self.assertEqual(e.exception.params["at"], 7)
        with self.assertRaises(InvalidInput) as e:
            cabinet_types._compile("t", {"storey": "base", "parts": [{"part": "x", "s": ["0", "nope"], "d": ["0", "1"], "y": ["0", "1"]}]}, raw)
        self.assertEqual(e.exception.params["detail"], "expr-unknown-name")
        loop = {"a": {"like": "b"}, "b": {"like": "a"}}
        with self.assertRaises(InvalidInput) as e:
            cabinet_types._compile("a", loop["a"], loop)
        self.assertEqual(e.exception.code, "cabinet-type-like")

    def test_the_workshop_changes_a_type(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            s = KitchenService(db_path=tmp / "k.db", render_dir=tmp / "r")
            spec = _fixture()
            before = [p for p in geometry.compile_spec(spec, s.catalog()).parts if p.module == "TT1"]
            row = next(i for i in s.catalog_list("cabinet-type", "workshop")["items"] if i["id"] == "upper")
            parts = [*row["data"]["parts"], {"part": "shelf", "s": ["fs0", "fs1"], "d": ["0", "depth - doorThickness"], "y": ["y + height / 2", "y + height / 2 + doorThickness"]}]
            s.catalog_put("cabinet-type", "upper", {**row["data"], "parts": parts}, "workshop")
            after = [p for p in geometry.compile_spec(spec, s.catalog()).parts if p.module == "TT1"]
            self.assertEqual(len(after), len(before) + 1)
            self.assertEqual(sum(p.type == "shelf" for p in after), 1)
            self.assertEqual(len(geometry.compile_spec(spec, builtin.CATALOG).parts), len(geometry.compile_spec(spec).parts))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repeat_and_let(self):
        spec = _fixture()
        m = next(m for m in spec.module if m.type == "upper")
        m.type, m.doors, m.shelfCount = "upper-open", [], 4
        shelves = [p for p in geometry.compile_spec(spec).parts if p.module == m.id and p.type == "shelf"]
        self.assertEqual(len(shelves), 5)


if __name__ == "__main__":
    unittest.main()
