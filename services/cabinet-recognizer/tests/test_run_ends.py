"""A run's own ends are candidate boundaries when no edge was detected there (white doors against a white wall)."""
import unittest

from cabinet_recognizer.pixels import _with_ends

BOX = {"left": 0.1, "right": 0.9, "top": 0, "bottom": 1}


class EndsTest(unittest.TestCase):
    def test_missing_ends_are_added_after_the_detected_lines(self):
        found = [(300, 5.0), (500, 4.0)]
        self.assertEqual(_with_ends(found, BOX, 1000), [(300, 5.0), (500, 4.0), (100, 0.0), (900, 0.0)])

    def test_an_end_that_was_detected_is_not_doubled(self):
        found = [(104, 5.0), (500, 4.0), (897, 3.0)]
        self.assertEqual(_with_ends(found, BOX, 1000), found)

    def test_only_the_missing_side(self):
        self.assertEqual(_with_ends([(101, 5.0)], BOX, 1000), [(101, 5.0), (900, 0.0)])


if __name__ == "__main__":
    unittest.main()
