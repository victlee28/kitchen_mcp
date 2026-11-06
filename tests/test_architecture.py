"""The portable-core rules, enforced. See CODING_STANDARDS.md ("Portable core"). Pure AST checks, no imports of the code under test."""
import glob
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import architecture_rules as rules  # noqa: E402
from architecture_allowlist import ALLOWED, ROUND_BASELINE  # noqa: E402


class TestPortableCore(unittest.TestCase):
    def test_core_modules_obey_r1_r6_r14_r16(self):
        bad = []
        for name in rules.CORE_ALL:
            for rule, detail in rules.violations(name):
                if (name, rule, detail) not in ALLOWED:
                    bad.append(f"kitchen/{name}.py: {rule} {detail}")
        self.assertFalse(bad, "Core modules must stay pure (no I/O, clock, randomness, pydantic behaviour, untyped raises, "
                              "broad except, module state; they import only core/data modules):\n  " + "\n  ".join(bad))

    def test_the_allowlist_only_shrinks(self):
        stale = [k for k in ALLOWED if k not in {(m, r, d) for m in rules.CORE_ALL for r, d in rules.violations(m)}]
        self.assertFalse(stale, f"These exceptions are no longer needed; delete them from architecture_allowlist.ALLOWED: {stale}")

    def test_every_kitchen_module_belongs_to_exactly_one_zone(self):
        on_disk = {os.path.basename(f)[:-3] for f in glob.glob(str(rules.KITCHEN / "*.py"))} - {"__init__"}
        zones = rules.ALL_ZONES
        self.assertFalse(on_disk - set(zones), f"Unclassified modules: add them to a zone in tests/architecture_rules.py: {sorted(on_disk - set(zones))}")
        self.assertFalse(set(zones) - on_disk, f"Zones name modules that do not exist: {sorted(set(zones) - on_disk)}")
        self.assertEqual(len(zones), len(set(zones)), "a module is listed in two zones")

    def test_packages_are_classified_and_the_image_package_stays_independent(self):
        import ast
        packages = {os.path.basename(os.path.dirname(f)) for f in glob.glob(str(rules.KITCHEN / "*" / "__init__.py"))}
        self.assertEqual(packages, set(rules.PIXEL_PACKAGES) | set(rules.CORE_PACKAGES), "a package under kitchen/ must be listed in a zone (PIXEL_PACKAGES or CORE_PACKAGES)")
        for pkg in rules.PIXEL_PACKAGES:
            for f in sorted((rules.KITCHEN / pkg).glob("*.py")):
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("os.environ", text, f"{f.name} reads the environment; take a Config instead")
                self.assertNotIn("getenv", text, f"{f.name} reads the environment; take a Config instead")
                for n in ast.walk(ast.parse(text)):
                    if isinstance(n, ast.ImportFrom):
                        names = {n.module or ""} | {a.name for a in n.names}
                        self.assertFalse(names & {"service", "web_server", "server"}, f"{f.name} imports the facade or an adapter")

    def test_prompt_wording_lives_only_in_the_prompts_package(self):
        for f in sorted(rules.KITCHEN.rglob("*.py")):
            rel = f.relative_to(rules.KITCHEN).as_posix()
            if rel.startswith("prompts/") or rel == "lexicon.py":
                continue
            text = f.read_text(encoding="utf-8")
            for phrase in ("photorealistic", "IMAGE 1", "Keep the exact", "keep exactly the same"):
                self.assertNotIn(phrase, text, f"{rel}: model-facing wording belongs in kitchen/prompts/")

    def test_only_the_shell_reads_the_environment(self):
        readers = [m for m in rules.ALL_ZONES if rules.env_reads(m)]
        self.assertFalse(set(readers) - set(rules.ENV_READERS), f"These modules read os.environ but are not in ENV_READERS: {sorted(set(readers) - set(rules.ENV_READERS))}")

    def test_builtin_round_does_not_spread(self):
        grew = []
        for name in rules.CORE_ALL:
            n, cap = rules.round_calls(name), ROUND_BASELINE.get(name, 0)
            if n > cap:
                grew.append(f"{name}: {n} round() calls, baseline {cap}; use numeric.round_half_away")
        self.assertFalse(grew, "\n".join(grew))
        shrank = [f"{m}: now {rules.round_calls(m)}, baseline {c}" for m, c in ROUND_BASELINE.items() if rules.round_calls(m) < c]
        self.assertFalse(shrank, "Lower ROUND_BASELINE in tests/architecture_allowlist.py (it may only go down): " + "; ".join(shrank))

    def test_the_checker_catches_what_it_claims_to(self):
        import tempfile
        old = rules.KITCHEN
        d = Path(tempfile.mkdtemp())
        (d / "bad.py").write_text(
            "import os, time, random\nfrom . import store\nimport numpy\n"
            "_CACHE = {}\n"
            "def f(spec):\n    x = open('a')\n    spec.model_dump()\n    time.time()\n"
            "    try:\n        pass\n    except Exception:\n        pass\n    raise ValueError('x')\n", encoding="utf-8")
        rules.KITCHEN = d
        try:
            got = {r for r, _ in rules.violations("bad")}
        finally:
            rules.KITCHEN = old
        self.assertEqual(got, {"R1-import", "R1-kitchen-import", "R1-call", "R6-pydantic", "R14-broad-except", "R14-untyped-raise", "R16-module-state"})


if __name__ == "__main__":
    unittest.main()
