"""The second look at a door built from a picture (proposal P4): the question, the reading of the answer, the corrections. No model."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import builtin  # noqa: E402
from kitchen.model_contract import first_json  # noqa: E402
from kitchen.prompts import photo as prompt_texts  # noqa: E402
from kitchen.recognition import opening_check  # noqa: E402
from kitchen.recognition import openings as ro  # noqa: E402

FOUR = {"kind": "door", "style": "sliding", "leaves": 4, "edgesSeen": "hole", "aspect": 1.4, "axesRatio": [0.25, 0.5, 0.75],
        "hAxesRatio": [0.86], "transomPanes": 3, "confidence": 0.9,
        "panels": [{"row": 0, "operation": "sliding"}, {"row": 0, "operation": "sliding", "handle": True},
                   {"row": 0, "operation": "sliding", "handle": True}, {"row": 0, "operation": "sliding"},
                   {"row": 1, "operation": "fixed"}, {"row": 1, "operation": "fixed"}, {"row": 1, "operation": "fixed"}]}


def seen(d=FOUR):
    return ro.read_photo({"photoOpenings": [d]})[0][0]


class TestQuestion(unittest.TestCase):
    def test_the_catalog_text_gets_what_was_built(self):
        text = prompt_texts.text("opening-check", builtin.CATALOG)
        self.assertIn("{built}", text)
        q = opening_check.question(text, seen(), "door-sliding-4-transom", "Sliding door, 4 leaves, transom")
        self.assertNotIn("{built}", q)
        self.assertIn("door-sliding-4-transom", q)
        self.assertIn("[0.25, 0.5, 0.75]", q)


class TestParse(unittest.TestCase):
    def test_a_match(self):
        c = opening_check.parse({"same": True})
        self.assertTrue(c.same)
        s = seen()
        self.assertIs(opening_check.correct(s, c), s)

    def test_not_an_answer(self):
        for bad in (None, [], {"same": "yes"}, {"corrections": {}}):
            self.assertIsNone(opening_check.parse(bad))

    def test_bad_corrections_are_dropped_one_by_one(self):
        c = opening_check.parse({"same": False, "corrections": {"style": "rolling", "leaves": 40, "transomPanes": 0, "handles": [1, "x"],
                                                                 "axesRatio": [0.5, 1.4], "hAxesRatio": [0.8]}, "notes": ["n", 3]})
        self.assertEqual((c.style, c.leaves, c.transom_panes), (None, None, None))
        self.assertEqual(c.h_axes_ratio, (0.8,))
        self.assertEqual(c.notes, ("n",))
        self.assertEqual(c.changes(), [f"{k}={v}" for k, v in (("handles", c.handles), ("axesRatio", c.axes_ratio), ("hAxesRatio", [0.8]))
                                       if v is not None])

    def test_fenced_json(self):
        self.assertEqual(first_json('```json\n{"same": true}\n```'), {"same": True})


class TestCorrect(unittest.TestCase):
    def test_handles_rewrite_the_main_row_and_keep_the_transom(self):
        out = opening_check.correct(seen(), opening_check.Correction(False, handles=(0, 3)))
        main = [p for p in out.panels if p.row == 0]
        self.assertEqual([p.handle for p in main], [True, False, False, True])
        self.assertEqual(len([p for p in out.panels if p.row == 1]), 3)

    def test_fewer_leaves_remake_the_row_and_change_the_type(self):
        out = opening_check.correct(seen(), opening_check.Correction(False, leaves=2, axes_ratio=(0.5,)))
        self.assertEqual((out.leaves, out.axes_ratio), (2, (0.5,)))
        self.assertEqual(len([p for p in out.panels if p.row == 0]), 2)
        self.assertNotEqual(ro.photo_match(out, builtin.CATALOG).type_id, ro.photo_match(seen(), builtin.CATALOG).type_id)


if __name__ == "__main__":
    unittest.main()
