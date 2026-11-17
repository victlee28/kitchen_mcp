"""Measure how well doors and windows are recognised, on the answered jobs of tests/data/openings/cases.json (proposal P5).

    python tools/measure_openings.py            # table + totals
    python tools/measure_openings.py --json out.json
    python tools/measure_openings.py --live     # ask the real vision model of RECOG_PROVIDER / RECOG_API_KEY instead of the kept answers

Each case is replayed through cabinet-recognizer with the answers kept for it (services/cabinet-recognizer/tests/data/<case>.answers.json,
plus <openings> when the case names a separate file), then through the kitchen's reading (``recognition.openings``) and type choice
(``recognition.opening_match``). Every opening the case expects is compared: the catalog type, the kind of leaves and how many, the
dividers (largest error as a fraction of the opening), the transom panes and the leaves with a handle when the case says them.
No model and no network: the answers are the ones given when the job was answered.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "cabinet-recognizer"
DATA = SERVICE / "tests" / "data"
CASES = ROOT / "tests" / "data" / "openings" / "cases.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVICE))


def live_client() -> Any:
    """The recognizer's own vision client from its environment (RECOG_PROVIDER, RECOG_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY);
    None when no key is set (a local ollama needs none)."""
    from cabinet_recognizer.config import Config
    from cabinet_recognizer.vision import make_client
    config = Config.from_env()
    if not config.api_key and config.provider != "ollama":
        return None
    return make_client(config)


def replay(case: dict[str, Any], client: Any = None) -> dict[str, Any]:
    """The recognizer's ``recognized-runs/1`` document for a case: from the kept answers, or asked again of ``client`` (a live model)."""
    from cabinet_recognizer.pipeline import recognize_auto
    from cabinet_recognizer.to_runs import to_runs
    from cabinet_recognizer.vision import ReplayClient
    name = case["case"]
    if client is None:
        answers = json.loads((DATA / f"{name}.answers.json").read_text(encoding="utf-8"))
        if case.get("openings"):
            answers["openings"] = json.loads((DATA / case["openings"]).read_text(encoding="utf-8"))
        client = ReplayClient(answers)
    spec = recognize_auto((DATA / f"{name}.png").read_bytes(), client)["spec"]
    return to_runs(spec)


def seen_of(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """What the kitchen reads from the document: each opening's run (``photo`` for a picture with no cabinets), the type it picks and
    the features it saw."""
    from kitchen import builtin
    from kitchen.recognition import opening_match
    from kitchen.recognition import openings as ro
    out: list[dict[str, Any]] = []
    photos, _ = ro.read_photo(doc)
    for p in photos:
        m = ro.photo_match(p, builtin.CATALOG)
        out.append({"run": "photo", "kind": p.kind, "type": m.type_id, "features": m.seen, "axesRatio": list(p.axes_ratio),
                    "hAxesRatio": list(p.h_axes_ratio), "exact": m.exact})
    seen, _ = ro.read(doc)
    for o in seen:
        f = ro.features_of(o)
        m = opening_match.best(f, builtin.CATALOG)
        out.append({"run": o.run, "kind": o.kind, "type": m.type_id if m else None, "features": f, "axesRatio": list(f.axes_ratio or ()),
                    "hAxesRatio": [], "exact": bool(m and m.exact)})
    return out


def _err(want: list[float], got: list[float]) -> float | None:
    if len(want) != len(got):
        return None
    return max((abs(a - b) for a, b in zip(sorted(want), sorted(got))), default=0.0)


def compare(expect: dict[str, Any], got: dict[str, Any] | None) -> dict[str, Any]:
    """One expected opening against what was read (None: nothing read for it)."""
    if got is None:
        return {"found": False, "typeRight": False}
    f = got["features"]
    row: dict[str, Any] = {"found": True, "type": got["type"], "typeRight": got["type"] == expect["type"],
                           "leavesRight": f.style == expect.get("style", f.style) and f.leaves == expect.get("leaves", f.leaves)}
    if "axesRatio" in expect and got["axesRatio"] is not None:
        e = _err(expect["axesRatio"], got["axesRatio"])
        row["axesErr"] = "count" if e is None else round(e, 3)
    if "hAxesRatio" in expect and got["run"] == "photo":
        e = _err(expect["hAxesRatio"], got["hAxesRatio"])
        row["hAxesErr"] = "count" if e is None else round(e, 3)
    if "transomPanes" in expect:
        row["transomPanesRight"] = f.transom_panes == expect["transomPanes"] if f.transom_panes is not None else None
    if "handles" in expect:
        row["handlesRight"] = (sorted(f.handles) == sorted(expect["handles"])) if f.handles is not None else None
    return row


def measure(cases: list[dict[str, Any]], client: Any = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        try:
            read = seen_of(replay(case, client))
        except Exception as e:      # a replay that fails counts every opening of the case as not found
            read = []
            print(f"  {case['case']}: replay failed: {e}", file=sys.stderr)
        left = list(read)
        for i, want in enumerate(case["expect"]):
            run = want.get("run", "photo")
            got = next((g for g in left if g["run"] == run and g["kind"] == want["kind"]), None)
            if got is not None:
                left.remove(got)
            rows.append({"case": case["case"], "opening": i + 1, "want": want["type"], **compare(want, got)})
    errs = [r["axesErr"] for r in rows if isinstance(r.get("axesErr"), float)] + [r["hAxesErr"] for r in rows if isinstance(r.get("hAxesErr"), float)]
    total = {"openings": len(rows), "typeRight": sum(1 for r in rows if r["typeRight"]),
             "leavesRight": sum(1 for r in rows if r.get("leavesRight")),
             "dividerCountWrong": sum(1 for r in rows if "count" in (r.get("axesErr"), r.get("hAxesErr"))),
             "worstDividerErr": round(max(errs, default=0.0), 3),
             "transomPanesRight": sum(1 for r in rows if r.get("transomPanesRight")),
             "transomPanesAsked": sum(1 for r in rows if "transomPanesRight" in r),
             "handlesRight": sum(1 for r in rows if r.get("handlesRight")),
             "handlesAsked": sum(1 for r in rows if "handlesRight" in r)}
    return {"rows": rows, "total": total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", help="write the rows and totals to this file")
    ap.add_argument("--live", action="store_true", help="ask the real vision model (needs RECOG_API_KEY or the provider's key)")
    a = ap.parse_args(argv)
    doc = json.loads(CASES.read_text(encoding="utf-8"))
    client = None
    if a.live:
        client = live_client()
        if client is None:
            print("--live: no key (RECOG_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY); nothing measured", file=sys.stderr)
            return 2
    result = measure(doc["cases"], client)
    for r in result["rows"]:
        mark = "OK  " if r["typeRight"] else "SAI "
        extra = {k: v for k, v in r.items() if k not in ("case", "opening", "want", "typeRight", "found", "type")}
        print(f"{mark}{r['case']} #{r['opening']}: want {r['want']}, got {r.get('type')} {extra}")
    print(json.dumps(result["total"], ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
