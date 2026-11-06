"""One place for the kitchen <-> room mapping, and one resolution of the binding per design."""
import ast
import json
import math
import sys
import copy
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import floorplan as fpm, geometry, intent, roomctx, threejs_export  # noqa: E402
from kitchen.placement import IDENTITY, Placement  # noqa: E402
from test_floorplan import ROOM, elem, plan, rect  # noqa: E402


def _spec():
    spec = intent.from_template(intent.parse_prompt("Bếp thẳng 3m")[0])
    cab = elem("c1", "furniture", "cabinet", rect(3400, 1000, 4000, 3000), "Tu")
    spec.floorplan = fpm.normalize(plan(ROOM, cab))
    return spec


class TestPlacement(unittest.TestCase):
    def test_round_trip_and_known_values(self):
        for yaw in (0, 90, -90, 180, 37.5):
            pl = Placement(yaw, 1234.5, -987.0)
            x, z = pl.to_room(310.0, 55.0)
            self.assertAlmostEqual(pl.to_kitchen(x, z)[0], 310.0, places=6)
            self.assertAlmostEqual(pl.to_kitchen(x, z)[1], 55.0, places=6)
        self.assertEqual(IDENTITY.to_room(5, 7), (5.0, 7.0))
        x, z = Placement(90, 100, 200).to_room(10, 0)       # +x of the kitchen turns to -z of the room
        self.assertAlmostEqual(x, 100.0), self.assertAlmostEqual(z, 190.0)

    def test_apply_binding_moves_a_document_exactly_as_the_placement_says(self):
        spec = _spec()
        ctx = roomctx.for_spec(spec, 3000, 2400)
        doc = {"modules": [{"transform": {"position": {"x": -500.0, "y": 0, "z": 300.0}, "rotation": {"x": 0, "y": 0, "z": 0}}}]}
        original = copy.deepcopy(doc)
        doc = fpm.apply_binding(doc, spec.floorplan, ctx.binding)
        self.assertEqual(original["modules"][0]["transform"]["position"]["x"], -500.0)  # the input is not changed
        pos = doc["modules"][0]["transform"]["position"]
        ex, ez = ctx.placement.to_room(-500.0, 300.0)
        self.assertAlmostEqual(pos["x"], ex, delta=0.001)
        self.assertAlmostEqual(pos["z"], ez, delta=0.001)


class TestRoomContext(unittest.TestCase):
    def test_binding_is_resolved_once_for_scene_and_export(self):
        spec = _spec()
        roomctx._CACHE.clear()
        with mock.patch.object(fpm, "resolve_binding", wraps=fpm.resolve_binding) as spy:
            geometry.compile_spec(spec)
            threejs_export.export(spec)
            geometry.compile_spec(spec)
        self.assertEqual(spy.call_count, 1)

    def test_a_different_binding_is_not_served_from_the_cache(self):
        spec = _spec()
        a = roomctx.for_spec(spec, 3000, 2400)
        spec.floorplan = {**spec.floorplan, "binding": {k: v for k, v in a.binding.items() if k != "transform"} | {"offset": 120.0}}
        b = roomctx.for_spec(spec, 3000, 2400)
        self.assertIsNot(a, b)
        self.assertNotEqual((a.placement.ox, a.placement.oz), (b.placement.ox, b.placement.oz))

    def test_no_floorplan_gives_no_context(self):
        spec = intent.from_template(intent.parse_prompt("Bếp thẳng 3m")[0])
        self.assertIsNone(roomctx.for_spec(spec, 3000, 2400))

    def test_geometry_does_not_depend_on_the_floorplan_module(self):
        tree = ast.parse((ROOT / "kitchen" / "geometry.py").read_text(encoding="utf-8"))
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                names |= {n.module or ""} | {a.name for a in n.names}
            elif isinstance(n, ast.Import):
                names |= {a.name for a in n.names}
        self.assertFalse({x for x in names if "floorplan" in x}, names)
        src = (ROOT / "kitchen" / "geometry.py").read_text(encoding="utf-8")
        self.assertNotIn("math.cos", src, "the rotation lives in kitchen.placement")


if __name__ == "__main__":
    unittest.main()
