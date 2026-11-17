"""Which catalog opening type a door or window seen in a picture is (``recognition.opening_match``, proposal P1): scored against the
catalog's own data, so a type the workshop adds is recognised without code."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import builtin  # noqa: E402
from kitchen.catalog.model import Catalog, Item  # noqa: E402
from kitchen.recognition import opening_match as m  # noqa: E402

CAT = builtin.CATALOG


def seen(kind="door", style="swing", leaves=1, transom=False, **more):
    return m.seen_features(kind, style, leaves, transom, **more)


class TestTypeFeatures(unittest.TestCase):
    def test_read_from_the_catalog_data(self):
        f = m.type_features(CAT.data("opening-type", "door-sliding-4-transom"))
        self.assertEqual((f.kind, f.style, f.leaves, f.transom, f.transom_panes, f.handles), ("door", "sliding", 4, True, 3, (1, 2)))
        f = m.type_features(CAT.data("opening-type", "door-swing-1-transom"))
        self.assertEqual((f.style, f.leaves, f.transom, f.transom_panes), ("swing", 1, True, 1))
        self.assertEqual(m.type_features(CAT.data("opening-type", "passage")).style, "none")
        self.assertEqual((m.type_features(CAT.data("opening-type", "window-fixed")).style, m.type_features(CAT.data("opening-type", "window-fixed")).leaves),
                         ("fixed", 0))
        self.assertEqual(m.type_features(CAT.data("opening-type", "window-swing-2-top")).transom, True)


class TestBest(unittest.TestCase):
    def test_each_builtin_door_is_found_from_its_own_features(self):
        for item in CAT.all("opening-type"):
            with self.subTest(type=item.id):
                f = m.type_features(item.data)
                got = m.best(f, CAT)
                self.assertIsNotNone(got)
                assert got is not None
                self.assertEqual(got.type_id, item.id)
                self.assertTrue(got.exact)

    def test_the_dividers_tell_an_unequal_double_door(self):
        self.assertEqual(m.best(seen(leaves=2, axes_ratio=[0.74]), CAT).type_id, "door-swing-2-unequal")
        self.assertEqual(m.best(seen(leaves=2, axes_ratio=[0.51]), CAT).type_id, "door-swing-2")

    def test_the_transom_panes_tell_two_types_apart(self):
        one = copy.deepcopy(dict(CAT.data("opening-type", "door-sliding-4-transom")))
        one["leaves"] = [lf for lf in one["leaves"] if lf["operation"] != "fixed"] + [
            {"cols": [0, 4], "rows": [1, 2], "operation": "fixed", "hinge": None, "opens": None, "active": False}]
        cat = Catalog.of([*CAT.items, Item("opening-type", "door-sliding-4-one-pane", one, "workshop")])
        self.assertEqual(m.best(seen(style="sliding", leaves=4, transom=True, transom_panes=1), cat).type_id, "door-sliding-4-one-pane")
        self.assertEqual(m.best(seen(style="sliding", leaves=4, transom=True, transom_panes=3), cat).type_id, "door-sliding-4-transom")

    def test_a_type_the_workshop_adds_is_found_without_code(self):
        six = copy.deepcopy(dict(CAT.data("opening-type", "door-sliding-4")))
        six["leaves"] = [{"cols": [k, k + 1], "rows": [0, 1], "operation": "sliding", "hinge": None, "opens": None, "active": k == 2,
                          "track": 0 if k in (0, 5) else 1} for k in range(6)]
        six["axesRatio"] = [k / 6 for k in range(1, 6)]
        six.pop("handle", None)
        cat = Catalog.of([*CAT.items, Item("opening-type", "door-sliding-6", six, "workshop")])
        got = m.best(seen(style="sliding", leaves=6), cat)
        self.assertEqual((got.type_id, got.exact), ("door-sliding-6", True))
        self.assertEqual(m.note(got), [])

    def test_nothing_alike_takes_the_closest_and_says_so(self):
        got = m.best(seen(style="sliding", leaves=3), CAT)
        self.assertFalse(got.exact)
        self.assertIn(got.type_id, ("door-sliding-2", "door-sliding-4"))
        (text,) = m.note(got)
        self.assertIn("opening-type-closest", text)
        self.assertIn("3 leaves", text)

    def test_another_kind_never_fits(self):
        self.assertIsNone(m.score(seen(kind="window"), m.type_features(CAT.data("opening-type", "door-swing-1"))))
        cat = Catalog.of([i for i in CAT.items if not (i.kind == "opening-type" and i.data.get("kind") == "window")])
        self.assertIsNone(m.best(seen(kind="window", style="fixed", leaves=0), cat))


class TestPanels(unittest.TestCase):
    """The answer's ``transomPanes`` and ``panels`` (proposal P2), read by the kitchen."""

    def test_the_type_says_its_front_rail_and_handles(self):
        f = m.type_features(CAT.data("opening-type", "door-sliding-4"))
        self.assertEqual((f.fronts, f.handles), ((1, 2), (1, 2)))
        self.assertIsNone(m.type_features(CAT.data("opening-type", "door-swing-2")).fronts)

    def test_panels_of_a_picture_become_features(self):
        from kitchen.recognition import openings as ro
        panels = [{"row": 0, "operation": "sliding", "handle": h, "front": f} for h, f in ((False, False), (True, True), (True, True), (False, False))]
        panels += [{"row": 1, "operation": "fixed"}] * 3
        doc = {"photoOpenings": [{"kind": "door", "style": "sliding", "leaves": 4, "aspect": 0.83, "axesRatio": [0.24, 0.49, 0.75],
                                  "hAxesRatio": [0.86], "transomPanes": 3, "panels": panels}]}
        (seen,), _ = ro.read_photo(doc)
        f = ro.photo_features(seen)
        self.assertEqual((f.transom_panes, f.handles, f.fronts), (3, (1, 2), (1, 2)))
        got = ro.photo_match(seen, CAT)
        self.assertEqual((got.type_id, got.exact), ("door-sliding-4-transom", True))

    def test_malformed_panels_are_left_out_not_trusted(self):
        from kitchen.recognition import openings as ro
        base = {"kind": "door", "style": "sliding", "leaves": 2, "aspect": 1.3, "axesRatio": [0.5], "hAxesRatio": []}
        for bad in ([{"row": 9, "operation": "sliding"}], [{"operation": "rolling"}], "x"):
            with self.subTest(bad=bad):
                (seen,), _ = ro.read_photo({"photoOpenings": [{**base, "panels": bad, "transomPanes": "three"}]})
                self.assertEqual((seen.panels, seen.transom_panes), (None, None))


if __name__ == "__main__":
    unittest.main()
