"""R5 ratchet: static type errors in the portable core may not grow.

Two baselines, both only shrink: tests/typecheck_baseline.json (pyright as configured in pyproject.toml, all zero) and
tests/typecheck_strict_baseline.json (the same files in strict mode, tests/pyright_strict.json): the road to a core whose
every value has a known type, which is what a Rust port needs. Skipped when pyright is not installed (pip install pyright).
Update the baselines with `python tests/test_typecheck.py --write` only after fixing errors, never to hide new ones.
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
STRICT_BASELINE = Path(__file__).parent / "typecheck_strict_baseline.json"
STRICT_CONFIG = Path(__file__).parent / "pyright_strict.json"


def checked_files() -> list[str]:
    """Core modules plus every module of the image-job package (``images/``), as paths relative to ``kitchen/``."""
    core = [rules.module_path(m).relative_to(rules.KITCHEN).as_posix() for m in rules.CORE_ALL]
    return core + sorted(f"images/{p.name}" for p in (ROOT / "kitchen" / "images").glob("*.py"))


def errors_per_file(strict: bool = False) -> dict[str, int]:
    names = checked_files()
    config = ["-p", str(STRICT_CONFIG)] if strict else []
    out = subprocess.run(["pyright", *config, "--outputjson", *[f"kitchen/{n}" for n in names]], cwd=ROOT, capture_output=True, text=True, timeout=900)
    data = json.loads(out.stdout)
    counts = collections.Counter(Path(d["file"]).resolve().relative_to(ROOT / "kitchen").as_posix()
                                 for d in data["generalDiagnostics"] if d["severity"] == "error")
    return {n: counts.get(n, 0) for n in names}


@unittest.skipUnless(shutil.which("pyright"), "pyright is not installed")
class TypecheckRatchet(unittest.TestCase):
    def test_core_type_errors_do_not_grow(self):
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        now = errors_per_file()
        worse = {f: (base.get(f, 0), n) for f, n in now.items() if n > base.get(f, 0)}
        self.assertEqual(worse, {}, "new type errors in core modules (baseline, now)")
        better = {f: (base[f], n) for f, n in now.items() if n < base.get(f, 0)}
        self.assertEqual(better, {}, "fewer errors than the baseline: lower tests/typecheck_baseline.json to lock it in")

    def test_strict_errors_only_shrink(self):
        base = json.loads(STRICT_BASELINE.read_text(encoding="utf-8"))
        now = errors_per_file(strict=True)
        worse = {f: (base.get(f, 0), n) for f, n in now.items() if n > base.get(f, 0)}
        self.assertEqual(worse, {}, "new strict-mode type errors in core modules (baseline, now)")
        better = {f: (base[f], n) for f, n in now.items() if n < base.get(f, 0)}
        self.assertEqual(better, {}, "fewer strict errors than the baseline: run `python tests/test_typecheck.py --write` to lock it in")


    def test_whole_package_has_no_basic_errors(self):
        """The shell too (service, intent, store, web_server...): pyright as configured in pyproject.toml finds nothing (0 since 11/11/2026)."""
        out = subprocess.run(["pyright", "--outputjson", "kitchen", "web_server.py"], cwd=ROOT, capture_output=True, text=True, timeout=600)
        found = [f"{Path(d['file']).name}:{d['range']['start']['line'] + 1} {d['message'].splitlines()[0]}"
                 for d in json.loads(out.stdout)["generalDiagnostics"] if d["severity"] == "error"]
        self.assertEqual(found, [])


if __name__ == "__main__":
    if "--write" in sys.argv:
        BASELINE.write_text(json.dumps(errors_per_file(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        STRICT_BASELINE.write_text(json.dumps(errors_per_file(strict=True), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        unittest.main()
