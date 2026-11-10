"""Appliance models (plan claude/ke-hoach-thay-mau-thiet-bi.md): reading old designs, fitting another model, the operation, the 3D export and
what the image AI is told about each appliance."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import appliance_models as am, edit, geometry, threejs_export  # noqa: E402
from kitchen.appliance_catalog import MODELS  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="appl-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_prompt("bếp chữ I dài 3m có tủ lạnh")["id"]
        self.spec, self.rev = self.svc.store.get(self.did)
        self.app = {a.type: a for a in self.spec.appliances}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCatalogue(unittest.TestCase):
    def test_every_type_has_one_default_and_complete_models(self):
        for t in am.TYPES:
            self.assertEqual(sum(1 for m in MODELS if m["type"] == t and m.get("default")), 1, t)
        for m in MODELS:
            for key in ("id", "type", "name", "size", "mount", "box", "visual", "prompt"):
                self.assertIn(key, m, m["id"])
            if m["type"] in ("sink", "cooktop"):
                self.assertIn("cutout", m, m["id"])


class TestOldDesigns(Base):
    def test_a_model_less_appliance_is_read_from_its_name_and_keeps_its_size(self):
        hob = self.app["cooktop"]
        self.assertIsNone(hob.model)
        self.assertEqual(am.model_id(hob), "hob-ind-2z-73")
        self.assertEqual(am.model_id(hob.model_copy(update={"name": "Bếp gas"})), "hob-gas-2b-75")
        self.assertEqual(am.size_of(self.app["fridge"]), {"w": 600.0, "h": 1600.0, "d": 620.0})


class TestReplace(Base):
    def test_candidates_follow_the_sentence_and_say_what_does_not_fit(self):
        got = {c["id"]: c["status"] for c in am.candidates(self.spec, self.app["cooktop"], "đổi sang bếp gas")}
        self.assertEqual(set(got), {"hob-mix-2z-73", "hob-gas-2b-75", "hob-gas-3b-86"})
        fr = {c["id"]: c["status"] for c in am.candidates(self.spec, self.app["fridge"])}
        self.assertEqual((fr["fridge-1d-60"], fr["fridge-2d-60-tall"], fr["fridge-sbs-91"], fr["fridge-int-56"]), ("ok", "bad", "bad", "later"))
        self.assertEqual([c["id"] for c in am.candidates(self.spec, self.app["faucet"], "vòi rút dây")], ["faucet-pullout"])

    def test_update_appliance_keeps_id_and_place_and_the_3d_box_follows(self):
        hob = self.app["cooktop"]
        after = edit.apply_op(self.spec, {"op": "update-appliance", "id": hob.id, "model": "hob-gas-2b-75"})
        new = next(a for a in after.appliances if a.id == hob.id)
        self.assertEqual((new.module, new.center, new.wall), (hob.module, hob.center, hob.wall))
        self.assertEqual((new.model, new.energy, new.cutout, new.dimensions), ("hob-gas-2b-75", "gas", {"w": 650.0, "d": 350.0}, "750 × 420"))
        part = next(p for p in geometry.compile_spec(after).parts if p.module == hob.id)
        self.assertEqual((part.max[0] - part.min[0], part.max[2] - part.min[2]), (750.0, 420.0))
        with self.assertRaises(InvalidInput):
            edit.apply_op(self.spec, {"op": "update-appliance", "id": hob.id, "model": "sink-single-60"})

    def test_template_lists_models_then_previews_one(self):
        hob = self.app["cooktop"]
        r = self.svc.template(self.did, {"kind": "replace-appliance", "id": hob.id, "prompt": "bếp gas"})
        self.assertEqual(r["status"], "choose-model")
        r = self.svc.template(self.did, {"kind": "replace-appliance", "id": hob.id, "model": "hob-ind-4z-60"})
        self.assertEqual((r["status"], r["fit"]), ("ok", "ok"))
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(r["aiFacts"]["model"], "hob-ind-4z-60")
        r = self.svc.template(self.did, {"kind": "replace-appliance", "id": hob.id, "model": "hob-gas-2b-75"})     # 650 hole in a 600 cabinet
        self.assertEqual(r["fit"], "bad")
        self.assertTrue(any(s.startswith("Does not fit") for s in r["summary"]))
        self.assertTrue(any("gas supply" in s for s in r["summary"]))
        self.assertEqual(r["aiFacts"]["energy"], "gas")
        self.assertEqual(self.svc.store.get(self.did)[1], self.rev, "a preview: nothing saved")
        with self.assertRaises(InvalidInput):
            self.svc.template(self.did, {"kind": "replace-appliance", "id": self.app["fridge"].id, "model": "fridge-int-56"})

    def test_a_model_too_wide_can_widen_its_cabinet(self):
        sink = self.app["sink"]
        host = am.host(self.spec, sink)
        r = self.svc.template(self.did, {"kind": "replace-appliance", "id": sink.id, "model": "sink-double-100", "resizeHost": True})
        self.assertEqual(r["fit"], "bad")
        after = edit.apply_op(self.spec, r["operation"])
        self.assertEqual(next(m for m in after.module if m.id == host.id).width, 1010.0)     # hole 970 + two 18 mm sides, 10 mm steps


class TestExport(Base):
    def test_types_and_cut_outs_come_from_the_model(self):
        hob = self.app["cooktop"]
        after = edit.apply_op(self.spec, {"op": "update-appliance", "id": hob.id, "model": "hob-gas-2b-75"})
        doc = threejs_export.export(after)
        a = next(x for x in doc["appliances"] if x["sourceRef"] == hob.id)
        self.assertEqual((a["type"], a["energy"], a["model"], a["rendering"]), ("Cooktop_Gas", "gas", "hob-gas-2b-75", "box-placeholder"))
        cut = next(c for acc in doc["accessories"] if acc["type"] == "Countertop" for c in acc.get("cutouts", []) if c["forId"] == f"APP-{hob.id}")
        self.assertEqual((cut["dimensions"]["width"], cut["dimensions"]["depth"], cut["estimated"]), (650.0, 350.0, False))
        import jsonschema
        v = jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8")))
        self.assertEqual([e.message for e in v.iter_errors(doc)][:2], [])    # 1.5.0 (v1.0.0 has no runs)
        self.assertEqual(threejs_export.integrity(doc), [])


class TestAiFacts(Base):
    def test_a_box_appliance_is_described_in_full(self):
        f = am.ai_facts(self.spec, self.app["cooktop"])
        self.assertEqual(f["rendering"], "box-placeholder")
        for key in ("visual", "size_mm", "mount", "energy", "placeholderNote", "cutout_mm", "prompt"):
            self.assertIn(key, f)
        self.assertIn("zones", f["notShownInInputImage"])
        g = am.ai_facts(self.spec, self.app["cooktop"], "model-3d")
        self.assertNotIn("placeholderNote", g)
        self.assertEqual(g["notShownInInputImage"], ["energy", "size", "mount"])

    def test_the_ai_request_lists_the_appliances(self):
        from kitchen import ai_export
        res = ai_export.build(self.svc, self.did, views=["perspective"])
        req = json.loads(Path(res["file"]).read_text(encoding="utf-8"))
        self.assertEqual({a["id"] for a in req["appliances"]}, {a.id for a in self.spec.appliances})
        view = req["views"][0]
        self.assertTrue(view["appliances"])
        self.assertIn("stand-in", view["prompt"])


if __name__ == "__main__":
    unittest.main()
