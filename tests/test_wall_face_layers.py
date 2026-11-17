"""Each wall face is a layer of its own on the layered picture: the render gives every face an instance ("<wall part>#<face>", with the
face's id), the layer catalogue a layer ``surface:<id>``; a wall part's layer still covers its faces, and a new finish for a face is the
design's own ``surface-material``."""
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

from kitchen import layers, render  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402


class TestWallFaceLayers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="faces-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        doc = json.loads((ROOT / "tests" / "data" / "floorplan-sliding-hole.json").read_text(encoding="utf-8"))
        cls.plan = cls.svc.create_from_spec(doc)["id"]
        cls.plain = cls.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "L", "backWallLength": 3600}), "t")["id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def faces_in(self, did, view):
        data = self.svc.images.layers(did, view)
        meta = json.loads((Path(data["dir"]) / "instances.json").read_text(encoding="utf-8"))
        return data, meta

    def test_a_floorplan_wall_is_split_into_its_faces(self):
        data, meta = self.faces_in(self.plan, "overhead")
        faces = [i for i in meta["instances"] if i["type"] == "wall-face"]
        self.assertGreater(len(faces), 4)
        self.assertFalse([i for i in meta["instances"] if i["type"] == "structure-wall"], "every wall pixel lies on one of its faces")
        f = faces[0]
        self.assertEqual(f["id"], f"{f['parent']}#{f['surface'].split('#')[1]}")
        group = next(x for x in data["layers"] if x["id"] == f"surface:{f['surface']}")
        self.assertEqual((group["type"], group["pixels"] >= f["pixels"]), ("wall-face", True))
        self.assertEqual(group["designEdit"], layers.say("scope.surfaces", surfaces=f["surface"]))
        wall = next(x for x in data["layers"] if x["id"] == f["parent"])
        self.assertGreaterEqual(wall["pixels"], f["pixels"], "the wall's own layer still counts its faces")

    def test_pick_mask_and_the_design_edit_of_a_face(self):
        data, meta = self.faces_in(self.plan, "overhead")
        f = max((i for i in meta["instances"] if i["type"] == "wall-face"), key=lambda i: i["pixels"])
        inst = np.array(Image.open(Path(data["dir"]) / "instance.png"))
        ys, xs = np.nonzero(inst == f["value"])
        hit = self.svc.images.pick(self.plan, "overhead", int(xs[len(xs) // 2]), int(ys[len(ys) // 2]))
        self.assertEqual((hit["part"]["surface"], hit["layers"][0]), (f["surface"], f"surface:{f['surface']}"))
        import io
        face = np.array(Image.open(io.BytesIO(self.svc.images.mask_png(self.plan, "overhead", f"surface:{f['surface']}")))) > 0
        whole = np.array(Image.open(io.BytesIO(self.svc.images.mask_png(self.plan, "overhead", f["parent"])))) > 0
        self.assertEqual(int(face.sum()), f["pixels"])
        self.assertTrue((whole | face).sum() == whole.sum() and whole.sum() >= face.sum(), "the wall's mask holds its faces")
        spec, _ = self.svc.store.get(self.plan)
        scene = render.compile_spec(spec)
        cat = layers.catalogue(spec, scene, render.wall_faces(spec, scene=scene))
        lay, _ = layers.resolve(cat, f"surface:{f['surface']}")
        op, _ = layers.design_op(spec, lay, "Sơn đen", scene)
        self.assertEqual(op, {"op": "surface-material", "surfaces": [f["surface"]], "material": "Sơn đen"})
        two = [x["id"] for x in cat if x["variant"] == "part" and x["type"] == "wall-face"][:2]
        lay2, _ = layers.resolve(cat, "parts:" + ",".join(two))
        self.assertEqual(layers.design_op(spec, lay2, "Sơn đen", scene)[0]["op"], "surface-material")

    def test_default_walls_too(self):
        data, meta = self.faces_in(self.plain, "perspective")
        faces = {i["surface"] for i in meta["instances"] if i["type"] == "wall-face"}
        self.assertTrue(faces and all(s.startswith("WALL-") for s in faces), faces)
        self.assertFalse([i for i in meta["instances"] if i["type"] == "wall"], "every default wall pixel lies on a face")


if __name__ == "__main__":
    unittest.main()
