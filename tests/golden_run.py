"""Run golden case files. Shared by test_golden.py and golden_regen.py. A case file is:

{"function": "placement.to_room", "tolerance": 1e-6,
 "cases": [{"name": "...", "input": {...}, "expected": {...}}  or  {"name": "...", "input": {...}, "error": {"kind": "...", "code": "..."}}]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from golden_compare import differences  # noqa: E402
from golden_functions import FUNCTIONS  # noqa: E402
from kitchen import errors  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden"


def files() -> list[Path]:
    return sorted(GOLDEN.rglob("*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(function: str, case: dict):
    """-> ("value", json) or ("error", {"kind", "code"})."""
    try:
        out = FUNCTIONS[function](case["input"])
    except errors.KitchenError as e:
        return "error", {"kind": e.kind, "code": e.code}
    return "value", json.loads(json.dumps(out))


def check(path: Path) -> list[str]:
    doc = load(path)
    tol = doc.get("tolerance", 1e-6)
    problems = []
    for case in doc["cases"]:
        label = f"{path.relative_to(GOLDEN)}::{case['name']}"
        kind, got = run_case(doc["function"], case)
        if "error" in case:
            problems += [f"{label}: expected error {case['error']}, got {kind} {got!r}"] if (kind, got) != ("error", case["error"]) else []
        elif "expected" not in case:
            problems.append(f"{label}: no expected value (run tests/golden_regen.py and review the diff)")
        elif kind == "error":
            problems.append(f"{label}: raised {got}")
        else:
            problems += [f"{label}: {d}" for d in differences(got, case["expected"], tol)]
    return problems
