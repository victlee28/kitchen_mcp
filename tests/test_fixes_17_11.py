"""Fixes of 17/11/2026: a view's prompt tells of what its picture shows (the wine cabinet's view is not told of the TV unit, the window
or the kitchen's LEDs); the views see a run out to its ends; a fridge cabinet laid on an object is deep enough for its fridge; cabinets
laid by a template stand on the design's levels; interpret_edit over MCP takes the picked wall faces."""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import camera_plan, cabinet_run, prompts  # noqa: E402
from kitchen.spec import KitchenSpec  # noqa: E402


def _design() -> KitchenSpec:
    """A kitchen run (with wall cabinets), a TV unit and a wine cabinet, and a window."""
    return KitchenSpec.model_validate({
        "runs": [{"id": "R1", "x": 0, "z": 0, "yaw": 0, "purpose": "tv", "tvLayout": "columns"},
                 {"id": "R2", "x": 0, "z": 3000, "yaw": 0},
                 {"id": "R3", "x": 0, "z": 6000, "yaw": 0, "purpose": "unit", "unitLayout": "wine"}],
        "common": {"material": {"countertop": "Đá trắng", "wallTile": "Gạch trắng"}},
        "module": [{"id": "TD1", "type": "base", "wall": "island", "run": "R1", "fromCorner": 0, "width": 1800, "height": 450, "depth": 400},
                   {"id": "TD2", "type": "base", "wall": "island", "run": "R2", "fromCorner": 0, "width": 600, "height": 840, "depth": 580},
                   {"id": "TT2", "type": "upper", "wall": "island", "run": "R2", "fromCorner": 0, "width": 600, "y": 1530, "height": 750, "depth": 320},
                   {"id": "TD3", "type": "base", "wall": "island", "run": "R3", "fromCorner": 0, "width": 900, "height": 840, "depth": 400},
                   {"id": "TT3", "type": "upper-glass", "wall": "island", "run": "R3", "fromCorner": 0, "width": 900, "y": 1350, "height": 1260,
                    "depth": 300}],
        "openings": [{"id": "OP1", "kind": "window", "openingType": "window-swing-2", "wallAxis": {"id": "W", "start": [0, 0], "dir": [1, 0],
                                                                                                   "length": 4000}, "center": 2000, "width": 1200,
                      "sill": 900, "height": 1200}]})


def _seen(*modules: str) -> prompts.Seen:
    return prompts.seen_in({"width": 100, "height": 100, "instances": [{"module": m, "type": "door", "pixels": 500} for m in modules]})


class TestPromptOfTheView(unittest.TestCase):
    def test_the_wine_cabinet_view_tells_of_the_wine_cabinet_only(self):
        spec = _design()
        scene = prompts.global_prompt(spec, seen=_seen("TD3", "TT3"))
        self.assertIn("wine cabinet", scene)
        self.assertNotIn("TV", scene)
        self.assertNotIn("kitchen", scene)
        self.assertNotIn("countertop", scene)
        photo = prompts.full(spec, "daylight", seen=_seen("TD3", "TT3"))
        self.assertNotIn("LED", photo)
        self.assertNotIn("window", photo)
        self.assertNotIn("countertop", photo)

    def test_the_kitchen_view_keeps_its_worktop_led_and_window(self):
        spec = _design()
        scene = prompts.global_prompt(spec, seen=_seen("TD2", "TT2", "OP1"))
        self.assertIn("kitchen", scene)
        self.assertNotIn("TV", scene)
        photo = prompts.full(spec, "daylight", seen=_seen("TD2", "TT2", "OP1"))
        self.assertIn("LED strip", photo)
        self.assertIn("through the window", photo)
        self.assertIn("countertop overhang", photo)

    def test_without_a_view_the_whole_design_is_told(self):
        scene = prompts.global_prompt(_design())
        self.assertIn("TV wall unit", scene)
        self.assertIn("wine cabinet", scene)

    def test_slivers_at_the_edge_of_the_picture_are_not_told(self):
        seen = prompts.seen_in({"width": 1000, "height": 1000, "instances": [{"module": "TD1", "type": "door", "pixels": 100},
                                                                             {"module": "TD3", "type": "door", "pixels": 90000}]})
        assert seen is not None
        self.assertEqual(seen.modules, frozenset({"TD3"}))


class TestRunEndsSeen(unittest.TestCase):
    def test_the_targets_reach_the_ends_and_the_top_of_the_run(self):
        face = camera_plan.Face("f", "f", (0.0, 0.0), (0.0, 1.0), 3000.0, 2400.0)
        xs = [t[0] for t in camera_plan.face_targets(face)]
        ys = [t[1] for t in camera_plan.face_targets(face)]
        self.assertGreater(max(xs), 1400.0)
        self.assertLess(min(xs), -1400.0)
        self.assertGreater(max(ys), 2200.0)

    def test_a_column_hiding_only_an_end_of_the_run_is_in_the_way(self):
        face = camera_plan.Face("f", "f", (0.0, 0.0), (0.0, 1.0), 3000.0, 2400.0)
        column = camera_plan.Obstacle("col", "column", ((680.0, 950.0), (760.0, 950.0), (760.0, 1050.0), (680.0, 1050.0)), 0.0, 2700.0)
        self.assertEqual(camera_plan.blockers((0.0, 1500.0, 2000.0), camera_plan.face_targets(face), [column]), ["col"])


class TestLaidOnAnObject(unittest.TestCase):
    def test_a_fridge_cabinet_is_never_shallower_than_its_fridge(self):
        tall = {"type": "tall-fridge", "width": 700.0, "s": 0.0, "y": 0.0, "height": 2200.0, "depth": 640.0,
                "appliances": [{"type": "fridge", "name": "Tủ lạnh", "dimensions": "600 × 1850 × 620"}]}
        base = {"type": "base", "width": 600.0, "s": 700.0, "y": 0.0, "height": 840.0, "depth": 580.0}
        fridge, other = cabinet_run.fit_depth([tall, base], 594.0)
        self.assertEqual(fridge["depth"], 650.0)
        self.assertEqual(other["depth"], 594.0)

    def test_template_cabinets_take_the_designs_levels(self):
        spec = KitchenSpec.model_validate({"module": []})
        c = spec.common
        laid = [{"type": "upper", "width": 600.0, "s": 0.0, "y": 1500.0, "height": 700.0, "depth": 320.0},
                {"type": "upper-hood", "width": 600.0, "s": 600.0, "y": 1715.0, "height": 485.0, "depth": 320.0},
                {"type": "tall-fridge", "width": 700.0, "s": 1200.0, "y": 0.0, "height": 2200.0, "depth": 650.0},
                {"type": "base", "width": 600.0, "s": 1900.0, "y": 0.0, "height": 840.0, "depth": 580.0}]
        upper, hood, tall, base = cabinet_run.fit_levels(laid, spec)
        self.assertEqual((upper["y"], upper["y"] + upper["height"]), (c.upperBottom, c.upperTierSplit))
        self.assertEqual((hood["height"], hood["y"] + hood["height"]), (485.0, c.upperTierSplit))
        self.assertEqual(tall["y"] + tall["height"], c.cabinetTop)
        self.assertEqual(base["height"], c.baseTop)


class TestInterpretTakesFaces(unittest.TestCase):
    def test_the_mcp_tool_passes_the_picked_wall_faces_on(self):
        import server
        self.assertIn("surfaces", inspect.signature(server.interpret_edit).parameters)


if __name__ == "__main__":
    unittest.main()
