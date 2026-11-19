"""19/11/2026, the layered picture's right-click menu (claude/menu-tren-anh-viec-de-sau.md):

* a pixel's point on the plan: the server's pick gives where the pixel lies (``point``, mm, the 3D view's frame), and whether it shows the
  floor (``floor``), so the picture's menu can draw a run on the floor and send a click point with a floorplan element, as the 3D view does;
* the reveal of an opening's hole (``<wall>#reveal-<opening>``): a wall face of its own (export, render instance, layer, finish)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import render, threejs_export  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

# an opening with no frame (a window's frame fills a 100 mm wall's hole), above the wall cabinets, so the views see into its hole
WINDOW = {"op": "add-opening", "opening": {"kind": "passage", "wallAxis": "back", "center": 1800, "width": 900, "height": 400, "sill": 2300}}


class TestImagePointsAndReveals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="reveal-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        cls.did = cls.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "L", "backWallLength": 3600, "ceiling": 3000}), "t")["id"]
        cls.svc.apply(cls.did, WINDOW, None)
        spec, rev = cls.svc.store.get(cls.did)
        cls.spec, cls.rev = spec, rev
        cls.doc = threejs_export.export(spec, catalog=cls.svc.catalog_for_revision(cls.did, rev))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def reveal_id(self):
        return next(s["id"] for s in self.doc["room"]["surfaces"] if s.get("opening") == "OP1")

    def test_the_hole_of_an_opening_has_a_reveal_face(self):
        rv = [s for s in self.doc["room"]["surfaces"] if s.get("opening") == "OP1"]
        self.assertEqual(len(rv), 1, "one reveal per hole")
        r = rv[0]
        self.assertEqual((r["face"], r["room"], len(r["quads"])), ("reveal-op1", None, 4), "two jambs, a head and a sill")
        self.assertEqual((r["span"]["y0"], r["span"]["y1"], r["span"]["e1"] - r["span"]["e0"]), (2300.0, 2700.0, 900.0))
        for q in r["quads"]:            # every piece lies inside the hole's box
            for x, y, z in q:
                self.assertTrue(2300.0 - 1e-6 <= y <= 2700.0 + 1e-6)

    def test_the_reveal_is_a_layer_of_the_picture_and_can_be_finished(self):
        rid = self.reveal_id()
        seen = {}
        for view in render.views_of(self.spec, self.svc.catalog_for_revision(self.did, self.rev)):
            data = self.svc.images.layers(self.did, view)
            g = next((x for x in data["layers"] if x["id"] == f"surface:{rid}"), None)
            if g:
                seen[view] = g["pixels"]
        self.assertTrue(seen and max(seen.values()) > 0, f"no view shows the reveal: {seen}")
        view = max(seen, key=lambda v: seen[v])
        data = self.svc.images.layers(self.did, view)
        meta = json.loads((Path(data["dir"]) / "instances.json").read_text(encoding="utf-8"))
        self.assertTrue([i for i in meta["instances"] if i.get("surface") == rid], "the render gives the reveal its own instance")
        res = self.svc.apply(self.did, {"op": "surface-material", "surfaces": [rid], "material": "Sơn đỏ"}, None)
        spec, rev = self.svc.store.get(self.did)
        colors = render.face_colors(spec, self.svc.catalog_for_revision(self.did, rev))
        self.assertTrue(any(c.span is not None for c in colors), "the finish of a reveal is painted in its hole")
        self.assertGreater(res["rev"], self.rev)

    def test_a_pixel_gives_its_point_on_the_plan(self):
        view = "perspective"
        data = self.svc.images.layers(self.did, view, self.rev)
        d = Path(data["dir"])
        cam = render.Camera(render.views_of(self.spec, self.svc.catalog_for_revision(self.did, self.rev))[view], data["width"], data["height"])
        inst = np.array(Image.open(d / "instance.png"))
        meta = json.loads((d / "instances.json").read_text(encoding="utf-8"))
        floor = next(i for i in meta["instances"] if i["type"] == "floor")
        carcass = next(i for i in meta["instances"] if i["type"] == "carcass")
        for item, is_floor in ((floor, True), (carcass, False)):
            ys, xs = np.nonzero(inst == item["value"])
            x, y = int(xs[len(xs) // 2]), int(ys[len(ys) // 2])
            hit = self.svc.images.pick(self.did, view, x, y, self.rev)
            self.assertEqual(hit["floor"], is_floor)
            p = hit["point"]
            depth = float(np.array(Image.open(d / "depth16.png"))[y, x]) / 1000
            world = cam.unproject(np.array([x + 0.5]), np.array([y + 0.5]), np.array([depth]))[0] * 1000
            self.assertAlmostEqual(p["x"], world[0], delta=0.1)
            self.assertAlmostEqual(p["z"], world[2], delta=0.1)
            if is_floor:
                self.assertLess(abs(world[1]), 5.0, "a floor pixel lies on the floor")
        # a pixel showing nothing: the ray carried down to the floor (y = 0), projected back to the same pixel
        empty = np.argwhere(inst == 0)
        below = [(int(r), int(c)) for r, c in empty if r > cam.cy + 5][:1]
        if below:
            y, x = below[0]
            hit = self.svc.images.pick(self.did, view, x, y, self.rev)
            self.assertTrue(hit["floor"] and hit["part"] is None)
            P = np.array([[hit["point"]["x"] / 1000, 0.0, hit["point"]["z"] / 1000]])
            u, v, _ = cam.project(cam.to_camera(P))
            self.assertAlmostEqual(float(u[0]), x + 0.5, delta=0.6)
            self.assertAlmostEqual(float(v[0]), y + 0.5, delta=0.6)


if __name__ == "__main__":
    unittest.main()
