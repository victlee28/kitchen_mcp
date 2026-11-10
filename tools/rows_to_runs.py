"""Rewrite stored designs that follow the walls as explicit runs (kitchen/rows_to_runs.py), one NEW revision per design.

  python tools/rows_to_runs.py                 dry run: what would change, nothing written
  python tools/rows_to_runs.py --apply         back the database up beside itself, then write

A design is rewritten only when its compiled kitchen is the same before and after (every box in the same place); otherwise it is left as it
is and listed. Nothing is deleted: the old revision stays in the history, so ``revert`` brings a design back.
"""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import rows_to_runs  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import KitchenSpec, to_data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "kitchen.db"))
    ap.add_argument("--renders", default=str(ROOT / "renders"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args()
    db = Path(args.db)
    if args.apply:
        backup = db.with_name(f"{db.name}.bak-before-runs-{datetime.datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(db, backup)
        print(f"backup: {backup.name}")
    svc = KitchenService(db, Path(args.renders))
    report: dict = {"converted": [], "partly": [], "unchanged": [], "skipped": [], "failed": []}
    for row in svc.store.list_designs():
        did = row["id"]
        try:
            spec, rev = svc.store.get(did)
            data, notes = rows_to_runs.convert(spec)
            after = KitchenSpec.model_validate(data)
            if to_data(after) == to_data(spec):
                report["unchanged"].append(did)
                continue
            diff = rows_to_runs.equivalent(spec, after)
            if diff:
                report["skipped"].append({"id": did, "why": diff})
                continue
            if args.apply:
                svc.apply(did, {"op": "replace", "spec": data}, rev, "rows-to-runs")
            left = [m.id for m in after.module if not m.run]
            report["partly" if left else "converted"].append({"id": did, "fromRev": rev, "leftOnWalls": left, "notes": notes} if left else {"id": did, "fromRev": rev})
        except Exception as error:  # one broken design must not stop the rest
            report["failed"].append({"id": did, "why": f"{type(error).__name__}: {error}"[:200]})
    print({k: len(v) for k, v in report.items()}, "(written)" if args.apply else "(dry run)")
    for item in report["skipped"] + report["failed"]:
        print(" ", item["id"], item["why"])
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
