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


THREE_DRAWERS = {"storey": "base", "label": {"vi": "Tủ dưới 3 ngăn kéo", "en": "Three-drawer base cabinet"},
                 "let": {"body": "max(y, plinthHeight) if y == 0 else y", "h": "(top - body) / 3"},
                 "parts": [{"when": "y == 0", "part": "plinth", "s": ["fs0", "fs1"], "d": ["0", "depth - doorThickness - 50"], "y": ["0", "plinthHeight"]},
                           {"part": "carcass", "s": ["fs0", "fs1"], "d": ["0", "depth - doorThickness"], "y": ["body", "top"]},
                           {"repeat": "3", "as": "i", "parts": [{"fronts": "drawer", "s": ["fs0", "fs1"], "y": ["body + i * h", "body + (i + 1) * h"]}]}]}


class TestWorkshopTypes(unittest.TestCase):
    """5.7: the workshop adds a type; a design uses it; each revision keeps the types it was built with."""

    def setUp(self):
        from kitchen.service import KitchenService
        self.tmp = Path(tempfile.mkdtemp())
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _drawers(self, scene_json):
        return [p for p in scene_json["parts"] if p["type"] == "drawer" and p["module"] == "TD9"]

    def test_add_use_and_keep(self):
        s = self.s
        s.catalog_put("cabinet-type", "base-3-drawers", THREE_DRAWERS, "workshop")
        design = s.create_from_spec(json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8")))["id"]
        first = s.get(design)["spec"]["module"][0]["id"]
        op = {"op": "add", "module": {"id": "TD9", "type": "base-3-drawers", "width": 600}, "afterModule": first}
        rev = s.apply(design, op, s.propose(design, op)["baseRev"], s.propose(design, op)["opHash"])["rev"]
        self.assertEqual(len(self._drawers(s.scene(design, rev))), 3)
        changed = {**THREE_DRAWERS, "parts": [*THREE_DRAWERS["parts"][:2], {**THREE_DRAWERS["parts"][2], "repeat": "2"}]}
        s.catalog_put("cabinet-type", "base-3-drawers", changed, "workshop")
        self.assertEqual(len(self._drawers(s.scene(design, rev))), 3, "the revision keeps the type it was saved with")
        with self.assertRaises(InvalidInput):
            s.apply(design, {"op": "add", "module": {"type": "nope-type", "width": 600}, "afterModule": first}, rev, None)

    def test_bad_types_are_refused_on_save(self):
        with self.assertRaises(InvalidInput) as e:
            self.s.catalog_put("cabinet-type", "base-bad", {**THREE_DRAWERS, "let": {"h": "top -"}}, "workshop")
        self.assertEqual(e.exception.code, "cabinet-type-formula")
        with self.assertRaises(InvalidInput) as e:
            self.s.catalog_put("cabinet-type", "upper-x", THREE_DRAWERS, "workshop")      # a base type whose id says upper
        self.assertEqual(e.exception.code, "cabinet-type-id")

    def test_preview_builds_samples_and_says_what_looks_wrong(self):
        r = self.s.cabinet_type_preview("base-3-drawers", THREE_DRAWERS, "workshop")
        self.assertEqual([x["width"] for x in r["samples"]], [400.0, 600.0, 900.0])
        self.assertTrue(all(not x["problems"] for x in r["samples"]))
        self.assertEqual(sum(p["type"] == "drawer" for p in r["samples"][1]["parts"]), 3)
        bad = {**THREE_DRAWERS, "parts": [{"part": "carcass", "s": ["fs0", "fs1 + 50"], "d": ["0", "depth"], "y": ["body", "top"]},
                                          {"part": "shelf", "s": ["fs0", "fs0"], "d": ["0", "depth"], "y": ["body", "top"]}]}
        codes = [p["rule"] for p in self.s.cabinet_type_preview("base-bad", bad, "workshop")["samples"][0]["problems"]]
        self.assertEqual(codes, ["cabinet-box-outside", "cabinet-box-empty", "cabinet-fronts-short"])
        nothing = {**THREE_DRAWERS, "parts": [{"fronts": "door", "s": ["fs0", "fs1"], "y": ["body", "top"]}]}
        self.assertIn("cabinet-no-carcass", [p["rule"] for p in self.s.cabinet_type_preview("base-x", nothing, "workshop")["samples"][0]["problems"]])
        corner = self.s.cabinet_type_preview("corner-shelf", {"storey": "corner", "label": {"vi": "x"}, "builder": "corner-shelf", "frontless": True}, "workshop")
        self.assertTrue(corner["samples"][0]["parts"])
        with self.assertRaises(InvalidInput):
            self.s.cabinet_type_preview("base-x", {**THREE_DRAWERS, "let": {"h": "top -"}}, "workshop")


if __name__ == "__main__":
    unittest.main()


class TestCatalogUpdates(unittest.TestCase):
    """Stage 7: a design says what changed in the catalog since it was saved, and takes the new items only through a previewed change."""

    def test_updates_and_refresh(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            s = KitchenService(db_path=tmp / "k.db", render_dir=tmp / "r")
            design = s.create_from_spec(_fixture().model_dump(mode="json"))["id"]
            self.assertEqual(s.catalog_updates(design)["updates"], [])
            row = next(i for i in s.catalog_list("cabinet-type", "workshop")["items"] if i["id"] == "upper")
            extra = {"part": "shelf", "s": ["fs0", "fs1"], "d": ["0", "depth - doorThickness"], "y": ["y + height / 2", "y + height / 2 + doorThickness"]}
            s.catalog_put("cabinet-type", "upper", {**row["data"], "parts": [*row["data"]["parts"], extra]}, "workshop")
            u = s.catalog_updates(design)
            self.assertIn({"kind": "cabinet-type", "id": "upper", "change": "changed"}, u["updates"])
            self.assertTrue(u["geometryChanges"])
            before = len(s.scene(design)["parts"])
            p = s.propose(design, u["operation"])
            self.assertTrue(p["applicable"])
            s.apply(design, u["operation"], p["baseRev"], expect=p["opHash"])
            self.assertEqual(s.catalog_updates(design)["updates"], [])
            self.assertGreater(len(s.scene(design)["parts"]), before)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCatalogListing(unittest.TestCase):
    def test_an_overridden_item_carries_its_builtin_data(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            s = KitchenService(db_path=tmp / "k.db", render_dir=tmp / "r")
            row = s.catalog_list("style", "workshop")["items"][0]
            self.assertNotIn("builtinData", row)
            s.catalog_put("style", row["id"], {**row["data"], "front": "Xám"}, "workshop")
            again = next(i for i in s.catalog_list("style", "workshop")["items"] if i["id"] == row["id"])
            self.assertEqual(again["builtinData"], row["data"])
            self.assertEqual(again["data"]["front"], "Xám")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCatalogBundle(unittest.TestCase):
    def test_the_whole_package_moves_to_another_machine(self):
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            s1 = KitchenService(db_path=a / "k.db", render_dir=a / "r")
            s1.catalog_put("cabinet-type", "base-wine", {"storey": "base", "label": {"vi": "Tủ rượu"}, "like": "base"}, "workshop")
            style = s1.catalog_list("style", "user")["items"][0]
            s1.catalog_put("style", style["id"], {**style["data"], "front": "Xám"}, "user")
            bundle = s1.catalog_export("user", everything=True)
            self.assertEqual(sorted(bundle["layers"]), ["user:default", "workshop"])
            s2 = KitchenService(db_path=b / "k.db", render_dir=b / "r")
            with self.assertRaises(InvalidInput):
                s2.catalog_import(bundle, "user")              # the workshop's layer needs the workshop role
            self.assertEqual(s2.catalog_import(bundle, "workshop")["imported"], 2)
            self.assertIsNotNone(s2.catalog().find("cabinet-type", "base-wine"))
            self.assertEqual(s2.catalog().data("style", style["id"])["front"], "Xám")
        finally:
            shutil.rmtree(a, ignore_errors=True)
            shutil.rmtree(b, ignore_errors=True)


class TestIdentity(unittest.TestCase):
    def test_providers(self):
        from kitchen import identity
        self.assertEqual(identity.HeaderRole().identify({"X-Role": " Workshop "}).role, "workshop")
        self.assertEqual(identity.HeaderRole().identify({}).role, "user")
        self.assertEqual(identity.provider("user").identify({"X-Role": "workshop"}).role, "user")
        with self.assertRaises(InvalidInput):
            identity.FixedRole("boss")
        from kitchen.config import Config
        self.assertEqual(Config.from_env({"KITCHEN_FIXED_ROLE": "User"}).fixed_role, "user")
