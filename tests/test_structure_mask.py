"""Structures of an imported floorplan in the Python renderer: kitchen-frame meshes, their own seg mask, no effect on appearance layers."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kitchen import floorplan as fpm, geometry, intent, layers, render  # noqa: E402
from kitchen.spec import ViewAngle  # noqa: E402
from test_floorplan import ROOM, elem, plan, rect  # noqa: E402


def _spec(with_plan=True):
    spec = intent.from_template(intent.parse_prompt("Bếp thẳng 3m")[0])
    if with_plan:
        cab = elem("c1", "furniture", "cabinet", rect(3400, 1000, 4000, 3000), "Tu")
        spec.floorplan = fpm.normalize(plan(ROOM, cab))
    return spec


class TestStructureMask(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_structures_land_in_the_kitchen_frame(self):
        scene = geometry.compile_spec(_spec())
        m = next(x for x in scene.meshes if x.module == "STRUCT-c1")
        zs = [v[2] for v in m.vertices]
        self.assertEqual(m.type, "structure-furniture")
        self.assertAlmostEqual(min(zs), 0.0, delta=5)      # its back is on the wall plane (kitchen z = 0)
        self.assertAlmostEqual(max(zs), 600.0, delta=5)    # and it reaches 600 mm into the room
        self.assertAlmostEqual(max(v[1] for v in m.vertices), 900.0)
        self.assertFalse([p for p in scene.parts if p.type == "wall"], "the imported plan replaces the synthetic walls")

    def test_without_a_plan_nothing_changes(self):
        scene = geometry.compile_spec(_spec(False))
        self.assertFalse([m for m in scene.meshes if m.type.startswith("structure-")])
        self.assertTrue([p for p in scene.parts if p.type == "wall"])

    def test_seg_structure_has_only_structure_pixels(self):
        spec = _spec()
        scene = geometry.compile_spec(spec)
        view = ViewAngle(name="v", position=(-1.5, 2.2, 3.5), lookAt=(-1.5, 0.8, 0.0), verticalFov=70)
        info = render.render_view(scene, view, self.tmp / "v", 640, 480, colors=render.part_colors(spec, scene))
        self.assertIn("seg_structure.png", info["files"])
        seg = np.array(Image.open(self.tmp / "v" / "seg_structure.png"))
        full = np.array(Image.open(self.tmp / "v" / "seg.png"))
        inst = json.loads((self.tmp / "v" / "instances.json").read_text(encoding="utf-8"))["instances"]
        struct_vals = {i["value"] for i in inst if i["type"].startswith("structure-")}
        self.assertTrue(struct_vals, "a structure is visible in this view")
        on = seg.any(-1)
        self.assertTrue(on.any())
        np.testing.assert_array_equal(seg[on], full[on])
        cabinets = np.array(Image.open(self.tmp / "v" / "instance.png"))
        cab_vals = {i["value"] for i in inst if not i["type"].startswith("structure-")}
        self.assertFalse(np.isin(cabinets[on], list(cab_vals)).any(), "cabinet pixels are never in the structure mask")
        legend = render.render_views(spec, self.tmp / "all", views=["perspective"], width=320, height=240)
        self.assertIn("structure-wall", json.loads((self.tmp / "all" / "legend.json").read_text())["seg_structure"])
        self.assertIn("seg_structure.png", legend["views"]["perspective"]["files"])

    def test_structures_are_not_appearance_layers(self):
        spec = _spec()
        cat = layers.catalogue(spec, geometry.compile_spec(spec))
        st = [x for x in cat if str(x["type"]).startswith("structure-")]
        self.assertTrue(st)
        self.assertFalse(any(x["allowAppearanceChange"] for x in st))
        self.assertTrue(all(x["materialLocked"].startswith("structure:") or x["variant"] == "group" for x in st))

    def test_stair_is_stepped(self):
        fp = _spec().floorplan
        st = {"id": "S", "kind": "stair", "outline": [{"x": 0, "z": 0}, {"x": 1000, "z": 0}, {"x": 1000, "z": 3000}, {"x": 0, "z": 3000}],
              "base": 0, "height": 1800, "steps": 10, "arrow": [{"x": 500, "z": 0}, {"x": 500, "z": 3000}]}
        from kitchen import structure_mesh
        ms = structure_mesh.meshes([st], lambda x, z: (x, z))
        self.assertEqual(len(ms), 10)
        self.assertAlmostEqual(max(v[1] for v in ms[-1].vertices), 1800.0)
        self.assertAlmostEqual(max(v[1] for v in ms[0].vertices), 180.0)
        self.assertIsNotNone(fp)


if __name__ == "__main__":
    unittest.main()
