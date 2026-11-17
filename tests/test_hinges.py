"""Cabinet door hinges from the catalog (kind ``hinge``): the design's (``common.hinge``) or a cabinet's own (``module[].hinge``), how many
per door by its height (``defaults.hinge``), carried to the three.js file and kept with each revision."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import defaults, hardware, threejs_export  # noqa: E402
from kitchen.edit import apply_op  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402

D = defaults.BUILTIN


class TestOffsets(unittest.TestCase):
    def test_count_by_height_and_even_spacing(self):
        for h, n in ((700, 2), (900, 2), (1200, 3), (1800, 4), (2200, 5), (3000, 5)):
            with self.subTest(h=h):
                off = hardware.hinge_offsets(h, D.hinge_edge, D.hinge_counts)
                self.assertEqual(len(off), n)
                self.assertAlmostEqual(off[0], 100)
                self.assertAlmostEqual(off[-1], h - 100)
                gaps = {round(b - a, 6) for a, b in zip(off, off[1:])}
                self.assertEqual(len(gaps), 1, "evenly spaced")

    def test_a_short_door_keeps_its_hinges_inside(self):
        off = hardware.hinge_offsets(200, D.hinge_edge, D.hinge_counts)
        self.assertEqual(off, [50, 150])


class TestInDesign(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "r")
        self.did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]
        self.spec = KitchenSpec.model_validate(self.svc.get(self.did)["spec"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def doors(self, spec):
        return {m["sourceRef"]: m["doors"] for m in threejs_export.export(spec)["modules"]}

    def test_the_workshop_default_then_the_design_then_the_cabinet(self):
        doors = self.doors(self.spec)
        self.assertEqual({d["hingeItem"] for ds in doors.values() for d in ds}, {D.hinge})
        self.assertEqual(doors["TD1"][0]["hingeType"]["openingAngle"], 110)
        spec = apply_op(self.spec, {"op": "common", "changes": {"hinge": "wide-165"}})
        spec = apply_op(spec, {"op": "update", "id": "TD3", "changes": {"hinge": "clip-110-inset"}})
        doors = self.doors(spec)
        self.assertEqual(doors["TD1"][0]["hingeItem"], "wide-165")
        self.assertEqual(doors["TD1"][0]["hingeType"]["openingAngle"], 165)
        self.assertEqual({d["hingeItem"] for d in doors["TD3"]}, {"clip-110-inset"})
        self.assertEqual(doors["TD3"][0]["hingeType"]["overlay"], "inset")

    def test_the_revision_keeps_the_hinges_it_uses(self):
        rev = self.svc.apply(self.did, {"op": "update", "id": "TD3", "changes": {"hinge": "clip-110-inset"}}, 1, "t")["rev"]
        kept = self.svc.store.revision_catalog(self.did, rev) or []
        self.assertIn(("hinge", "clip-110-inset"), {(i.get("kind"), i.get("id")) for i in kept})

    def test_a_command_sets_them(self):
        from kitchen.edit_intent import interpret_edit
        r = interpret_edit(self.spec, "bản lề lọt lòng", ["TD3"])
        self.assertEqual(r["operation"], {"op": "update", "id": "TD3", "changes": {"hinge": "clip-110-inset"}})
        r = interpret_edit(self.spec, "đổi bản lề giảm chấn")
        self.assertEqual(r["operation"], {"op": "common", "changes": {"hinge": "clip-110-soft"}})


if __name__ == "__main__":
    unittest.main()
