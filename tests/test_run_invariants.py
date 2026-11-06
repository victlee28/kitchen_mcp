"""Invariant: a module's world box rebuilt from its exported frame (position + yaw + local boxes) equals the geometry AABB.

This pins the two independent code paths (``geometry.box`` and ``threejs_export._module_frame``) to each other before they are merged
into ``runs``; any later change of run frames has to keep it true."""
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import geometry, threejs_export  # noqa: E402
from kitchen.spec import KitchenSpec, from_data  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
RUN = {"id": "TD90", "type": "base-drawers", "wall": "island", "offset": 2000, "fromCorner": 500, "width": 1200, "y": 0, "height": 840, "depth": 550}
BODY = ("carcass", "plinth", "door", "glass-door", "drawer", "side-panel", "shelf")


def _spec(facing=None, extra=True):
    data = json.loads(json.dumps(FIX))
    if extra:
        data["module"].append({**RUN, **({"facing": facing} if facing else {})})
    return from_data(KitchenSpec, data)


def _run_spec(yaw, x=-1500.0, z=2500.0):
    data = json.loads(json.dumps(FIX))
    data["runs"] = [{"id": "R1", "x": x, "z": z, "yaw": yaw}]
    data["module"] += [{"id": "TD91", "type": "base-drawers", "wall": "island", "run": "R1", "fromCorner": 0, "width": 1200, "y": 0, "height": 840, "depth": 550},
                       {"id": "TD92", "type": "base", "wall": "island", "run": "R1", "fromCorner": 1200, "width": 600, "y": 0, "height": 840, "depth": 550},
                       {"id": "TU93", "type": "upper", "wall": "island", "run": "R1", "fromCorner": 0, "width": 800, "y": 1400, "height": 700, "depth": 320}]
    return from_data(KitchenSpec, data)


def _world_box(mod):
    t = mod["transform"]
    px, py, pz, yaw = t["position"]["x"], t["position"]["y"], t["position"]["z"], math.radians(t["rotation"]["y"])
    lo, hi = [1e9] * 3, [-1e9] * 3
    for item in mod["parts"] + mod["drawers"] + mod["doors"]:
        d, q = item["dimensions"], item["transform"]["position"]
        for x in (q["x"], q["x"] + d["width"]):
            for y in (q["y"], q["y"] + d["height"]):
                for z in (q["z"], q["z"] + d["depth"]):
                    w = (px + x * math.cos(yaw) + z * math.sin(yaw), py + y, pz - x * math.sin(yaw) + z * math.cos(yaw))
                    for i in range(3):
                        lo[i], hi[i] = min(lo[i], w[i]), max(hi[i], w[i])
    return lo, hi


class TestRunInvariants(unittest.TestCase):
    def check(self, spec, ids=None):
        doc = threejs_export.export(spec)
        scene = geometry.compile_spec(spec)
        checked = 0
        for mod in doc["modules"]:
            ref = mod["sourceRef"]
            if ids and ref not in ids:
                continue
            ps = [p for p in scene.parts if p.module == ref and p.type in BODY]
            if not ps or not (mod["parts"] or mod["drawers"] or mod["doors"]):
                continue
            lo, hi = _world_box(mod)
            glo = [min(p.min[i] for p in ps) for i in range(3)]
            ghi = [max(p.max[i] for p in ps) for i in range(3)]
            for i in range(3):
                self.assertAlmostEqual(lo[i], glo[i], delta=1.5, msg=f"{ref} min[{i}]")
                self.assertAlmostEqual(hi[i], ghi[i], delta=1.5, msg=f"{ref} max[{i}]")
            checked += 1
        self.assertGreater(checked, 0)

    def test_fixture_walls(self):
        self.check(_spec(extra=False))

    def test_island_all_facings(self):
        for facing in (None, "-z", "+z", "-x", "+x"):
            with self.subTest(facing=facing):
                self.check(_spec(facing), {"TD90"})

    def test_angled_run_any_yaw(self):
        for yaw in (0, 30, 90, 120, 180, 225, 270, -45):
            with self.subTest(yaw=yaw):
                self.check(_run_spec(yaw), {"TD91", "TD92", "TU93"})

    def test_run_at_right_angles_matches_facing_runs(self):
        # yaw 180 puts the doors at -z like facing "-z", s growing towards -x: same box as the legacy free run with the same extent
        scene = geometry.compile_spec(_run_spec(180, x=-500, z=2000))
        ps = [p for p in scene.parts if p.module == "TD91" and p.type == "carcass"]
        self.assertAlmostEqual(min(p.min[0] for p in ps), -1700, delta=0.5)
        self.assertAlmostEqual(max(p.max[0] for p in ps), -500, delta=0.5)
        self.assertAlmostEqual(min(p.min[2] for p in ps), 1468, delta=0.5)
        self.assertAlmostEqual(max(p.max[2] for p in ps), 2000, delta=0.5)


if __name__ == "__main__":
    unittest.main()
