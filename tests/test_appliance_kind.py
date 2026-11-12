"""Changing an appliance to a model of another kind (11/11/2026): the cabinets around it change with it, through the preview."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import appliance_kind, appliance_models as am, geometry, rules  # noqa: E402
from kitchen.edit import apply_op, combine_ops  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

SPEC = KitchenSpec.model_validate({
    "module": [
        {"id": "TD1", "type": "base-cooktop", "wall": "back", "fromCorner": 0, "width": 800, "height": 840, "depth": 580},
        {"id": "TC1", "type": "tall-fridge", "wall": "back", "fromCorner": 800, "width": 700, "height": 2400, "depth": 640, "niche": 1650},
        {"id": "TT1", "type": "upper-hood", "wall": "back", "fromCorner": 0, "width": 800, "y": 1665, "height": 615, "depth": 320},
        {"id": "TN1", "type": "upper-loft", "wall": "back", "fromCorner": 0, "width": 800, "y": 2280, "height": 330, "depth": 320}],
    "appliances": [
        {"id": "TB1", "type": "cooktop", "module": "TD1", "dimensions": "730 × 430"},
        {"id": "TB2", "type": "hood", "module": "TT1", "dimensions": "730 × 165"},
        {"id": "TB3", "type": "fridge", "module": "TC1", "dimensions": "600 × 1600 × 620"}]})


def change(spec, app_id, model):
    app = next(a for a in spec.appliances if a.id == app_id)
    ops, notes = appliance_kind.plan(spec, app, am.model(model))
    return apply_op(spec, combine_ops(ops)), notes


class TestHood(unittest.TestCase):
    def test_insert_to_chimney_and_back(self):
        hung, notes = change(SPEC, "TB2", "hood-wall-90")
        self.assertNotIn("TT1", {m.id for m in hung.module})
        self.assertNotIn("TN1", {m.id for m in hung.module})                  # the top-row cabinet stood on the hood cabinet
        self.assertEqual(next(a for a in hung.appliances if a.id == "TB2").module, "TD1")
        self.assertEqual(len([p for p in geometry.compile_spec(hung).parts if p.module == "TB2"]), 2)      # canopy + chimney
        self.assertEqual([i for i in rules.validate(hung)["issues"] if i["severity"] == "error"], [])
        back, _ = change(hung, "TB2", "hood-slim-60" if "hood-slim-60" in am.models() else
                         next(m["id"] for m in am.models().values() if m["type"] == "hood" and am.kind_of(m) == "insert"))
        cabinet = next(m for m in back.module if m.type == "upper-hood")
        self.assertEqual(next(a for a in back.appliances if a.id == "TB2").module, cabinet.id)

    def test_popup_says_what_happens(self):
        hood = next(a for a in SPEC.appliances if a.id == "TB2")
        status, reasons = am.fit(SPEC, hood, am.model("hood-wall-90"))
        self.assertEqual(status, "check")
        self.assertTrue(any(getattr(r, "key", "").startswith("reason.hood-cabinet-removed") and r.params["id"] == "TT1" for r in reasons))

    def test_insert_cannot_go_where_wall_cabinets_stand(self):
        hung, _ = change(SPEC, "TB2", "hood-wall-90")
        blocked = apply_op(hung, {"op": "add", "closeGap": False, "module": {"id": "TT9", "type": "upper", "wall": "back", "fromCorner": 0,
                                                                             "width": 800, "y": 1530, "height": 700, "depth": 320}})
        insert = next(m["id"] for m in am.models().values() if m["type"] == "hood" and am.kind_of(m) == "insert")
        with self.assertRaises(InvalidInput):
            change(blocked, "TB2", insert)
        hood = next(a for a in blocked.appliances if a.id == "TB2")
        self.assertEqual(am.fit(blocked, hood, am.model(insert))[0], "blocked")


class TestFridge(unittest.TestCase):
    def test_integrated_hides_the_fridge_behind_doors_and_back(self):
        inte, _ = change(SPEC, "TB3", "fridge-int-56")
        self.assertIsNone(inte.find("TC1").niche)
        self.assertFalse([p for p in geometry.compile_spec(inte).parts if p.module == "TB3"])
        free, _ = change(inte, "TB3", "fridge-2d-60")
        self.assertEqual(free.find("TC1").niche, am.model("fridge-2d-60")["niche"]["h"])
        self.assertTrue([p for p in geometry.compile_spec(free).parts if p.module == "TB3"])


if __name__ == "__main__":
    unittest.main()
