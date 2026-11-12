"""Checks of the cabinets against the room's doors and windows (rules_openings), through the service."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

TOPICS = ("doorway-width", "doorway-width-accessible", "doorway-height", "doorway-blocked", "door-interference", "cooktop-window", "window-upper")


class TestOpenings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _with_openings(self, openings):
        """A straight kitchen against a 3600 mm back wall that has ``openings``, as a new design (wall rows, not runs)."""
        did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600, "fridge": True}), "t")["id"]
        spec = self.svc.get(did)["spec"]
        spec["room"] = {"wall": [{"id": "back", "length": 3600, "openings": openings}]}
        return self.svc.create_from_spec(spec)["id"]

    def _found(self, did, country="VN"):
        return [i for i in self.svc.validate(did, None, country)["issues"] if i.get("topic") in TOPICS]

    def test_nothing_without_openings(self):
        self.assertEqual(self._found(self._with_openings([])), [])

    def test_a_door_behind_the_cabinets_is_a_warning_never_an_error(self):
        found = self._found(self._with_openings([{"type": "entrance", "fromCorner": 1000, "width": 900, "height": 2100}]))
        blocked = [i for i in found if i["topic"] == "doorway-blocked"]
        self.assertEqual(len(blocked), 1, found)
        self.assertEqual(blocked[0]["severity"], "warning")
        self.assertTrue(blocked[0]["module"])

    def test_a_narrow_door_and_the_wheelchair_level(self):
        narrow = self._found(self._with_openings([{"type": "entrance", "fromCorner": 10, "width": 700, "height": 2100}]), "US")
        self.assertIn("doorway-width", {i["topic"] for i in narrow})
        wide = self._found(self._with_openings([{"type": "entrance", "fromCorner": 10, "width": 900, "height": 2100}]), "US")
        self.assertIn("doorway-width-accessible", {i["topic"] for i in wide})        # 840 clear: over 813, under 865
        self.assertNotIn("doorway-width", {i["topic"] for i in wide})

    def test_a_window_over_the_run(self):
        did = self._with_openings([{"type": "window", "fromCorner": 0, "width": 3600, "height": 1200, "sillHeight": 1000}])
        topics = {i["topic"] for i in self._found(did)}
        self.assertTrue({"cooktop-window", "window-upper"} <= topics, topics)


if __name__ == "__main__":
    unittest.main()
