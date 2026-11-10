import ast
import copy
import json
import unittest
from pathlib import Path

from cabinet_recognizer import compute, contract, pipeline
from cabinet_recognizer.errors import RecognizerError
from cabinet_recognizer.numeric import round_half_away, snap
from cabinet_recognizer.vision import ReplayClient

HERE = Path(__file__).parent
IMAGE = (HERE / "data" / "bep-chu-I-xam.png").read_bytes()
ANSWERS = json.loads((HERE / "data" / "bep-chu-I-xam.answers.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((HERE / "golden" / "bep-chu-I-xam.spec.json").read_text(encoding="utf-8"))

CORE = ["errors", "numeric", "contract", "compute", "prompts", "labels_vi", "persp", "contract_persp", "compute_persp", "to_kitchen", "to_runs"]
CORE_ALLOWED = {"__future__", "math", "dataclasses", "typing", "enum", "re", "json", "collections"}


class SequenceClient:
    """Trả lần lượt các câu trả lời cho mỗi bước (để thử hỏi lại)."""

    def __init__(self, answers):
        self.answers = {k: list(v) if isinstance(v, list) else [v] for k, v in answers.items()}
        self.calls = []

    def complete(self, step, prompt, images):
        self.calls.append(step)
        seq = self.answers[step]
        a = seq.pop(0) if len(seq) > 1 else seq[0]
        return a if isinstance(a, str) else json.dumps(a)


class PipelineTest(unittest.TestCase):
    def test_sample_matches_golden(self):
        client = ReplayClient(ANSWERS)
        spec = pipeline.recognize(IMAGE, client)["spec"]
        self.assertEqual(client.calls, ["layout", "segmentation", "policy"])
        self.assertEqual(spec, GOLDEN)

    def test_widths_sum_to_run(self):
        spec = GOLDEN
        for band in ("upper", "base"):
            mods = [m for m in spec["modules"] if m["storey"] == band]
            self.assertEqual(sum(m["width"] for m in mods), spec["common"]["runLength"])
            for m in mods:
                if "doors" in m:
                    self.assertEqual(sum(m["doors"]), m["width"])

    def test_retry_once_on_invalid_answer(self):
        bad = copy.deepcopy(ANSWERS["segmentation"])
        bad["upper"]["boundaries"] = ["U1", "U99"]
        client = SequenceClient({**ANSWERS, "segmentation": [bad, ANSWERS["segmentation"]]})
        spec = pipeline.recognize(IMAGE, client)["spec"]
        self.assertEqual(client.calls, ["layout", "segmentation", "segmentation", "policy"])
        self.assertEqual(spec, GOLDEN)

    def test_gives_up_after_retries(self):
        bad = copy.deepcopy(ANSWERS["segmentation"])
        bad["base"]["modules"][0]["type"] = "cupboard"
        client = SequenceClient({**ANSWERS, "segmentation": bad})
        with self.assertRaises(RecognizerError) as cm:
            pipeline.recognize(IMAGE, client)
        self.assertEqual(cm.exception.kind, "validation")
        self.assertEqual(cm.exception.code, "segmentation-unknown-enum")


class ContractTest(unittest.TestCase):
    def test_layout_rejects_non_straight(self):
        with self.assertRaises(RecognizerError):
            contract.parse_layout({**ANSWERS["layout"], "layout": "l-shape"})

    def test_extract_json_from_markdown(self):
        self.assertEqual(contract.extract_json('ok ```json\n{"a": "}"}\n```'), {"a": "}"})

    def test_door_split_must_be_inside_module(self):
        measure = {"vlines": {"upper": [{"id": "U1", "pos": 0}, {"id": "U2", "pos": 10}, {"id": "U3", "pos": 20}],
                              "base": [{"id": "B1", "pos": 0}, {"id": "B2", "pos": 20}]},
                   "hlines": [{"id": f"H{i}", "pos": i * 10} for i in range(1, 8)]}
        seg = {"rows": {k: f"H{i + 1}" for i, k in enumerate(contract.ROW_KEYS)},
               "upper": {"boundaries": ["U1", "U2"], "modules": [
                   {"type": "upper", "doors": 2, "doorSplits": ["U3"]}]},
               "base": {"boundaries": ["B1", "B2"], "modules": [{"type": "base", "doors": 1}]}}
        with self.assertRaises(RecognizerError) as cm:
            contract.parse_segmentation(seg, measure)
        self.assertEqual(cm.exception.code, "bad-split")


class NumericTest(unittest.TestCase):
    def test_round_half_away(self):
        self.assertEqual(round_half_away(2.5), 3)
        self.assertEqual(round_half_away(-2.5), -3)
        self.assertEqual(round_half_away(2905, 50), 2900)
        self.assertEqual(round_half_away(2925, 50), 2950)

    def test_snap(self):
        self.assertEqual(snap(828, [700, 750, 800, 900], 60), (800, True))
        self.assertEqual(snap(1000, [700, 800], 60), (1000, False))

    def test_split_near_equal(self):
        self.assertEqual(compute._split(810, [0.49, 0.51], 10), [405, 405])
        self.assertEqual(compute._split(800, [0.3, 0.7], 10), [240, 560])


class ArchitectureTest(unittest.TestCase):
    def test_core_imports_stdlib_only(self):
        pkg = HERE.parent / "cabinet_recognizer"
        for name in CORE:
            tree = ast.parse((pkg / f"{name}.py").read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mods = [(node.module or "").split(".")[0]]
                else:
                    continue
                for m in mods:
                    self.assertIn(m, CORE_ALLOWED, f"{name}.py import {m}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "round":
                    self.fail(f"{name}.py dùng round() trần")


if __name__ == "__main__":
    unittest.main()


class ToKitchenTest(unittest.TestCase):
    def _conv(self, name):
        from cabinet_recognizer.to_kitchen import corner_check, to_kitchen_spec
        rec = json.loads((HERE / "golden" / f"{name}.spec.json").read_text(encoding="utf-8"))
        out = to_kitchen_spec(rec)
        self.assertEqual(corner_check(out["spec"]), [])
        return rec, out

    def test_back_run_measured_from_right_corner(self):
        rec, out = self._conv("bep-chu-I-xam")
        L = rec["common"]["runLength"]
        src = {m["id"]: m for m in rec["modules"]}
        for m in out["spec"]["module"]:
            s = src[m["id"]]
            self.assertEqual(m["fromCorner"], L - s["x"] - s["width"])
        self.assertIn("module", out["spec"])
        self.assertNotIn("modules", out["spec"])

    def test_left_corner_blind_moves_to_left_run(self):
        _, out = self._conv("bep-chu-L-trang")
        mods = {m["id"]: m for m in out["spec"]["module"]}
        self.assertEqual(mods["TD6"]["fromCorner"], 0)
        self.assertEqual(mods["TD6"]["blindCorner"], 620)
        self.assertEqual(mods["TD1"]["fromCorner"] + mods["TD1"]["width"], 4850 - 600)
        self.assertIn("KG1a", mods)
        self.assertEqual(mods["KG1a"]["type"], "upper-open")

    def test_right_corner_blind_stays(self):
        _, out = self._conv("u-frontal-render")
        mods = {m["id"]: m for m in out["spec"]["module"]}
        self.assertEqual(mods["TD5"]["fromCorner"], 0)
        self.assertGreater(mods["TD5"]["blindCorner"], 0)
        self.assertEqual(mods["TC1"]["niche"], 1880)
