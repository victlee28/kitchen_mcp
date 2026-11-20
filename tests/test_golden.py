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

    def test_every_public_core_function_is_pinned(self):
        """R19: a golden case runs every public function of the portable core, so a Rust port can be checked against it. The ones
        still unpinned are listed in tests/golden_unpinned.json; THAT LIST MAY ONLY SHRINK (a new public core function needs a case)."""
        import json
        base = set(json.loads((Path(__file__).resolve().parent / "golden_unpinned.json").read_text(encoding="utf-8")))
        now = g.unpinned_fresh()
        self.assertFalse(sorted(now - base), "public core functions no golden case runs: add a case in tests/golden/ (golden_functions.py)")
        self.assertFalse(sorted(base - now), "now pinned: remove them from tests/golden_unpinned.json")


if __name__ == "__main__":
    unittest.main()
