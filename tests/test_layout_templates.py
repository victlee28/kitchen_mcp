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


class TestSaveSystemAsTemplate(unittest.TestCase):
    """A cabinet system of a design saved as a layout template, and new kitchens laid out from it."""

    def setUp(self):
        from kitchen.service import KitchenService
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make(self, **request):
        from kitchen.intent import KitchenTemplate
        return self.svc.create_from_template(KitchenTemplate.model_validate(request), "test")["id"]

    def _system(self, did):
        return sorted({v["system"] for k, v in self.svc.get(did)["systems"].items() if k.startswith(("TD", "TC", "TT", "TN", "KG"))})[0]

    def _cabinets(self, did, storeys=("base", "tall", "upper", "corner")):
        spec = self.svc.get(did)["spec"]
        return sorted((m.get("run") or m["wall"], m["type"], round(m["fromCorner"]), round(m["width"])) for m in spec["module"]
                      if m["type"].split("-")[0] in storeys and (m["wall"] != "island" or m.get("run")))

    def _by_run(self, did):
        """The cabinets of each run, the runs in no particular order (a rebuilt kitchen may number them otherwise)."""
        runs: dict[str, list[tuple]] = {}
        for run, kind, s, w in self._cabinets(did):
            runs.setdefault(run, []).append((kind, s, w))
        return sorted(sorted(v) for v in runs.values())

    def test_an_L_and_a_U_come_back_the_same(self):
        for request in ({"geometry_edit": "L", "backWallLength": 3200, "rightWallLength": 2400, "fridge": True, "loft": True},
                        {"geometry_edit": "U", "backWallLength": 3000, "rightWallLength": 2400, "leftWallLength": 2000, "fridge": True}):
            did = self._make(**request)
            saved = self.svc.layout_template_from_design(did, "user", label="Mẫu " + request["geometry_edit"], system=self._system(did))
            self.assertEqual(saved["skipped"], [])
            self.assertEqual(saved["scope"], "user:default")
            again = self._make(**{**request, "geometry_edit": saved["id"]})
            self.assertEqual(self._by_run(again), self._by_run(did), request["geometry_edit"])

    def test_a_longer_wall_stretches_the_plain_cabinets_only(self):
        did = self._make(geometry_edit="I", backWallLength=3200, fridge=True)
        saved = self.svc.layout_template_from_design(did, "user", label="Thẳng có tủ lạnh")
        before = [(t, w) for _, t, _, w in self._cabinets(did, ("base", "tall"))]
        after = [(t, w) for _, t, _, w in self._cabinets(self._make(geometry_edit=saved["id"], backWallLength=3900), ("base", "tall"))]
        self.assertEqual(sum(w for _, w in after), sum(w for _, w in before) + 700)
        fixed = lambda rows: sorted(r for r in rows if r[0] != "base")
        self.assertEqual(fixed(after), fixed(before))                      # the fridge, the sink, the cooktop keep their widths
        self.assertTrue(all(w % 10 == 0 for _, w in after))

    def test_a_saved_run_is_laid_along_another_system_by_its_name(self):
        did = self._make(geometry_edit="I", backWallLength=3200, fridge=True)
        saved = self.svc.layout_template_from_design(did, "user", label="Bếp nhà tôi")
        other = self._make(geometry_edit="I", backWallLength=4000)
        plan = self.svc.template(other, {"kind": "replace-system", "system": self._system(other), "prompt": "thay hệ tủ theo mẫu bếp nhà tôi"})
        added = sorted((o["module"]["fromCorner"], o["module"]["type"]) for o in plan["operation"]["ops"] if o.get("op") == "add")
        kinds = [t for _, t in added if t in ("tall-fridge", "base-sink", "base-cooktop")]
        mine = [t for _, t, _, _ in sorted(self._cabinets(did, ("base", "tall")), key=lambda r: r[2]) if t in ("tall-fridge", "base-sink", "base-cooktop")]
        self.assertEqual(kinds, mine)
        self.assertTrue(any("Bếp nhà tôi".lower() in str(line).lower() for line in plan["summary"]), plan["summary"])
        self.assertEqual(saved["id"], "bep-nha-toi")

    def test_a_design_with_two_systems_asks_which(self):
        did = self._make(geometry_edit="I", backWallLength=3600, island=True)
        with self.assertRaises(InvalidInput) as e:
            self.svc.layout_template_from_design(did, "user", label="x")
        self.assertEqual(e.exception.code, "pick-system")

    def test_the_same_name_twice_gets_a_new_id(self):
        did = self._make(geometry_edit="I", backWallLength=3200)
        first = self.svc.layout_template_from_design(did, "user", label="Bếp A")
        second = self.svc.layout_template_from_design(did, "user", label="Bếp A")
        self.assertEqual((first["id"], second["id"]), ("bep-a", "bep-a-2"))

    def test_a_draft_is_not_saved(self):
        did = self._make(geometry_edit="I", backWallLength=3200)
        draft = self.svc.layout_template_from_design(did, "user", label="Nháp", save=False)
        self.assertNotIn("version", draft)
        self.assertNotIn("nhap", {it.id for it in self.svc.catalog().all("layout-template")})

