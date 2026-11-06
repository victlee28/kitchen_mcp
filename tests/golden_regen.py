"""Fill in or refresh golden values. DELIBERATE, REVIEWED ACT (rule R19): run it, read the git diff of tests/golden, commit with a reason.

  python tests/golden_regen.py              fill only cases that have no expected/error yet
  python tests/golden_regen.py --all        recompute every case (use when behaviour was changed on purpose)
Never called by the test run.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_run as g  # noqa: E402


def main(argv):
    refresh = "--all" in argv
    for path in g.files():
        doc = g.load(path)
        changed = False
        for case in doc["cases"]:
            if not refresh and ("expected" in case or "error" in case):
                continue
            kind, got = g.run_case(doc["function"], case)
            case.pop("expected", None)
            case.pop("error", None)
            case["error" if kind == "error" else "expected"] = got
            changed = True
        if changed:
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print("wrote", path.relative_to(g.GOLDEN))


if __name__ == "__main__":
    main(sys.argv[1:])
