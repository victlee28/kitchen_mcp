"""Give runs made against a floorplan element before cabinet systems existed the id of that element (Run.system), so they join its system.

  python tools/assign_run_systems.py            dry run: what would be assigned, nothing written
  python tools/assign_run_systems.py --apply    back the database up beside itself, then write

Only runs without a system, in designs bound to an imported floorplan, whose back line lies on an edge of one element (furniture, column,
wall, shaft) with the doors looking out of it (kitchen.run_line.element_against). Several equally good elements: left alone and listed.
One new revision per design changed (op set-run-system); geometry does not change, so neither do the render keys. Nothing is deleted.
"""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import geometry, roomctx, run_line, runs  # noqa: E402
from kitchen.edit import combine_ops  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402


def plan(spec) -> tuple[list[dict], list[str]]:
    """(set-run-system ops, notes) for one design."""
    if not isinstance(getattr(spec, "floorplan", None), dict) or not spec.runs:
        return [], []
    scene = geometry.compile_spec(spec)
    ctx = roomctx.for_spec(spec, scene.lsau, scene.lphai)
    if ctx is None:
        return [], ["no floorplan context"]
    place = ctx.placement
    structures = [{"sourceElement": st.get("sourceElement") or str(st["id"]).removeprefix("STRUCT-"), "kind": st["kind"],
                   "outline": [place.to_kitchen(float(p["x"]), float(p["z"])) if place else (float(p["x"]), float(p["z"])) for p in st["outline"]]}
                  for st in ctx.structures]
    ops, notes = [], []
    for r in spec.runs:
        mods = [m for m in spec.module if m.run == r.id]
        if r.system or not mods:
            continue
        element, tied = run_line.element_against({"x": r.x, "z": r.z, "yaw": r.yaw}, min(m.fromCorner for m in mods), max(m.endAt for m in mods), structures)
        if element:
            ops.append({"op": "set-run-system", "id": r.id, "system": runs.system_id(element)})
        elif tied:
            notes.append(f"{r.id}: against several elements equally ({', '.join(tied)}); left alone")
    return ops, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "kitchen.db"))
    ap.add_argument("--renders", default=str(ROOT / "renders"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    db = Path(args.db)
    if args.apply:
        backup = db.with_name(f"{db.name}.bak-before-systems-{datetime.datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(db, backup)
        print(f"backup: {backup.name}")
    svc = KitchenService(db, Path(args.renders))
    changed = 0
    for row in svc.store.list_designs():
        spec, rev = svc.store.get(row["id"])
        ops, notes = plan(spec)
        for n in notes:
            print(f"  {row['id']}: {n}")
        if not ops:
            continue
        changed += 1
        print(f"{row['id']} rev {rev}: " + ", ".join(f"{o['id']} -> {o['system']}" for o in ops))
        if args.apply:
            svc.apply(row["id"], combine_ops(ops), rev, "assign-systems")
    print(f"{changed} designs {'changed' if args.apply else 'would change'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
