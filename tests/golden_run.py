"""Run golden case files. Shared by test_golden.py and golden_regen.py. A case file is:

{"function": "placement.to_room", "tolerance": 1e-6,
 "cases": [{"name": "...", "input": {...}, "expected": {...}}  or  {"name": "...", "input": {...}, "error": {"kind": "...", "code": "..."}}]}
"""
from __future__ import annotations

import json

from pydantic import ValidationError
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
    except ValidationError:                     # the spec's schema refused the data (the boundary check; web_server answers 400)
        return "error", {"kind": "validation", "code": "schema"}
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


def public_core_functions() -> list[tuple[str, str]]:
    """(module, function) for every public top-level function of the portable core (``architecture_rules.CORE_ALL``)."""
    import ast
    import architecture_rules as rules
    out: list[tuple[str, str]] = []
    for m in rules.CORE_ALL:
        tree = ast.parse(rules.module_path(m).read_text(encoding="utf-8"))
        out += [(m, n.name) for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
    return out


def unpinned() -> set[str]:
    """``module.function`` of the public core functions that no golden case runs (directly or through the function a case calls):
    their behaviour is not pinned for the Rust port (rule R19). Measured by tracing the calls made while every case runs."""
    import architecture_rules as rules
    root = str(rules.KITCHEN.resolve())
    called: set[tuple[str, str]] = set()

    def trace(frame, event, _arg):
        if event == "call" and frame.f_code.co_filename.startswith(root):
            called.add((str(Path(frame.f_code.co_filename).resolve()), frame.f_code.co_name))

    old = sys.getprofile()
    sys.setprofile(trace)
    try:
        for path in files():
            doc = load(path)
            for case in doc["cases"]:
                run_case(doc["function"], case)
    finally:
        sys.setprofile(old)
    return {f"{m}.{f}" for m, f in public_core_functions() if (str(rules.module_path(m).resolve()), f) not in called}


def unpinned_fresh() -> set[str]:
    """``unpinned`` measured in a new interpreter: memo caches (``Catalog.derived``, cached lookups) warmed by earlier tests would hide calls."""
    import subprocess
    out = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--unpinned"], capture_output=True, text=True, timeout=600,
                         cwd=str(Path(__file__).resolve().parent.parent))
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-2000:])
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


if __name__ == "__main__" and "--unpinned" in sys.argv:
    print(json.dumps(sorted(unpinned())))
