"""Phào cổ điển: preset mặt cắt, tính đường chạy từ module, quét mặt cắt thành lưới tam giác, kiểm tra.

Đường chạy (mặt bằng x, z; mm) đi theo thứ tự tường phải (về phía góc) -> tường sau -> tường trái, sao cho
phía phòng luôn nằm theo pháp tuyến n = (t.z, -t.x) của hướng đi t. Góc chữ L và đầu quay về tường là các
đỉnh của cùng một đường gấp khúc nên được vát góc (miter) tự động khi quét. Thuật toán quét có bản JS tương ứng
trong web/scene-loader.js (sweepRings) và được test so khớp.
"""
from __future__ import annotations

from typing import Any

import math
from dataclasses import dataclass, field

from . import builtin, words
from .catalog import Catalog
from .i18n import pick
from .jsonview import as_list
from .spec import KitchenSpec, Molding, MoldingProfile, Module, from_data, to_data
from . import runs as runmod
from .errors import InvalidInput

def _points(raw: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in as_list(raw) or []:
        pair = as_list(p) or []
        out.append((float(pair[0]), float(pair[1])))
    return out


def _profiles(catalog: Catalog) -> dict[str, MoldingProfile]:
    return {it.id: MoldingProfile(id=it.id, name=pick(it.data.get("name"), "vi"), description=pick(it.data.get("description"), "vi") or None,
                                  points=_points(it.data.get("points"))) for it in catalog.all("molding-profile")}


def presets(catalog: Catalog = builtin.CATALOG) -> dict[str, MoldingProfile]:
    """The molding profiles offered (catalog kind ``molding-profile``: workshop and user edit them)."""
    return catalog.derived("moldings.presets", _profiles)


PRESETS: dict[str, MoldingProfile] = presets()
"""The builtin profiles: what a design that names a profile without carrying it is drawn with. A profile from the catalog that is not
exactly a builtin one is copied into the design (``embedded``), so editing the catalog never redraws a stored design."""


def embedded(ids: list[str], own: list[MoldingProfile], catalog: Catalog = builtin.CATALOG) -> list[MoldingProfile]:
    """``own`` plus the catalog profiles among ``ids`` the design must carry: those that are not exactly the builtin profile of that id."""
    have = {p.id for p in own}
    offered = presets(catalog)
    extra = [offered[i] for i in dict.fromkeys(ids) if i in offered and i not in have and offered[i] != PRESETS.get(i)]
    return [*own, *extra]


def profile_of(spec: KitchenSpec, id: str) -> MoldingProfile | None:
    for p in spec.moldingProfiles:
        if p.id == id:
            return p
    return PRESETS.get(id)


def default_moldings(crown: bool = True, base: bool = True, crown_profile: str = "classic-crown-layered",
                     base_profile: str = "classic-base") -> list[Molding]:
    out: list[Molding] = []
    if crown:
        out.append(Molding(id="crown-molding", variant="crown", profile=crown_profile))
    if base:
        out.append(Molding(id="base-molding", variant="base", profile=base_profile))
    return out


# ------------------------------------------------------------------ đường chạy
@dataclass
class Run:
    molding: Molding
    profile: MoldingProfile
    y: float
    points: list[tuple[float, float]]  # (x, z) mặt bằng, mm
    modules: list[str] = field(default_factory=list[str])
    wall: list[str] = field(default_factory=list[str])

    @property
    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))


def _lsau(spec: KitchenSpec) -> float:
    from .geometry import wall_length            # the one length of the back wall: what the kitchen is drawn with
    return wall_length(spec)[0]


def _wall_pt(wall: str, s: float, d: float, lsau: float) -> tuple[float, float]:
    if wall == "back":
        return (-s, d)
    if wall == "right":
        return (-d, s)
    return (-lsau + d, s)


def _top(m: Module) -> float:
    return m.y + m.height


def _on_wall(spec: KitchenSpec) -> dict[str, str]:
    """Explicit runs standing against a wall of the kitchen frame: run id -> wall. Their cabinets are that wall's row for the moldings, so a
    kitchen written by runs gets the moldings of the same kitchen written by walls (corners, corner shelf and all)."""
    lsau = _lsau(spec)
    out: dict[str, str] = {}
    for r in spec.runs:
        wall = runmod.run_wall(runmod.RunFrame(r.id, r.x, r.z, r.yaw), lsau)
        if wall is not None:
            out[r.id] = wall
    for joint in runmod.corner_joints(spec):      # a corner with a run that is not on a wall (or not square) is turned run by run, both of them
        if not (joint.square and joint.a in out and joint.b in out):
            out.pop(joint.a, None)
            out.pop(joint.b, None)
    return out


def _place(spec: KitchenSpec, m: Module, on_wall: dict[str, str]) -> tuple[str, float, float] | None:
    """(wall, s0, s1) of a cabinet that follows a wall, itself or through its run; None for the others."""
    if m.run:
        wall = on_wall.get(m.run)
        fr = runmod.frame_of(spec, m)
        if wall is None or fr is None:
            return None
        s0, s1 = runmod.along_wall(fr, wall, m.fromCorner, m.endAt)
        return wall, s0, s1
    return (m.wall, m.fromCorner, m.endAt) if m.wall in ("back", "right", "left") else None


def _intervals(spec: KitchenSpec, variant: str) -> tuple[dict[str, list[tuple[float, float, float, str]]], float]:
    """Đoạn (s0, s1, độ sâu mặt trước, mã module) theo từng tường + cao độ đường chạy."""
    iv: dict[str, list[Any]] = {"back": [], "right": [], "left": []}
    on_wall = _on_wall(spec)
    if variant == "crown":
        cands = [m for m in spec.module if m.storey in ("upper", "loft", "tall", "corner")]
        if not cands:
            return iv, 0.0
        y = max(_top(m) for m in cands)
        for m in cands:
            if abs(_top(m) - y) > 1:
                continue
            if m.type == "corner-shelf" and not m.run:
                iv["back"].append((0.0, m.backLength, m.depth, m.id))
                iv["right"].append((0.0, m.rightLength, m.depth, m.id))
            elif m.type == "corner-shelf":             # by runs: each leg belongs to the wall its run stands against
                if (at := _place(spec, m, on_wall)) is not None:
                    iv[at[0]].append((at[1], at[2], m.depth, m.id))
                other = runmod.frames(spec).get(m.turnsInto or "")
                wall = on_wall.get(m.turnsInto or "")
                if other is not None and wall is not None and m.rightLength:
                    s0, s1 = runmod.along_wall(other, wall, 0.0, m.rightLength)
                    iv[wall].append((s0, s1, m.depth, m.id))
            elif (at := _place(spec, m, on_wall)) is not None:
                iv[at[0]].append((at[1], at[2], m.depth, m.id))
        return iv, y
    for m in spec.module:  # phào chân: tủ đặt sàn, bỏ tủ cao có hốc thiết bị sát sàn (tủ lạnh)
        if m.y == 0 and (m.storey == "base" or (m.storey == "tall" and not m.niche)) and (at := _place(spec, m, on_wall)) is not None:
            iv[at[0]].append((at[1], at[2], m.depth, m.id))
    return iv, 0.0


def _segments(items: list[tuple[float, float, float, str]], gap: float) -> list[dict[str, Any]]:
    """Cabinets of one row joined into stretches of one depth: ``{"s0", "s1", "d", "mods"}``."""
    segs: list[dict[str, Any]] = []
    for s0, s1, d, id in sorted(items):
        if segs and abs(segs[-1]["d"] - d) <= 1 and s0 - segs[-1]["s1"] <= gap:
            segs[-1]["s1"] = max(segs[-1]["s1"], s1)
            segs[-1]["mods"].append(id)
        else:
            segs.append({"s0": s0, "s1": s1, "d": d, "mods": [id]})
    return segs


def _end_depth(seg: dict[str, Any], neighbor: dict[str, Any] | None, ho: str) -> float | None:
    """Độ sâu mà đầu phào quay về; None = cắt phẳng (đâm vào hông tủ sâu hơn hoặc tường)."""
    if neighbor is not None:
        if neighbor["d"] > seg["d"] + 1:
            return None
        return neighbor["d"]
    return 0.0 if ho == "return-to-wall" else None


def _run_items(spec: KitchenSpec, mol: Molding, run_id: str, y: float) -> list[tuple[float, float, float, str]]:
    if mol.variant == "crown":
        return [(m.fromCorner, m.endAt, m.depth, m.id) for m in spec.module
                if m.run == run_id and m.storey in ("upper", "loft", "tall", "corner") and abs(_top(m) - y) <= 1] + \
               [(0.0, float(m.rightLength or 0.0), m.depth, m.id) for m in spec.module
                if m.turnsInto == run_id and m.rightLength and abs(_top(m) - y) <= 1]     # the second leg of a corner shelf by runs
    return [(m.fromCorner, m.endAt, m.depth, m.id) for m in spec.module
            if m.run == run_id and m.y == 0 and (m.storey == "base" or (m.storey == "tall" and not m.niche))]


def _butts(fr: "runmod.RunFrame", s: float) -> bool:
    """Whether a run's end at ``s`` stands in the back-right corner of the kitchen frame, against the wall it runs into (a run along the back
    wall ending at x = 0, a run along a side wall ending at z = 0): there a molding stops at the wall instead of returning to its own."""
    x, z = fr.to_world(s, 0.0)
    nx, nz = fr.normal()
    return (abs(nx) < 1e-6 and abs(x) <= 1.0 and abs(z) <= 1.0) or (abs(nz) < 1e-6 and abs(z) <= 1.0 and (abs(x) <= 1.0 or nx > 0))


def _angled_runs(spec: KitchenSpec, mol: Molding, prof: MoldingProfile, y: float) -> list[Run]:
    """Moldings along the explicit runs (any angle). Points are walked against s (the run frame is mirror-wise like the right wall).

    Each run is its own chain, except where two runs meet in an inside corner, square or not (``runs.corner_joints``: the end of a meets
    the start of b) and both have cabinets up to the corner: there the two chains are ONE, turning at the point where the two front lines
    cross, so the molding is mitred round the corner instead of two pieces ending in each other."""
    out: list[Run] = []
    chains: dict[tuple[str, int], dict[str, Any]] = {}
    order: list[tuple[str, int]] = []
    segs_of: dict[str, list[dict[str, Any]]] = {}
    on_wall = _on_wall(spec)
    for r in spec.runs:
        if r.id in on_wall or (mol.wall and r.id not in mol.wall):   # a run against a wall is walked as that wall's row (``_intervals``)
            continue
        fr = runmod.RunFrame(r.id, r.x, r.z, r.yaw)
        segs = _segments(_run_items(spec, mol, r.id, y), mol.joinGap)
        segs_of[r.id] = segs
        for i, sg in enumerate(segs):
            prev_n = segs[i - 1] if i > 0 and sg["s0"] - segs[i - 1]["s1"] <= mol.joinGap else None
            next_n = segs[i + 1] if i + 1 < len(segs) and segs[i + 1]["s0"] - sg["s1"] <= mol.joinGap else None
            d = sg["d"]
            dr = None if prev_n is None and _butts(fr, sg["s0"]) else _end_depth(sg, prev_n, mol.openEnd)
            start = [(sg["s0"], d)] if dr is None or abs(dr - d) < 1 else [(sg["s0"], dr), (sg["s0"], d)]
            dr = None if next_n is None and _butts(fr, sg["s1"]) else _end_depth(sg, next_n, mol.openEnd)
            end = [(sg["s1"], d)] if dr is None or abs(dr - d) < 1 else [(sg["s1"], d), (sg["s1"], dr)]
            chains[(r.id, i)] = {"fr": fr, "start": start, "end": end, "mods": sg["mods"], "runs": [r.id], "d": d, "s0": sg["s0"], "s1": sg["s1"]}
            order.append((r.id, i))
    joined: dict[tuple[str, int], tuple[str, int]] = {}          # last chain of a -> first chain of b, where they turn the corner together
    for joint in runmod.corner_joints(spec):
        if not segs_of.get(joint.a) or not segs_of.get(joint.b):
            continue
        ka, kb = (joint.a, len(segs_of[joint.a]) - 1), (joint.b, 0)
        ca, cb = chains[ka], chains[kb]
        cross = runmod.front_cross(ca["fr"], ca["d"], cb["fr"], cb["d"])         # where the two front lines cross (any corner angle)
        if cross is None:
            continue
        # a square corner is turned only by cabinets that reach it; in an open or sharp one the cabinets stop short of the crossing by a wedge
        # (which the worktop closes too), so the molding may bridge up to that wedge
        wedge = 2.0 * math.tan(math.radians(abs(joint.angle - 90.0) / 2.0))
        slack_a, slack_b = mol.joinGap + 1 + ca["d"] * wedge, mol.joinGap + 1 + cb["d"] * wedge
        if ca["s1"] >= cross[0] - slack_a and cb["s0"] <= cross[1] + slack_b and ka not in joined and kb not in joined.values():
            joined[ka] = kb
            ca["turn"] = cross[2]
    tails = set(joined.values())
    for key in order:
        if key in tails:
            continue                                              # walked as the far part of the chain that turns into it
        parts = [key]
        while parts[-1] in joined:
            parts.append(joined[parts[-1]])
        pts: list[tuple[float, float]] = []
        mods: list[str] = []
        names: list[str] = []
        for n, k in reversed(list(enumerate(parts))):             # against s: the far run first, back to the first
            ch = chains[k]
            start: list[tuple[float, float]] = [] if n > 0 else ch["start"]   # its start is the corner it shares with the run before it
            end: list[tuple[float, float]] = [] if k in joined else ch["end"]              # its end is the corner it shares with the run after it
            pts += [ch["fr"].to_world(s0, d0) for s0, d0 in (start + end)[::-1]] if (start or end) else []
            if n > 0:
                pts.append(chains[parts[n - 1]]["turn"])
            mods += ch["mods"]
            names += ch["runs"]
        pts = [p for k, p in enumerate(pts) if k == 0 or math.dist(p, pts[k - 1]) > 0.5]
        if len(pts) >= 2:
            out.append(Run(mol, prof, y, pts, mods, names))
    return out


def compute_runs(spec: KitchenSpec) -> list[Run]:
    lsau = _lsau(spec)
    runs: list[Run] = []
    for mol in spec.moldings:
        if not mol.enabled:
            continue
        prof = profile_of(spec, mol.profile)
        if prof is None:
            continue
        iv, y = _intervals(spec, mol.variant)
        on_wall = _on_wall(spec)
        walls = [on_wall.get(w, w) for w in mol.wall] or ["right", "back", "left"]      # a run named in mol.wall stands for the wall it is against
        segs = {w: (_segments(iv[w], mol.joinGap) if w in walls else []) for w in ("right", "back", "left")}
        # nối góc: đoạn đầu tường phải/trái chạm đoạn đầu (cuối) tường sau
        join_r = bool(segs["right"] and segs["back"] and segs["right"][0]["s0"] <= segs["back"][0]["d"] + 1
                      and segs["back"][0]["s0"] <= segs["right"][0]["d"] + 1)
        join_l = bool(segs["left"] and segs["back"] and segs["left"][0]["s0"] <= segs["back"][-1]["d"] + 1
                      and segs["back"][-1]["s1"] >= lsau - segs["left"][0]["d"] - 1)

        def wall_polys(w: str) -> list[dict[str, Any]]:
            """Mỗi đoạn -> danh sách (s, d) theo chiều đi, kèm cờ bỏ xử lý đầu ở phía góc."""
            out: list[dict[str, Any]] = []
            ss = segs[w]
            for i, sg in enumerate(ss):
                prev_n = ss[i - 1] if i > 0 and sg["s0"] - ss[i - 1]["s1"] <= mol.joinGap else None
                next_n = ss[i + 1] if i + 1 < len(ss) and ss[i + 1]["s0"] - sg["s1"] <= mol.joinGap else None
                at_corner_start = i == 0 and ((w == "right" and join_r) or (w == "left" and join_l) or (w == "back" and join_r))
                at_corner_end = (w == "back" and i == len(ss) - 1 and join_l)
                d = sg["d"]
                # đầu phía s0
                if at_corner_start:
                    other = segs["back"][0]["d"] if w == "right" else segs["right"][0]["d"] if w == "back" else segs["back"][-1]["d"]
                    start = [(other, d)]
                else:
                    dr = None if (sg["s0"] <= 1 and prev_n is None) else _end_depth(sg, prev_n, mol.openEnd)
                    start = [(sg["s0"], d)] if dr is None or abs(dr - d) < 1 else [(sg["s0"], dr), (sg["s0"], d)]
                if at_corner_end:
                    end = [(lsau - segs["left"][0]["d"], d)]
                else:
                    dr = _end_depth(sg, next_n, mol.openEnd)
                    end = [(sg["s1"], d)] if dr is None or abs(dr - d) < 1 else [(sg["s1"], d), (sg["s1"], dr)]
                pts = start + end  # theo chiều s tăng
                if w == "right":
                    pts = pts[::-1]  # tường phải đi về phía góc (s giảm)
                out.append({"pts": [_wall_pt(w, s, dd, lsau) for s, dd in pts], "mods": sg["mods"], "w": w,
                            "corner_start": at_corner_start, "corner_end": at_corner_end})
            return out

        polys = {w: wall_polys(w) for w in ("right", "back", "left")}
        chains: list[dict[str, Any]] = []
        if join_r:
            r_last = polys["right"].pop(0)  # đoạn chạm góc (s nhỏ nhất); theo chiều đi nó kết thúc ở góc
            b_first = polys["back"].pop(0)
            chains.append({"pts": r_last["pts"] + b_first["pts"][1:], "mods": r_last["mods"] + b_first["mods"], "w": ["right", "back"],
                           "tail": b_first})
        for w in ("right", "back", "left"):
            for p in polys[w]:
                chains.append({"pts": p["pts"], "mods": p["mods"], "w": [w], "tail": p})
        if join_l:
            # nối chuỗi chứa đoạn cuối tường sau với đoạn đầu tường trái
            l_first = next(c for c in chains if c["w"] == ["left"])
            b_last = next(c for c in chains if c["tail"].get("corner_end"))
            if b_last is not l_first:
                b_last["pts"] = b_last["pts"] + l_first["pts"][1:]
                b_last["mods"] += l_first["mods"]
                b_last["w"] = b_last["w"] + ["left"]
                chains.remove(l_first)
        for ch in chains:
            pts = [p for i, p in enumerate(ch["pts"]) if i == 0 or math.dist(p, ch["pts"][i - 1]) > 0.5]
            if len(pts) >= 2:
                runs.append(Run(mol, prof, y, pts, ch["mods"], ch["w"]))
        if spec.runs:
            runs.extend(_angled_runs(spec, mol, prof, y if mol.variant == "crown" else 0.0))
    return runs


# ------------------------------------------------------------------ quét mặt cắt
def _normals(pts: list[tuple[float, float]]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    ts: list[tuple[float, float]] = []
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b)
        ts.append(((b[0] - a[0]) / L, (b[1] - a[1]) / L))
    return [(t[1], -t[0]) for t in ts], ts


def sweep_rings(profile: list[tuple[float, float]], pts: list[tuple[float, float]], y: float) -> list[list[tuple[float, float, float]]]:
    """Vòng đỉnh 3D tại mỗi đỉnh đường chạy (miter ở đỉnh giữa). Bản JS: sweepRings trong scene-loader.js."""
    ns, _ = _normals(pts)
    rings: list[list[tuple[float, float, float]]] = []
    for i, p in enumerate(pts):
        if i == 0:
            m = ns[0]
        elif i == len(pts) - 1:
            m = ns[-1]
        else:
            a, b = ns[i - 1], ns[i]
            k = 1 + a[0] * b[0] + a[1] * b[1]
            m = ((a[0] + b[0]) / k, (a[1] + b[1]) / k) if k > 1e-6 else b
        rings.append([(p[0] + m[0] * u, y + v, p[1] + m[1] * u) for u, v in profile])
    return rings


def ear_clip(poly: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    idx = list(range(len(poly)))
    tris: list[tuple[int, int, int]] = []

    def area2(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if area2(a, b, c) <= 1e-9:
                continue
            if any(area2(a, b, poly[j]) >= 0 and area2(b, c, poly[j]) >= 0 and area2(c, a, poly[j]) >= 0
                   for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return tris


@dataclass
class MeshPart:
    id: str
    module: str  # mã phào (để tô mask theo từng phào)
    type: str
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]


def run_mesh(run: Run, idx: int) -> MeshPart:
    prof = run.profile.points
    rings = sweep_rings(prof, run.points, run.y)
    n = len(prof)
    verts = [v for r in rings for v in r]
    faces: list[tuple[int, int, int]] = []
    for k in range(len(rings) - 1):
        for j in range(n):
            a, b = k * n + j, k * n + (j + 1) % n
            c, d = (k + 1) * n + (j + 1) % n, (k + 1) * n + j
            faces += [(a, b, c), (a, c, d)]
    cap = ear_clip(prof)
    last = (len(rings) - 1) * n
    faces += [(c, b, a) for a, b, c in cap] + [(last + a, last + b, last + c) for a, b, c in cap]
    return MeshPart(f"{run.molding.id}-{idx}", run.molding.id, "molding", verts, faces)


def meshes(spec: KitchenSpec) -> list[MeshPart]:
    return [run_mesh(r, i + 1) for i, r in enumerate(compute_runs(spec))]


# ------------------------------------------------------------------ kiểm tra
def _flap(m: Module) -> bool:
    return (m.hingeSides[:1] == ["upper"]) or (not m.hingeSides and m.storey == "loft" and m.width > m.height * 1.2)


def check(spec: KitchenSpec) -> list[dict[str, Any]]:
    c = spec.common
    out: list[dict[str, Any]] = []
    by_id = {m.id: m for m in spec.module}
    runs = compute_runs(spec)
    for mol in spec.moldings:
        if not mol.enabled:
            continue
        prof = profile_of(spec, mol.profile)
        if prof is None:
            out.append(words.finding("MOLDING-PROFILE-001", "error", [mol.id], "finding.molding-no-profile", id=mol.id, profile=mol.profile))
            continue
        mine = [r for r in runs if r.molding.id == mol.id]
        if not mine:
            out.append(words.finding("MOLDING-RUN-001", "info", [mol.id], "finding.molding-no-run", id=mol.id))
            continue
        if mol.variant == "crown":
            top = mine[0].y + prof.height
            if top > c.ceiling + 0.5:
                new_top = math.floor((c.ceiling - prof.height) / 5) * 5
                delta = c.cabinetTop - new_top
                actions: list[dict[str, Any]] = []
                if delta > 0 and _can_lower(spec, delta):
                    actions.append({"label": words.say("action.lower-top", delta=delta, top=c.cabinetTop, new=new_top),
                                    "labelKey": "action.lower-top", "params": {"delta": delta, "top": c.cabinetTop, "new": new_top},
                                    "op": {"op": "lower-top", "newTop": new_top}})
                if not mol.ignoreCeiling:
                    actions.append({"label": words.say("action.keep"), "labelKey": "action.keep",
                                    "op": {"op": "molding", "id": mol.id, "changes": {"ignoreCeiling": True}}})
                    out.append({**words.finding("MOLDING-CEILING-001", "error", [mol.id] + mine[0].modules[:3], "finding.crown-above-ceiling",
                                                id=mol.id, top=top, ceiling=c.ceiling),
                                "measured": top, "limit": c.ceiling, "action": actions})
                else:
                    out.append({**words.finding("MOLDING-CEILING-001", "info", [mol.id], "finding.crown-above-ceiling-kept", id=mol.id, over=top - c.ceiling),
                                "measured": top, "limit": c.ceiling,
                                "action": actions + [{"label": words.say("action.unkeep"), "labelKey": "action.unkeep",
                                                      "op": {"op": "molding", "id": mol.id, "changes": {"ignoreCeiling": False}}}]})
            flaps = sorted({id for r in mine for id in r.modules if id in by_id and _flap(by_id[id])})
            if flaps and prof.overhang > 0:
                out.append(words.finding("MOLDING-FLIPUP-001", "warning", flaps, "finding.flap-hits-crown", ids=', '.join(flaps), overhang=prof.overhang))
        else:
            if prof.height > c.plinthHeight + 2:
                out.append({**words.finding("MOLDING-BASE-001", "warning", [mol.id], "finding.base-molding-high", height=prof.height,
                                            plinth=c.plinthHeight), "measured": prof.height, "limit": c.plinthHeight})
    return out


def _can_lower(spec: KitchenSpec, delta: float) -> bool:
    try:
        lower_top(spec, spec.common.cabinetTop - delta)
        return True
    except ValueError:
        return False


def lower_top(spec: KitchenSpec, new_top: float) -> KitchenSpec:
    """Hạ đỉnh tủ: rút chiều cao các module đang chạm đỉnh (tủ nóc, tủ cao, kệ góc, tủ trên nếu không có nóc)."""
    data = to_data(spec)
    old = spec.common.cabinetTop
    delta = old - new_top
    if delta <= 0:
        raise InvalidInput("The new top must be lower than the current one", code="top-not-lower")
    for m in data["module"]:
        if abs(m["y"] + m["height"] - old) > 1:
            continue
        new_h = m["height"] - delta
        min_h = 150 if m["type"] == "upper-loft" else 300
        if new_h < min_h:
            raise InvalidInput(f"{m['id']} would be {new_h:g} mm, below the minimum {min_h}", code="cabinet-too-low",
                               params={"id": m["id"], "height": f"{new_h:g}", "min": min_h})
        if m.get("niche") and m["y"] + new_h < m["niche"] + 150:
            raise InvalidInput(f"{m['id']}: the part above the appliance niche would be too low", code="niche-top-too-low", params={"id": m["id"]})
        m["height"] = new_h
    c = data["common"]
    if abs(c["upperTierSplit"] - old) <= 1:
        c["upperTierSplit"] = new_top
    c["cabinetTop"] = new_top
    return from_data(KitchenSpec, data)
