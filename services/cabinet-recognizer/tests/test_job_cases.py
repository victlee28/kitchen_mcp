"""Bộ kiểm từ các job hộp thư thật (tools/jobs_to_cases.py): cùng ảnh + cùng câu trả lời phải cho cùng kết quả."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from tests.replay import replay_case  # noqa: E402

CASES = sorted(p.name[:-len(".answers.json")] for p in (HERE / "data" / "jobs").glob("*.answers.json"))


class JobCasesTest(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertGreaterEqual(len(CASES), 5)

    def test_replay_matches_golden(self):
        for name in CASES:
            with self.subTest(job=name):
                case = json.loads((HERE / "data" / "jobs" / f"{name}.answers.json").read_text(encoding="utf-8"))
                golden = json.loads((HERE / "golden" / "jobs" / f"{name}.spec.json").read_text(encoding="utf-8"))
                self.assertEqual(replay_case(HERE / "data" / "jobs" / f"{name}.png", case), golden)

    def test_results_are_sane(self):
        """Bất biến không phụ thuộc giá trị vàng: tủ không chồng nhau trong một dãy/tầng, mặt bếp và tủ trên trong khoảng hợp lý."""
        for name in CASES:
            with self.subTest(job=name):
                spec = json.loads((HERE / "golden" / "jobs" / f"{name}.spec.json").read_text(encoding="utf-8"))
                self.assertTrue(820 <= spec["common"]["worktopTop"] <= 950, spec["common"]["worktopTop"])
                self.assertGreater(spec["common"]["upperBottom"], spec["common"]["worktopTop"] + 400)
                rows: dict[tuple, list] = {}
                for m in spec["modules"]:
                    if "x" in m and "upper-corner-open-shelf" != m["type"]:
                        rows.setdefault((m.get("wall", "back"), m["storey"]), []).append((m["x"], m["x"] + m["width"], m["id"]))
                for key, spans in rows.items():
                    spans.sort()
                    for a, b in zip(spans, spans[1:]):
                        if key[1] != "tall":
                            self.assertLessEqual(a[1], b[0] + 1, f"{key}: {a[2]} đè {b[2]}")


if __name__ == "__main__":
    unittest.main()
