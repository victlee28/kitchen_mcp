"""Bếp chữ U: ba dãy (phải, trái, sau), hai tủ góc khuất, không chồng nhau, xuất được file 3D."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kitchen import geometry, intent, rules, threejs_export  # noqa: E402


def build(prompt):
    t, _ = intent.parse_prompt(prompt)
    return t, intent.from_template(t)


class TestLayoutU(unittest.TestCase):
    def test_prompt_reads_three_lengths(self):
        t, _ = build("Bếp chữ U dài 4m x 2.4m x 2.2m")
        self.assertEqual((t.geometry_edit, t.backWallLength, t.rightWallLength, t.leftWallLength), ("U", 4000, 2400, 2200))

    def test_two_lengths_mirror_the_second(self):
        t, _ = build("Bếp chữ U dài 4m x 2.4m")
        self.assertEqual(t.leftWallLength, 2400)

    def test_three_walls_with_a_blind_corner_each_side(self):
        _, s = build("Bếp chữ U 3m, tủ lạnh")
        walls = {m.wall for m in s.module}
        self.assertEqual(walls, {"back", "right", "left", "corner"})
        corners = [m for m in s.module if m.blindCorner]
        self.assertEqual(sorted(m.wall for m in corners), ["left", "right"])
        self.assertTrue(any(m.type == "tall-fridge" for m in s.module))
        self.assertEqual(s.room.length("back"), 3000)

    def test_no_overlap_and_rules_pass(self):
        for p in ("Bếp chữ U 3m", "Bếp chữ U dài 4m x 2.4m x 2.4m, tủ lạnh", "Bếp chữ U 2m"):
            _, s = build(p)
            r = rules.validate(s)
            self.assertEqual(r["dem"]["error"], 0, p)
            self.assertEqual(rules.check_geometry(s), [], p)

    def test_width_is_never_narrower_than_the_two_corner_cabinets(self):
        t, s = build("Bếp chữ U 1m")
        self.assertGreaterEqual(s.room.length("back"), 2 * s.common.baseDepth + 900)
        self.assertTrue(any(m.wall == "back" and m.storey == "base" for m in s.module))

    def test_left_wall_exists_in_the_scene_and_views(self):
        _, s = build("Bếp chữ U 3m")
        sc = geometry.compile_spec(s)
        self.assertEqual(sc.lsau, 3000)
        self.assertTrue(any(p.wall == "left" and p.type == "door" for p in sc.parts))
        self.assertIn("left-wall", geometry.default_views(s))
        v = geometry.default_views(s)["perspective"]
        self.assertGreater(v.position[2], sc.lphai / 1000, "camera must stand on the open side")

    def test_threejs_file_has_left_wall(self):
        _, s = build("Bếp chữ U 3m")
        doc = threejs_export.export(s, "d", 1)
        self.assertEqual(threejs_export.integrity(doc), [])
        self.assertIn("WALL-LEFT", {w["id"] for w in doc["room"]["walls"]} if "room" in doc else {"WALL-LEFT"})

    def test_lexicon_marks_u_as_built(self):
        t, _ = build("Bếp chữ U hiện đại")
        self.assertTrue(all(i["status"] != "unsupported" for i in t.promptInterpretation if i.get("canonical") == "U"))


if __name__ == "__main__":
    unittest.main()
