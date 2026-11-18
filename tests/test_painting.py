"""Wall paintings (18/11/2026): "thay bằng bức tranh" on a TV hangs a painting in its place: a model of type ``painting`` swaps with a
``tv`` (both hung on the wall), drawn, exported and described like the TV was."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import appliance_models, geometry, threejs_export, tv_system as tv  # noqa: E402
from kitchen.edit import apply_op  # noqa: E402
from kitchen.run_line import Line, plan_on_line  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402


def _spec_with_tv() -> KitchenSpec:
    spec = KitchenSpec.model_validate({"module": []})
    plan = plan_on_line(spec, Line((0.0, 0.0), (3980.0, 0.0), (0.0, 1.0)), tv.layout(3980, {"cabinetTop": 2610}), run_fields=tv.run_fields("columns"))
    return apply_op(spec, plan["operation"])


def _tv(spec: KitchenSpec):
    return next(a for a in spec.appliances if a.type == "tv")


class TestModels(unittest.TestCase):
    def test_the_catalog_has_paintings_with_a_default(self):
        paintings = [m for m in appliance_models.models().values() if m["type"] == "painting"]
        self.assertGreaterEqual(len(paintings), 2)
        default = appliance_models.default_for("painting")
        assert default is not None
        self.assertEqual(default["id"], "painting-120x80")

    def test_a_painting_is_offered_for_a_tv_only_when_the_sentence_asks_for_it(self):
        spec = _spec_with_tv()
        asked = appliance_models.candidates(spec, _tv(spec), "thay bằng bức tranh")
        self.assertTrue(asked)
        self.assertEqual({c["id"].split("-")[0] for c in asked}, {"painting"})
        self.assertTrue(all(c["status"] == "ok" for c in asked))
        plain = appliance_models.candidates(spec, _tv(spec), "")
        self.assertEqual({c["id"].split("-")[0] for c in plain}, {"tv"})
        self.assertFalse(appliance_models.candidates(spec, _tv(spec), "tránh cửa sổ")[0]["id"].startswith("painting"))

    def test_only_wall_hung_types_swap(self):
        self.assertTrue(appliance_models.swaps("tv", "painting"))
        self.assertTrue(appliance_models.swaps("painting", "tv"))
        self.assertFalse(appliance_models.swaps("tv", "fridge"))


class TestSwap(unittest.TestCase):
    def setUp(self):
        self.spec = _spec_with_tv()
        self.old = _tv(self.spec)
        self.after = apply_op(self.spec, {"op": "update-appliance", "id": self.old.id, "model": "painting-120x80"})
        self.painting = next(a for a in self.after.appliances if a.id == self.old.id)

    def test_the_tv_becomes_a_painting_in_the_same_place(self):
        p = self.painting
        self.assertEqual((p.type, p.model, p.module, p.center), ("painting", "painting-120x80", self.old.module, self.old.center))
        self.assertEqual(p.dimensions, "1200 × 800 × 30")
        self.assertIsNone(p.energy)

    def test_it_is_drawn_on_the_wall_where_the_tv_was(self):
        before = next(x for x in geometry.compile_spec(self.spec).parts if x.type == "tv")
        part = next(x for x in geometry.compile_spec(self.after).parts if x.type == "painting")
        self.assertAlmostEqual((part.min[0] + part.max[0]) / 2, (before.min[0] + before.max[0]) / 2)
        self.assertAlmostEqual(part.max[0] - part.min[0], 1200.0)
        self.assertAlmostEqual(part.max[1] - part.min[1], 800.0)

    def test_the_export_has_a_painting_and_stays_valid(self):
        doc = threejs_export.export(self.after, "p", 1)
        hung = [a for a in doc["appliances"] if a["type"] == "Painting"]
        self.assertEqual(len(hung), 1)
        self.assertEqual((hung[0]["installation"]["mountType"], hung[0]["energy"], hung[0]["box"]["kind"]), ("wall_mounted", "none", "painting"))
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)][:3], [])

    def test_the_image_ai_hears_of_a_painting(self):
        facts = appliance_models.ai_facts(self.after, self.painting)
        self.assertIn("painting", json.dumps(facts))
        self.assertNotIn("television", json.dumps(facts))

    def test_and_back_to_a_tv(self):
        back = apply_op(self.after, {"op": "update-appliance", "id": self.old.id, "model": "tv-55"})
        self.assertEqual(next(a for a in back.appliances if a.id == self.old.id).type, "tv")


class TestService(unittest.TestCase):
    def test_replace_appliance_previews_the_painting(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        svc = KitchenService(tmp / "k.db", tmp / "r")
        did = svc.create_from_spec(json.loads(json.dumps(_spec_with_tv().model_dump(mode="json"))))["id"]
        spec, rev = svc.store.get(did)
        tb = _tv(spec).id
        listed = svc.template(did, {"kind": "replace-appliance", "id": tb, "prompt": "thay bằng bức tranh"}, rev)
        self.assertEqual(listed["status"], "choose-model")
        first = listed["models"][0]["id"]
        self.assertTrue(first.startswith("painting-"))
        done = svc.template(did, {"kind": "replace-appliance", "id": tb, "model": first}, rev)
        self.assertEqual((done["status"], done["fit"], done["proposal"]["validation"]["introducesErrors"]), ("ok", "ok", False))


if __name__ == "__main__":
    unittest.main()
