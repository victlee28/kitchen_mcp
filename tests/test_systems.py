"""Cabinet systems: which runs belong together. A run made against a floorplan element carries its id; the others are worked out from
which runs touch."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import edit, runs  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402


def mod(i, run, at, width=600, kind="base", **extra):
    high = kind.startswith("upper")
    return {"id": i, "type": kind, "wall": "island", "run": run, "fromCorner": at, "width": width, "y": 1500 if high else 0,
            "height": 700 if high else 840, "depth": 350 if high else 600, **extra}


def spec(run_list, modules):
    return KitchenSpec.model_validate({"runs": run_list, "module": modules})


L = [{"id": "R1", "x": -3000, "z": 0, "yaw": 0}, {"id": "R2", "x": -3000, "z": 2400, "yaw": 90}]        # back run, left run ending at the corner
L_MODS = [mod("A1", "R1", 0), mod("A2", "R1", 600), mod("B1", "R2", 1200), mod("B2", "R2", 1800)]
ISLAND = {"id": "R3", "x": -2500, "z": 2500, "yaw": 180}


class TestWorkedOut(unittest.TestCase):
    def test_an_l_is_one_system_and_an_island_another(self):
        s = spec([*L, ISLAND], [*L_MODS, mod("C1", "R3", 0), mod("C2", "R3", 600)])
        got = runs.systems(s)
        self.assertEqual({got[m] for m in ("A1", "A2", "B1", "B2")}, {"auto-R1"})
        self.assertEqual({got["C1"], got["C2"]}, {"auto-R3"})

    def test_an_angled_corner_and_a_corner_cabinet_join_their_runs(self):
        bay = spec([{"id": "R1", "x": -4000, "z": 0, "yaw": 0}, {"id": "R2", "x": -1900, "z": 0, "yaw": -45}],
                   [mod("A1", "R1", 0, 900), mod("A2", "R1", 900, 900), mod("B1", "R2", 300, 900)])
        self.assertEqual(set(runs.systems(bay).values()), {"auto-R1"})
        shelf = spec(L, [*L_MODS, {"id": "K1", "type": "corner-shelf", "wall": "island", "run": "R1", "turnsInto": "R2", "fromCorner": 2400,
                                   "width": 600, "rightLength": 600, "y": 1500, "height": 700, "depth": 350}])
        far = edit.apply_op(shelf, {"op": "move-run", "id": "R2", "changes": {"z": 4000}})        # apart, but the corner shelf still joins them
        self.assertEqual(set(runs.systems(far).values()), {"auto-R1"})

    def test_a_run_moved_away_becomes_its_own_system(self):
        s = edit.apply_op(spec(L, L_MODS), {"op": "move-run", "id": "R2", "changes": {"x": -6000}})
        got = runs.systems(s)
        self.assertEqual((got["A1"], got["B1"]), ("auto-R1", "auto-R2"))

    def test_lowest_run_number_names_the_group(self):
        s = spec([{"id": "R10", "x": -3000, "z": 0, "yaw": 0}, {"id": "R2", "x": -3000, "z": 2400, "yaw": 90}],
                 [mod("A1", "R10", 0), mod("A2", "R10", 600), mod("B1", "R2", 1200), mod("B2", "R2", 1800)])
        self.assertEqual(set(runs.systems(s).values()), {"auto-R2"})

    def test_cabinets_in_no_run_are_the_whole_design(self):
        s = KitchenSpec.model_validate({"module": [{"id": "TD1", "type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 600}]})
        self.assertEqual(runs.systems(s), {"TD1": "design"})


class TestRecorded(unittest.TestCase):
    def test_a_recorded_system_spreads_to_the_runs_it_touches_only(self):
        s = spec([{**L[0], "system": "furniture_003"}, L[1], ISLAND], [*L_MODS, mod("C1", "R3", 0)])
        got = runs.systems(s)
        self.assertEqual({got[m] for m in ("A1", "B1")}, {"furniture_003"})
        self.assertEqual(got["C1"], "auto-R3")

    def test_two_recorded_systems_that_touch_are_not_merged(self):
        s = spec([{**L[0], "system": "furniture_003"}, {**L[1], "system": "furniture_017"}], L_MODS)
        got = runs.systems(s)
        self.assertEqual((got["A1"], got["B1"]), ("furniture_003", "furniture_017"))

    def test_an_unrecorded_run_between_two_systems_takes_the_nearest(self):
        three = [{"id": "R1", "x": -3000, "z": 0, "yaw": 0, "system": "wall_a"}, {"id": "R2", "x": -1800, "z": 0, "yaw": 0},
                 {"id": "R3", "x": -1180, "z": 0, "yaw": 0, "system": "wall_b"}]
        s = spec(three, [mod("A1", "R1", 0), mod("A2", "R1", 600), mod("B1", "R2", 0), mod("C1", "R3", 0)])
        got = runs.systems(s)
        self.assertEqual(got["B1"], "wall_a", "R2 touches R1 (0 mm) and is 20 mm from R3: the nearer wins")

    def test_editing_keeps_the_system(self):
        s = spec([{**L[0], "system": "furniture_003"}, L[1]], L_MODS)
        for op in ({"op": "add", "afterModule": "A2", "module": {"width": 400}}, {"op": "stretch-run", "id": "R1", "end": "end", "delta": 100},
                   {"op": "move-run", "id": "R1", "changes": {"x": -2900}}):
            after = edit.apply_op(s, op)
            self.assertEqual(next(r for r in after.runs if r.id == "R1").system, "furniture_003", op)
        with self.assertRaises(Exception):
            edit.apply_op(s, {"op": "move-run", "id": "R1", "changes": {"system": "x"}})

    def test_set_run_system(self):
        s = spec(L, L_MODS)
        named = edit.apply_op(s, {"op": "set-run-system", "id": "R2", "system": "furniture_017"})
        self.assertEqual(runs.systems(named)["B1"], "furniture_017")
        cleared = edit.apply_op(named, {"op": "set-run-system", "id": "R2", "system": None})
        self.assertEqual(runs.systems(cleared)["B1"], "auto-R1")
        for bad in ("a:b", "a,b", "có dấu"):
            with self.assertRaises(Exception):
                edit.apply_op(s, {"op": "set-run-system", "id": "R2", "system": bad})

    def test_element_ids_become_valid_system_ids(self):
        self.assertEqual(runs.system_id("furniture_003"), "furniture_003")
        self.assertEqual(runs.system_id("tủ:1,2"), "t__1_2")
        self.assertEqual(runs.system_id(""), "element")

    def test_old_designs_still_load(self):
        old = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        self.assertTrue(runs.systems(KitchenSpec.model_validate(old)))


class TestSelectionGroups(unittest.TestCase):
    """The layers catalogue carries each part's system; Shift groups exist per system when there are several."""

    def two(self):
        """furniture_003: an L (back run + left run). furniture_017: an island. Both with doors, drawers and wall cabinets."""
        rs = [{**L[0], "system": "furniture_003"}, L[1], {**ISLAND, "system": "furniture_017"}]
        ms = [mod("A1", "R1", 0, doors=[300, 300]), mod("A2", "R1", 600, frontSections=[{"type": "drawer", "height": 300}, {"type": "drawer", "height": 440}]),
              mod("U1", "R1", 0, 600, "upper"), mod("B1", "R2", 1200), mod("B2", "R2", 1800), mod("C1", "R3", 0), mod("C2", "R3", 600)]
        return spec(rs, ms)

    def catalogue(self, s):
        from kitchen import geometry, layers
        scene = geometry.compile_spec(s)
        return scene, layers.catalogue(s, scene)

    def test_every_cabinet_part_knows_its_system(self):
        _, cat = self.catalogue(self.two())
        parts = [x for x in cat if x["variant"] == "part" and x["module"]]
        self.assertEqual({x["module"]: x["cabinetSystemId"] for x in parts if x["module"] in ("A1", "B1", "C1")},
                         {"A1": "furniture_003", "B1": "furniture_003", "C1": "furniture_017"})
        tops = {x["cabinetSystemId"] for x in cat if x["variant"] == "part" and x["type"] == "countertop"}
        self.assertEqual(tops, {"furniture_003", "furniture_017"}, "a worktop belongs to the system of its run")

    def test_groups_per_system_besides_the_old_ones(self):
        _, cat = self.catalogue(self.two())
        ids = {x["id"]: x for x in cat if x["variant"] == "group"}
        door = ids["sys:furniture_003:tier:base:door"]
        members = {c.split("-")[0] for c in door["component"]}
        self.assertEqual(members, {"A1", "B1", "B2"}, "base doors of the L only: not the island's, not the drawers")
        self.assertEqual({c.split("-")[0] for c in ids["sys:furniture_017:tier:base:door"]["component"]}, {"C1", "C2"})
        self.assertEqual({c.split("-")[0] for c in ids["tier:base:door"]["component"]}, {"A1", "B1", "B2", "C1", "C2"}, "the old group is unchanged")
        self.assertIn("sys:furniture_003:tier:upper:door", ids)
        self.assertNotIn("sys:furniture_017:tier:upper:door", ids, "the island has no wall cabinets")

    def test_one_system_has_no_extra_groups(self):
        _, cat = self.catalogue(spec(L, L_MODS))
        self.assertFalse([x for x in cat if x["id"].startswith("sys:")])

    def test_a_material_for_one_system_stays_in_that_system(self):
        from kitchen import layers
        s = self.two()
        scene, cat = self.catalogue(s)
        layer, _ = layers.resolve(cat, "sys:furniture_003:tier:base:door")
        op, scope = layers.design_op(s, layer, "Laminate xanh", scene)
        self.assertEqual((op["op"], sorted(o["id"] for o in op["ops"])), ("multi", ["A1", "B1", "B2"]))
        after = edit.apply_op(s, op)
        self.assertEqual({m.id: m.material for m in after.module if m.material}, {"A1": "Laminate xanh", "B1": "Laminate xanh", "B2": "Laminate xanh"})
        self.assertIn("vật liệu riêng", scope)
        whole, _ = layers.resolve(cat, "tier:base:front")
        self.assertEqual(layers.design_op(s, whole, "Laminate xanh", scene)[0]["op"], "common", "every base front: the shared material, as before")

    def test_a_hand_picked_selection_changes_only_its_modules(self):
        from kitchen import layers
        s = self.two()
        scene, cat = self.catalogue(s)
        doors = [x["id"] for x in cat if x["variant"] == "part" and x["module"] == "C1" and x["type"] == "door"]
        layer, _ = layers.resolve(cat, "parts:" + ",".join(doors))
        op, _ = layers.design_op(s, layer, "Sồi", scene)
        self.assertEqual((op["op"], op["id"]), ("update", "C1"))

    def test_the_page_gets_system_and_tier_of_each_module(self):
        import shutil
        import tempfile
        from kitchen.service import KitchenService
        tmp = Path(tempfile.mkdtemp(prefix="systems-"))
        try:
            svc = KitchenService(tmp / "k.db", tmp / "r")
            did = svc.create_from_spec(json.loads(json.dumps(self.two().model_dump(mode="json"))))["id"]
            got = svc.get(did)["systems"]
            self.assertEqual((got["A1"], got["U1"], got["C1"]), ({"system": "furniture_003", "tier": "base", "storey": "base"},
                                                                {"system": "furniture_003", "tier": "upper", "storey": "upper"},
                                                                {"system": "furniture_017", "tier": "base", "storey": "base"}))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
