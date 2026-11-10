"""Every axis-aligned row of cabinets (a wall's, a legacy free run's) is placed through ONE thing, ``runs.Seat``; its numbers are those the
wall-keyed formulas gave (written out here once, literally), so stored geometry and render keys do not move."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import geometry, runs, threejs_export  # noqa: E402
from kitchen.spec import KitchenSpec, Module  # noqa: E402

S0, S1, D0, D1, Y0, Y1 = 300.0, 900.0, 20.0, 580.0, 100.0, 840.0
LSAU, POS, DEPTH = 3600.0, 2100.0, 600.0

OLD = {   # (wall, facing) -> (min, max) as geometry._Builder.box computed them before Seat
    ("back", None): ((-S1, Y0, D0), (-S0, Y1, D1)),
    ("right", None): ((-D1, Y0, S0), (-D0, Y1, S1)),
    ("left", None): ((-LSAU + D0, Y0, S0), (-LSAU + D1, Y1, S1)),
    ("island", "-z"): ((-S1, Y0, POS + DEPTH - D1), (-S0, Y1, POS + DEPTH - D0)),
    ("island", "+z"): ((-S1, Y0, POS - DEPTH + D0), (-S0, Y1, POS - DEPTH + D1)),
    ("island", "-x"): ((-POS + DEPTH - D1, Y0, S0), (-POS + DEPTH - D0, Y1, S1)),
    ("island", "+x"): ((-POS - DEPTH + D0, Y0, S0), (-POS - DEPTH + D1, Y1, S1)),
}
OLD_FRAME = {   # (wall, facing) -> (anchor x, anchor z, yaw) as threejs_export._module_frame computed them (fromCorner = S0, width = S1 - S0)
    ("back", None): (-S1, 0, 0.0), ("right", None): (0, S0, -90.0), ("left", None): (-LSAU, S1, 90.0),
    ("island", "-z"): (-S0, POS + DEPTH, 180.0), ("island", "+z"): (-S1, POS - DEPTH, 0.0),
    ("island", "-x"): (-POS + DEPTH, S0, -90.0), ("island", "+x"): (-POS - DEPTH, S1, 90.0),
}
FRONT = {("back", None): "back", ("right", None): "right", ("left", None): "left", ("island", "-z"): "island", ("island", "+z"): "back",
         ("island", "-x"): "right", ("island", "+x"): "left"}


def seat(wall, facing):
    return runs.free_seat(POS, DEPTH, facing) if wall == "island" else runs.wall_seat(wall, LSAU)


class TestSeat(unittest.TestCase):
    def test_boxes_are_bit_for_bit_the_old_wall_formulas(self):
        for key, want in OLD.items():
            with self.subTest(seat=key):
                got = seat(*key).box(S0, S1, D0, D1, Y0, Y1)
                self.assertEqual(repr(got), repr(want))
                self.assertEqual(seat(*key).front, FRONT[key])

    def test_a_zero_stays_the_zero_it_was(self):
        self.assertEqual(repr(runs.wall_seat("back", LSAU).box(0.0, 600.0, 0.0, 600.0, 0.0, 840.0)), repr(((-600.0, 0.0, 0.0), (-0.0, 840.0, 600.0))))
        self.assertEqual(repr(runs.wall_seat("back", LSAU).box(0, 600, 0, 600, 0, 840)), repr(((-600, 0, 0), (0, 840, 600))))

    def test_the_door_normal_points_from_the_back_of_the_cabinet_to_its_front(self):
        for key in OLD:
            with self.subTest(seat=key):
                s = seat(*key)
                (ax, az), (bx, bz) = s.to_world(S0, 0.0), s.to_world(S0, 1.0)
                self.assertEqual((bx - ax, bz - az), s.normal())

    def test_a_front_seen_from_the_front_and_back_again(self):
        for key in OLD:
            with self.subTest(seat=key):
                s = seat(*key)
                mn, mx = s.box(S0, S1, D1 - 18.0, D1, Y0, Y1)             # a door on the front of the row
                u0, u1, f = runs.front_span(s.front, mn, mx)
                self.assertEqual(u1 - u0, S1 - S0)
                hmn, hmx = runs.front_box(s.front, u0 + 50.0, u0 + 62.0, Y0 + 10.0, Y0 + 138.0, f, 30.0)   # a handle on it
                nx, nz = s.normal()
                out = (hmn[0] + hmx[0]) / 2 - (mn[0] + mx[0]) / 2, (hmn[2] + hmx[2]) / 2 - (mn[2] + mx[2]) / 2
                self.assertGreater(out[0] * nx + out[1] * nz, 0, "the handle stands proud of the door, on the room side")
                self.assertTrue(mn[0] <= hmn[0] <= hmx[0] <= mx[0] or mn[2] <= hmn[2] <= hmx[2] <= mx[2], "and within the door's width")

    def test_exporter_anchor_is_the_back_left_corner_seen_from_the_front(self):
        for (wall, facing), (x, z, yaw) in OLD_FRAME.items():
            with self.subTest(seat=(wall, facing)):
                m = Module(id="M1", type="base", wall=wall, fromCorner=S0, width=S1 - S0, y=0, height=840, depth=DEPTH, offset=POS, facing=facing)
                frame, size = threejs_export._module_frame(m, LSAU)
                self.assertEqual(repr((frame.pos[0], frame.pos[2], frame.rot)), repr((x, z, yaw)))
                self.assertEqual(size, (S1 - S0, 840, DEPTH))

    def test_only_explicit_runs_have_no_seat(self):
        self.assertIsNone(runs.seat_of(Module(id="M1", type="base", wall="island", run="R1", fromCorner=0, width=600, y=0, height=840, depth=600), LSAU))
        self.assertIsNone(runs.wall_seat("attic", LSAU))

    def test_geometry_has_no_wall_keyed_placement_left(self):
        src = (ROOT / "kitchen" / "geometry.py").read_text(encoding="utf-8")
        body = src[src.index("    def box("):src.index("    def wall_behind(")] + src[src.index("    def _local("):src.index("    def build(")]
        for word in ('"back"', '"right"', '"left"', "facing =="):
            self.assertNotIn(word, body, f"box / handle must place through a seat or a run frame, not by {word}")

    def test_a_kitchen_on_every_seat_compiles(self):
        mods = [{"id": f"M{i}", "type": "base", "wall": w, "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 600, **({"offset": 2400, "facing": f} if f else {})}
                for i, (w, f) in enumerate(OLD)]
        scene = geometry.compile_spec(KitchenSpec.model_validate({"module": mods}))
        self.assertEqual(sum(1 for p in scene.parts if p.type == "handle"), sum(1 for p in scene.parts if p.type in ("door", "glass-door", "drawer")))


if __name__ == "__main__":
    unittest.main()
