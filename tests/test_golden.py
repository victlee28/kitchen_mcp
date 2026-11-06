"""Golden cases: the same JSON files will be run against the Rust implementation. See golden_run.py for the file format."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_run as g  # noqa: E402
from golden_functions import FUNCTIONS  # noqa: E402


class TestGolden(unittest.TestCase):
    def test_there_are_golden_files_and_every_function_has_one(self):
        used = {g.load(p)["function"] for p in g.files()}
        self.assertEqual(used, set(FUNCTIONS), "every golden function needs a case file, and every case file a registered function")

    def test_every_case_matches(self):
        problems = [p for path in g.files() for p in g.check(path)]
        self.assertFalse(problems, "\n" + "\n".join(problems))

    def test_cases_are_named_uniquely_and_include_edge_or_error_cases(self):
        for path in g.files():
            doc = g.load(path)
            names = [c["name"] for c in doc["cases"]]
            self.assertEqual(len(names), len(set(names)), f"{path.name}: duplicate case names")
            self.assertGreaterEqual(len(names), 2, f"{path.name}: a golden file needs at least a normal and an edge/error case")


if __name__ == "__main__":
    unittest.main()
