"""Run every case that has a truth file through the recogniser (recorded answers, no model) and print how far it is from the truth.

    python tools/measure_accuracy.py                         # the recorded answers of tests/data/<case>.answers.json
    python tools/measure_accuracy.py --answers-dir other/    # answers from another model / another session, same file names: A/B

Add a case: put the photo (``<case>.png``) and its answers (``<case>.answers.json``, e.g. from ``tools/jobs_to_cases.py``) in
``tests/data`` and what you measured in ``tests/data/truth/<case>.truth.json`` (see ``cabinet_recognizer.accuracy``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cabinet_recognizer.accuracy import compare  # noqa: E402
from cabinet_recognizer.pipeline import recognize_auto  # noqa: E402
from cabinet_recognizer.vision import ReplayClient  # noqa: E402

DATA = ROOT / "tests" / "data"


def run(case: str, answers_dir: Path) -> dict:
    answers = json.loads((answers_dir / f"{case}.answers.json").read_text(encoding="utf-8"))
    image = (DATA / f"{case}.png").read_bytes()
    return recognize_auto(image, ReplayClient(answers))["spec"]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers-dir", type=Path, default=DATA)
    ap.add_argument("--json", action="store_true", help="print the full reports as JSON")
    args = ap.parse_args(argv)
    reports = []
    for path in sorted((DATA / "truth").glob("*.truth.json")):
        truth = json.loads(path.read_text(encoding="utf-8"))
        case = truth["case"]
        if not (args.answers_dir / f"{case}.answers.json").exists():
            print(f"{case}: no answers in {args.answers_dir}")
            continue
        reports.append(compare(run(case, args.answers_dir), truth))
    if args.json:
        print(json.dumps(reports, indent=1, ensure_ascii=False))
    else:
        for r in reports:
            s = r["summary"]
            print(f"{r['case']:<28} edges ≤ {s['worstEdgeMm']:>6} mm ({100 * s['worstEdgeShare']:.1f}% of the run)"
                  f"   lengths ≤ {100 * s['worstLengthShare']:.1f}%   camera {r['camera'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
