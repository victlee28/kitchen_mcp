"""A free-standing run can face any of four directions: parts, Three.js frame and overlap boxes must agree for each."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import geometry, rules, threejs_export  # noqa: E402
from kitchen.spec import KitchenSpec, from_data  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
# a 1200-wide run whose door face is at offset 2000, 550 deep, starting 500 from the origin of its own axis
RUN = {"id": "TD90", "type": "base-drawers", "wall": "island", "offset": 2000, "fromCorner": 500, "width": 1200, "y": 0, "height": 840, "depth": 550}


def _spec(facing):
    data = json.loads(json.dumps(FIX))
    data["module"].append({**RUN, **({"facing": facing} if facing else {})})
    return from_data(KitchenSpec, data)


def _box(spec, kind):
    parts = [p for p in geometry.compile_spec(spec).parts if p.module == "TD90" and (p.type == kind if kind else p.type in ("carcass", "door", "plinth"))]
    return parts, [min(p.min[i] for p in parts) for i in range(3)], [max(p.max[i] for p in parts) for i in range(3)]


class TestFreeRun(unittest.TestCase):
    def test_footprint_per_facing(self):
        # (x range, z range) of the carcass of a 1200 x 550 run, door face at 2000
        want = {None: ((-1700, -500), (2000, 2550)), "-z": ((-1700, -500), (2000, 2550)), "+z": ((-1700, -500), (1450, 2000)),
                "-x": ((-2000, -1450), (500, 1700)), "+x": ((-2550, -2000), (500, 1700))}
        for facing, (xs, zs) in want.items():
            _, lo, hi = _box(_spec(facing), None)
            self.assertEqual(((round(lo[0]), round(hi[0])), (round(lo[2]), round(hi[2]))), (xs, zs), facing)

    def test_doors_sit_on_the_outer_face(self):
        face = {None: ("z", "min", 2000), "+z": ("z", "max", 2000), "-x": ("x", "min", -2000), "+x": ("x", "max", -2000)}
        for facing, (axis, side, value) in face.items():
            spec = _spec(facing)
            _, lo, hi = _box(spec, "door")
            i = 0 if axis == "x" else 2
            self.assertAlmostEqual((lo if side == "min" else hi)[i], value, delta=0.5, msg=facing)

    def test_overlap_box_matches_the_carcass(self):
        for facing in (None, "+z", "-x", "+x"):
            spec = _spec(facing)
            _, lo, hi = _box(spec, None)
            box = next(b for b in rules._envelopes(spec) if b[0] == "TD90")
            self.assertEqual((round(box[1][0]), round(box[2][0]), round(box[1][2]), round(box[2][2])), (round(lo[0]), round(hi[0]), round(lo[2]), round(hi[2])), facing)

    def test_threejs_frame_encloses_the_parts(self):
        for facing in (None, "+z", "-x", "+x"):
            spec = _spec(facing)
            doc = threejs_export.export(spec)
            mod = next(m for m in doc["modules"] if m["sourceRef"] == "TD90")
            self.assertEqual([round(v) for v in (mod["dimensions"]["width"], mod["dimensions"]["depth"])], [1200, 550])
            for item in mod["parts"] + mod["drawers"] + mod["doors"]:
                d = item["dimensions"]
                t = item["transform"]["position"]
                self.assertTrue(-1 <= t["x"] and t["x"] + d["width"] <= 1200 + 1 and -1 <= t["z"] and t["z"] + d["depth"] <= 550 + 1, (facing, item["id"], t, d))

    def test_facing_only_for_free_runs(self):
        data = json.loads(json.dumps(FIX))
        data["module"][0]["facing"] = "+z"
        with self.assertRaises(ValueError):
            from_data(KitchenSpec, data)


if __name__ == "__main__":
    unittest.main()
