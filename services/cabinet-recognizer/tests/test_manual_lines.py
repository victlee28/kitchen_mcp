"""A boundary written x<fraction> is a candidate line of its own: edge detection misses same-coloured door seams."""
import unittest

from cabinet_recognizer.contract import add_manual_lines


def measure():
    return {"imageSize": [1000, 800], "vlines": {"upper": [{"id": "U1", "pos": 100, "strength": 5.0}, {"id": "U2", "pos": 900, "strength": 5.0}],
                                                 "base": [{"id": "B1", "pos": 100, "strength": 5.0}, {"id": "B2", "pos": 900, "strength": 5.0}]}}


class ManualLineTest(unittest.TestCase):
    def test_a_boundary_is_added_to_its_band_in_order(self):
        m = measure()
        add_manual_lines({"base": {"boundaries": ["B1", "x0.412", "B2"], "modules": []}}, m)
        self.assertEqual([(ln["id"], ln["pos"]) for ln in m["vlines"]["base"]], [("B1", 100), ("x0.412", 412), ("B2", 900)])
        self.assertEqual(len(m["vlines"]["upper"]), 2)

    def test_a_door_split_counts_too_and_nothing_is_doubled(self):
        m = measure()
        data = {"upper": {"boundaries": ["U1", "U2"], "modules": [{"doorSplits": ["x.5", "x.5", "U1"]}]}}
        add_manual_lines(data, m)
        self.assertEqual([ln["id"] for ln in m["vlines"]["upper"]], ["U1", "x.5", "U2"])
        self.assertEqual(m["vlines"]["upper"][1]["pos"], 500)

    def test_other_strings_are_not_lines(self):
        m = measure()
        add_manual_lines({"base": {"boundaries": ["B1", "foo", "B2"], "modules": []}}, m)
        self.assertEqual(len(m["vlines"]["base"]), 2)


if __name__ == "__main__":
    unittest.main()
