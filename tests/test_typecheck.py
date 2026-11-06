"""R5 ratchet: static type errors in the portable core may not grow (tests/typecheck_baseline.json only shrinks).

Skipped when pyright is not installed (pip install pyright). Update the baseline with
`python tests/test_typecheck.py --write` only after fixing errors, never to hide new ones.
"""
from __future__ import annotations

import collections
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
import architecture_rules as rules  # noqa: E402

BASELINE = Path(__file__).parent / "typecheck_baseline.json"


def errors_per_file() -> dict[str, int]:
    files = [f"kitchen/{m}.py" for m in rules.CORE_MODULES]
    out = subprocess.run(["pyright", "--outputjson", *files], cwd=ROOT, capture_output=True, text=True, timeout=600)
    data = json.loads(out.stdout)
    counts = collections.Counter(Path(d["file"]).name for d in data["generalDiagnostics"] if d["severity"] == "error")
    return {f"{m}.py": counts.get(f"{m}.py", 0) for m in rules.CORE_MODULES}


@unittest.skipUnless(shutil.which("pyright"), "pyright is not installed")
class TypecheckRatchet(unittest.TestCase):
    def test_core_type_errors_do_not_grow(self):
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        now = errors_per_file()
        worse = {f: (base.get(f, 0), n) for f, n in now.items() if n > base.get(f, 0)}
        self.assertEqual(worse, {}, "new type errors in core modules (baseline, now)")
        better = {f: (base[f], n) for f, n in now.items() if n < base.get(f, 0)}
        self.assertEqual(better, {}, "fewer errors than the baseline: lower tests/typecheck_baseline.json to lock it in")


if __name__ == "__main__":
    if "--write" in sys.argv:
        BASELINE.write_text(json.dumps(errors_per_file(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        unittest.main()
