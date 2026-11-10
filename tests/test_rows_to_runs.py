"""A kitchen that follows the walls, rewritten as explicit runs, stands exactly where it stood."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import edit, geometry, rows_to_runs, rules, runs, threejs_export  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))


def box(i, wall, at, width, kind="base", **extra):
    high = kind.startswith("upper")
    return {"id": i, "type": kind, "wall": wall, "fromCorner": at, "width": width, "y": 1500 if high else 0, "height": 700 if high else 840,
            "depth": 350 if high else 600, **extra}


def spec_of(modules, **extra):
    return KitchenSpec.model_validate({"common": {"material": {"wallTile": "white"}}, "module": modules, **extra})


def converted(spec):
    data, notes = rows_to_runs.convert(spec)
    return KitchenSpec.model_validate(data), notes


class TestConvert(unittest.TestCase):
    def test_the_sample_l_kitchen_stands_where_it_stood(self):
        before = KitchenSpec.model_validate(FIX)
        after, _ = converted(before)
        self.assertEqual(rows_to_runs.equivalent(before, after), [])
        self.assertTrue(after.runs and any(m.run for m in after.module))
        self.assertEqual(sorted(geometry.default_views(before)), sorted(geometry.default_views(after)), "the same views, under the same names")
        self.assertEqual({(i["rule"], i["severity"]) for i in rules.validate(before)["issues"]}, {(i["rule"], i["severity"]) for i in rules.validate(after)["issues"]})
        self.assertEqual(threejs_export.integrity(threejs_export.export(after)), [])

    def test_every_kind_of_row(self):
        mods = [box("B1", "back", 0, 600, doors=[200, 400]), box("B2", "back", 600, 900), box("U1", "back", 0, 600, "upper"),
                box("R1x", "right", 600, 450), box("R2x", "right", 1050, 800, blindCorner=0), box("L1", "left", 600, 700, doors=[300, 400]),
                box("I1", "island", 300, 900, offset=2400, facing="-z"), box("I2", "island", 300, 900, offset=3600, facing="+z"),
                box("I3", "island", 1200, 800, offset=1300, facing="+x"), box("I4", "island", 2400, 800, offset=900, facing="-x")]
        before = spec_of(mods)
        after, notes = converted(before)
        self.assertEqual((rows_to_runs.equivalent(before, after), notes), ([], []))
        self.assertEqual(len(after.runs), 7)
        b1 = next(m for m in after.module if m.id == "B1")
        self.assertEqual((b1.fromCorner, b1.doors), (900.0, [400.0, 200.0]), "the back wall is measured from the right: mirrored, doors in reverse")
        r1 = next(m for m in after.module if m.id == "R1x")
        self.assertEqual((r1.fromCorner, r1.hingeSides), (600.0, ["right"]), "the right wall is not mirrored; its lone door keeps the hinge it had")
        self.assertEqual((after.room.length("back"), after.room.length("right")), geometry._wall_length(before), "the kitchen frame is written down")

    def test_a_blind_corner_changes_ends_with_its_row(self):
        mods = [box("B1", "back", 0, 1000, blindCorner=600, doors=[400]), box("B2", "back", 1000, 600), box("R1x", "right", 600, 600, blindCorner=0),
                box("L1", "left", 600, 900, blindCorner=300, endPanel=18, doors=[582]),
                {"id": "KG1", "type": "corner-shelf", "wall": "corner", "y": 1500, "height": 700, "depth": 320, "backLength": 600, "rightLength": 600}]
        before = spec_of(mods)
        after, notes = converted(before)
        self.assertEqual(rows_to_runs.equivalent(before, after), [])
        got = {m.id: (m.wall, bool(m.run), m.blindSide) for m in after.module}
        self.assertEqual(got, {"B1": ("island", True, "end"), "B2": ("island", True, "start"), "L1": ("island", True, "end"), "KG1": ("island", True, "start"),
                               "R1x": ("island", True, "start")})
        b1 = next(m for m in after.module if m.id == "B1")
        self.assertEqual((b1.fromCorner, b1.fronts, b1.blind_span), (600.0, (600.0, 1000.0), (1000.0, 1600.0)), "the blind part is at the corner end of the run")
        self.assertEqual(notes, [])
        self.assertEqual(threejs_export.integrity(threejs_export.export(after)), [])

    def corner_kitchen(self, **extra):
        from kitchen import moldings
        mods = [box("B0", "back", 0, 600), box("B1", "back", 600, 900), box("B2", "back", 1500, 900), box("U1", "back", 600, 900, "upper"), box("U2", "back", 1500, 900, "upper"),
                box("R1x", "right", 600, 900), box("U3", "right", 600, 900, "upper"),
                {"id": "KG1", "type": "corner-shelf", "wall": "corner", "y": 1500, "height": 700, "depth": 350, "backLength": 600, "rightLength": 600}]
        return spec_of(mods, moldings=[m.model_dump() for m in moldings.default_moldings(True, True)], **extra)

    def test_a_corner_shelf_becomes_a_cabinet_that_turns_from_the_back_run_into_the_right_run(self):
        from kitchen import moldings
        before = self.corner_kitchen()
        after, notes = converted(before)
        self.assertEqual((rows_to_runs.equivalent(before, after), notes), ([], []))
        shelf = next(m for m in after.module if m.id == "KG1")
        back, right = (next(r.id for r in after.runs if r.yaw == yaw) for yaw in (0.0, -90.0))
        self.assertEqual((shelf.wall, shelf.run, shelf.turnsInto, shelf.fromCorner, shelf.width, shelf.rightLength), ("island", back, right, 1800.0, 600.0, 600.0))
        chain = lambda sp: sorted((r.molding.variant, len(r.points), round(r.length)) for r in moldings.compute_runs(sp))
        self.assertEqual(chain(before), chain(after), "the crown still goes round the corner over the shelf")
        self.assertFalse([i for i in rules.validate(after)["issues"] if i["rule"] in ("GEO-COLLISION", "GEO-CORNER")])

    def test_the_exported_corner_shelf_is_the_same_object(self):
        before = self.corner_kitchen()
        after, _ = converted(before)
        docs = [threejs_export.export(sp) for sp in (before, after)]
        self.assertEqual(threejs_export.integrity(docs[1]), [])
        text = [json.dumps(d, sort_keys=True) for d in docs]
        a, b = (next(m for m in d["modules"] if m["id"] == "MOD-KG1") for d in docs)
        self.assertEqual((a["dimensions"], a["transform"]["position"]), (b["dimensions"], b["transform"]["position"]))
        self.assertEqual(len(a.get("components", [])), len(b.get("components", [])))
        self.assertEqual(sorted(json.dumps(c.get("transform", {}).get("position"), sort_keys=True) for c in a.get("components", [])),
                         sorted(json.dumps(c.get("transform", {}).get("position"), sort_keys=True) for c in b.get("components", [])), "every board where it was")
        self.assertTrue(text)

    def test_a_corner_shelf_whose_runs_part_is_reported_and_one_without_both_runs_stays_on_its_walls(self):
        after, _ = converted(self.corner_kitchen())
        right = next(r.id for r in after.runs if r.yaw == -90.0)
        apart = edit.apply_op(after, {"op": "move-run", "id": right, "changes": {"z": 800}})
        self.assertIn("GEO-CORNER", {i["rule"] for i in rules.validate(apart)["issues"]})
        alone = spec_of([box("B1", "back", 600, 900),
                         {"id": "KG1", "type": "corner-shelf", "wall": "corner", "y": 1500, "height": 700, "depth": 350, "backLength": 600, "rightLength": 600}])
        kept, notes = converted(alone)
        self.assertEqual((next(m for m in kept.module if m.id == "KG1").wall, len(notes)), ("corner", 1))
        self.assertEqual(rows_to_runs.equivalent(alone, kept), [])

    def test_a_sink_given_by_wall_and_centre_joins_its_cabinet_and_then_follows_it(self):
        before = spec_of([box("B1", "back", 0, 600), box("B2", "back", 600, 800, "base-sink"), box("B3", "back", 1400, 600)],
                         appliances=[{"id": "TB1", "type": "sink", "wall": "back", "center": 1000, "dimensions": "700 × 430"},
                                     {"id": "TB2", "type": "faucet", "wall": "back", "center": 1100, "dimensions": "cao 300"}])
        after, _ = converted(before)
        self.assertEqual(rows_to_runs.equivalent(before, after), [])
        sink, tap = after.appliances
        self.assertEqual((sink.module, sink.wall, sink.center), ("B2", None, None), "in the middle of its cabinet: nothing to store")
        self.assertEqual((tap.module, tap.center), ("B2", 900.0), "off the middle: its place along the run is kept")
        moved = edit.apply_op(after, {"op": "remove", "id": "B3"})                # B3 is first in the run now (the left end)
        self.assertEqual(runs.spot(moved, moved.appliances[0]).center, 400.0)

    def test_a_kitchen_already_by_runs_is_left_alone(self):
        once, _ = converted(KitchenSpec.model_validate(FIX))
        twice, notes = rows_to_runs.convert(once)
        self.assertEqual(KitchenSpec.model_validate(twice), once)

    def test_moldings_keep_their_shape(self):
        from kitchen import moldings
        before = spec_of([box("B1", "back", 0, 900), box("B2", "back", 900, 900), box("U1", "back", 0, 900, "upper"), box("U2", "back", 900, 900, "upper")],
                         moldings=[m.model_dump() | {"wall": ["back"]} for m in moldings.default_moldings(True, True)])
        after, _ = converted(before)
        self.assertEqual(rows_to_runs.equivalent(before, after), [])
        self.assertEqual({tuple(m.wall) for m in after.moldings}, {("R1",)})


class TestNewKitchens(unittest.TestCase):
    """What the generator makes is stored by runs, and the everyday edits still work on it."""

    def setUp(self):
        import tempfile
        from kitchen.service import KitchenService
        self.tmp = Path(tempfile.mkdtemp(prefix="byruns-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.config = self.svc.config.__class__.from_env({})          # no LLM: the regex parser

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_described_l_kitchen_is_stored_by_runs_and_reads_like_the_walled_one(self):
        from kitchen import intent
        did = self.svc.create_from_prompt("tủ bếp chữ L dài 3m cạnh phải 2.4m có tủ lạnh")["id"]
        spec, _ = self.svc.store.get(did)
        self.assertTrue(spec.runs and all(m.run for m in spec.module if m.wall != "corner"))
        template, _ = intent.parse_prompt("tủ bếp chữ L dài 3m cạnh phải 2.4m có tủ lạnh")
        walled = intent.from_template(template, "x", self.svc.store.rule_rows())
        self.assertEqual(rows_to_runs.equivalent(walled, spec), [])
        self.assertTrue({"back-wall", "right-wall"} <= set(geometry.default_views(spec)))
        self.assertEqual({(i["rule"], i["severity"]) for i in rules.validate(walled)["issues"]}, {(i["rule"], i["severity"]) for i in rules.validate(spec)["issues"]})

    def test_adding_and_removing_a_cabinet_still_works(self):
        did = self.svc.create_from_prompt("tủ bếp chữ I dài 3m")["id"]
        spec, rev = self.svc.store.get(did)
        first = next(m for m in spec.module if m.storey == "base")
        preview = self.svc.propose(did, {"op": "add", "afterModule": first.id, "module": {"type": "base", "width": 400}}, rev)
        self.assertTrue(preview["applicable"], preview.get("error"))
        self.svc.apply(did, preview["operation"], rev, "test", preview["opHash"])
        after, rev2 = self.svc.store.get(did)
        new = next(m for m in after.module if m.id not in {x.id for x in spec.module})
        self.assertEqual((new.run, new.wall), (first.run, "island"), "it joins the run of the cabinet it stands beside")
        self.assertFalse([i for i in rules.validate(after)["issues"] if i["rule"] == "GEO-COLLISION"])
        gone = self.svc.propose(did, {"op": "remove", "id": new.id}, rev2)
        self.assertTrue(gone["applicable"])


if __name__ == "__main__":
    unittest.main()
