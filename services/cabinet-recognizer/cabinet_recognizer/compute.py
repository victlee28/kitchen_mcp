"""Từ số đo pixel + phán đoán của AI -> spec tủ bếp tính bằng mm (lõi thuần, xác định).

Đơn vị: *_px là pixel ảnh gốc (trục y hướng xuống), còn lại là mm.
Khung toạ độ đầu ra: x tính từ đầu trái dãy sang phải, y tính từ sàn lên.
"""
from __future__ import annotations

from typing import Any

from .contract import Layout, Policy, Segmentation
from .errors import invalid
from .labels_vi import APPLIANCE_NAMES, module_name
from .numeric import round_half_away, round_int, snap

ID_PREFIX = {"upper": "TT", "base": "TD"}


def _pos(lines: list[dict[str, Any]]) -> dict[str, int]:
    return {ln["id"]: int(ln["pos"]) for ln in lines}


def _rows_px(measure: dict[str, Any], seg: Segmentation) -> dict[str, int]:
    hp = _pos(measure["hlines"])
    return {k: hp[v] for k, v in seg["rows"].items()}


def _bounds_px(measure: dict[str, Any], seg: Segmentation, band: str) -> list[int]:
    vp = _pos(measure["vlines"][band])
    return [vp[b] for b in seg[band]["boundaries"]]  # type: ignore[literal-required]


def policy_summary(measure: dict[str, Any], layout: Layout, seg: Segmentation) -> dict[str, Any]:
    """Các số đo pixel gửi cho bước AI chọn chuẩn kích thước."""
    rows = _rows_px(measure, seg)
    ux, bx = _bounds_px(measure, seg, "upper"), _bounds_px(measure, seg, "base")
    base_h = rows["floor"] - rows["worktopFront"]
    return {
        "imageSizePx": measure["imageSize"],
        "baseRunWidthPx": bx[-1] - bx[0],
        "upperRunWidthPx": ux[-1] - ux[0],
        "floorToWorktopFrontPx": base_h,
        "plinthPx": rows["floor"] - rows["plinthTop"],
        "upperHeightPx": rows["upperBottom"] - rows["upperTop"],
        "worktopBackToUpperBottomPx": rows["worktopBack"] - rows["upperBottom"],
        "baseModuleWidthsPx": [b - a for a, b in zip(bx, bx[1:])],
        "upperModuleWidthsPx": [b - a for a, b in zip(ux, ux[1:])],
        "runWidthOverBaseHeight": round_half_away((bx[-1] - bx[0]) / base_h, 0.001),
        "upperSameExtent": layout["upperSameExtent"],
        "leftEnd": layout["leftEnd"], "rightEnd": layout["rightEnd"],
    }


EQUAL_TOLERANCE = 0.03  # các phần lệch nhau < 3% tổng coi như chia đều


def _split(total: int, fractions: list[float], step: int) -> list[int]:
    """Chia tổng theo tỉ lệ; phần cuối nhận phần dư để tổng đúng tuyệt đối.
    Tỉ lệ gần đều (cánh đôi, ngăn kéo bằng nhau) thì chia đều."""
    n = len(fractions)
    if n > 1 and max(fractions) - min(fractions) < EQUAL_TOLERANCE:
        fractions = [1 / n] * n
        if total % n == 0:
            return [total // n] * n
    out: list[int] = []
    for f in fractions[:-1]:
        out.append(round_int(total * f, step))
    out.append(total - sum(out))
    return out


def build_spec(measure: dict[str, Any], layout: Layout, seg: Segmentation, policy: Policy,
               refine: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    rows = _rows_px(measure, seg)
    ux, bx = _bounds_px(measure, seg, "upper"), _bounds_px(measure, seg, "base")

    # 1. Tỉ lệ ở mặt trước tủ dưới: chiều cao sàn -> mặt đá là chuẩn tham chiếu
    base_h_px = rows["floor"] - rows["worktopFront"]
    if base_h_px <= 0:
        raise invalid("bad-rows", "floor phải nằm dưới worktopFront")
    s_base = policy["referenceMm"] / base_h_px

    # 2. Tủ trên xa camera hơn nên trông nhỏ hơn: suy hệ số từ hai dãy cùng đầu mút
    if layout["upperSameExtent"]:
        factor = (bx[-1] - bx[0]) / (ux[-1] - ux[0])
    else:
        factor = policy["upperScaleFactor"]
    if not 0.95 <= factor <= 1.15:
        warnings.append({"code": "upper-factor-unusual", "factor": round_half_away(factor, 0.001)})
    s_upper = s_base * factor

    # 3. Chiều dài dãy, làm tròn và co giãn đều mọi đường chia theo phần làm tròn
    run_measured = (bx[-1] - bx[0]) * s_base
    run = round_int(run_measured, policy["runRoundingMm"])
    k = run / run_measured
    base_off = [(x - bx[0]) * s_base * k for x in bx]
    if layout["upperSameExtent"]:
        upper_off = [(x - ux[0]) * s_upper * k for x in ux]
    else:
        start = (ux[0] - bx[0]) * s_base
        upper_off = [(start + (x - ux[0]) * s_upper) * k for x in ux]

    # 4. Căn đường chia tủ trên trùng tủ dưới khi lệch ít (ưu tiên tủ dưới: gần camera, mép rõ)
    aligned: list[dict[str, Any]] = []
    for i, off in enumerate(upper_off):
        near = min(base_off, key=lambda b: abs(b - off))
        if abs(near - off) <= policy["alignToleranceMm"]:
            if abs(near - off) > 0.5:
                aligned.append({"line": seg["upper"]["boundaries"][i],
                                "fromMm": round_int(off), "toMm": round_int(near)})
            upper_off[i] = near
    if aligned:
        warnings.append({"code": "upper-aligned-to-base", "lines": aligned})

    step = policy["widthRoundingMm"]
    base_mm = [round_int(o, step) for o in base_off]
    upper_mm = [round_int(o, step) for o in upper_off]
    base_mm[0], base_mm[-1] = 0, run
    if layout["upperSameExtent"]:
        upper_mm[0], upper_mm[-1] = 0, run
    for band, xs in (("upper", upper_mm), ("base", base_mm)):
        if any(b <= a for a, b in zip(xs, xs[1:])):
            raise invalid("collapsed-module", f"{band}: có module rộng <= 0 sau khi làm tròn")

    # 5. Chiều cao: đo rồi snap về giá trị chuẩn AI chọn
    tol = policy["snapToleranceMm"]
    upper_h_meas = (rows["upperBottom"] - rows["upperTop"]) * s_upper
    upper_h, ok_h = snap(upper_h_meas, policy["upperHeightOptionsMm"], tol)
    gap_meas = (rows["worktopBack"] - rows["upperBottom"]) * s_upper
    gap, ok_g = snap(gap_meas, policy["gapOptionsMm"], tol)
    plinth_meas = (rows["floor"] - rows["plinthTop"]) * s_base
    for code, ok, meas in (("upper-height-not-standard", ok_h, upper_h_meas),
                           ("gap-not-standard", ok_g, gap_meas)):
        if not ok:
            warnings.append({"code": code, "measuredMm": round_int(meas)})
    if abs(plinth_meas - policy["plinthMm"]) > 40:
        warnings.append({"code": "plinth-differs", "measuredMm": round_int(plinth_meas),
                         "usedMm": policy["plinthMm"]})

    worktop = policy["referenceMm"]
    thick = policy["worktopThicknessMm"]
    plinth = policy["plinthMm"]
    upper_bottom = worktop + gap
    upper_top = upper_bottom + upper_h
    loft_h = 0                                    # a second, top row of wall cabinets (rows.upperSplit given)
    if "upperSplit" in rows:
        loft_h = round_int((rows["upperSplit"] - rows["upperTop"]) * s_upper, policy["heightRoundingMm"])
        if not 0 < loft_h < upper_h:
            warnings.append({"code": "loft-row-ignored", "measuredMm": loft_h})
            loft_h = 0
    lower_h = upper_h - loft_h                    # the wall cabinets under the loft row
    lower_top = upper_bottom + lower_h
    top_line = rows["upperSplit"] if loft_h else rows["upperTop"]
    base_body = worktop - thick
    front_h = round_int((rows["plinthTop"] - rows["frontsTop"]) * s_base, 10)
    if not 0 < front_h <= base_body - plinth:
        front_h = base_body - plinth
        warnings.append({"code": "front-height-clamped", "usedMm": front_h})

    # 6. Module
    modules: list[dict[str, Any]] = []
    vpos = {"upper": _pos(measure["vlines"]["upper"]), "base": _pos(measure["vlines"]["base"])}
    for band, xs_mm, xs_px in (("upper", upper_mm, ux), ("base", base_mm, bx)):
        answers = seg[band]["modules"]  # type: ignore[literal-required]
        for i, ans in enumerate(answers):
            width = xs_mm[i + 1] - xs_mm[i]
            mod: dict[str, Any] = {
                "id": f"{ID_PREFIX[band]}{i + 1}", "type": ans["type"],
                "name": module_name(ans["type"], ans["doors"], ans["drawers"], ans["open"]),
                "storey": band, "x": xs_mm[i], "width": width,
                "depth": policy["upperDepthMm"] if band == "upper" else policy["baseDepthMm"],
                "confidence": ans["confidence"],
            }
            cell_px = xs_px[i + 1] - xs_px[i]
            if ans["doors"] and not ans["open"]:
                if ans["doorSplits"]:
                    fr = [vpos[band][s] for s in ans["doorSplits"]]
                    edges = [xs_px[i], *fr, xs_px[i + 1]]
                    mod["doors"] = _split(width, [(b - a) / cell_px for a, b in zip(edges, edges[1:])], step)
                else:
                    mod["doors"] = _split(width, [1 / ans["doors"]] * ans["doors"], step)
            inner = refine.get(band, [])[i]["innerRows"] if i < len(refine.get(band, [])) else []
            if band == "upper":
                mod["y"], mod["height"] = upper_bottom, lower_h
                if ans["applianceBelow"] == "hood":
                    if inner:
                        door_h = round_int((inner[0] - top_line) * s_upper, policy["heightRoundingMm"])
                        mod["y"], mod["height"] = lower_top - door_h, door_h
                        mod["applianceBelowHeight"] = lower_h - door_h
                    else:
                        warnings.append({"code": "hood-line-missing", "module": mod["id"]})
            elif ans["type"].startswith("tall"):      # a tall unit in the base band: floor to the top of the wall cabinets
                mod["storey"], mod["y"], mod["height"] = "tall", 0, upper_top
            else:
                mod["y"], mod["height"] = 0, base_body
                if ans["drawers"]:
                    zone_mm = front_h
                    if len(inner) == ans["drawers"] - 1:
                        ys = [rows["frontsTop"], *inner, rows["plinthTop"]]
                        tot = ys[-1] - ys[0]
                        mod["drawers"] = _split(zone_mm, [(b - a) / tot for a, b in zip(ys, ys[1:])], 10)
                    else:
                        warnings.append({"code": "drawer-lines-missing", "module": mod["id"]})
                        mod["drawers"] = _split(zone_mm, [1 / ans["drawers"]] * ans["drawers"], 10)
            if ans["note"]:
                mod["note"] = ans["note"]
            modules.append(mod)
    if loft_h:
        for i, below in enumerate([m for m in modules if m["storey"] == "upper"]):
            loft = {k: v for k, v in below.items() if k in ("x", "width", "depth", "confidence")}
            loft.update(id=f"TN{i + 1}", type="upper-top", storey="upper-top", y=lower_top, height=loft_h,
                        name=module_name("upper-top", 0, 0, False))
            if "doors" in below:
                loft["doors"] = list(below["doors"])
            modules.append(loft)

    appliances = [{
        "id": f"AP{n + 1}", "kind": a["kind"], "name": APPLIANCE_NAMES.get(a["kind"], a["kind"]),
        "module": f"{ID_PREFIX[a['band']]}{a['module'] + 1}", **({"note": a["note"]} if a["note"] else {}),
    } for n, a in enumerate(seg["appliances"])]

    return {
        "schema": "cabinet-recognizer/0.1",
        "unit": "mm",
        "origin": "x từ đầu trái dãy sang phải, y từ sàn lên",
        "layout": layout["layout"], "wall": "back",
        "leftEnd": layout["leftEnd"], "rightEnd": layout["rightEnd"],
        "common": {
            "runLength": run, "plinthHeight": plinth, "worktopTop": worktop,
            "worktopThickness": thick, "baseDepth": policy["baseDepthMm"],
            "baseFrontHeight": front_h, "baseFrontTopGap": base_body - plinth - front_h,
            "upperBottom": upper_bottom, "upperTop": upper_top, "upperDepth": policy["upperDepthMm"],
            **({"upperSplit": lower_top} if loft_h else {}),
            "materials": layout["materials"],
        },
        "modules": modules,
        "appliances": appliances,
        "evidence": {
            "region": policy["region"],
            "baseMmPerPx": round_half_away(s_base, 0.001),
            "upperMmPerPx": round_half_away(s_upper, 0.001),
            "upperFactor": round_half_away(factor, 0.0001),
            "measuredMm": {
                "runLength": round_int(run_measured), "upperHeight": round_int(upper_h_meas),
                "gap": round_int(gap_meas), "plinth": round_int(plinth_meas),
            },
            "boundariesPx": {"upper": ux, "base": bx},
            "rowsPx": rows,
            "policyReasoning": policy["reasoning"],
        },
        "warnings": warnings,
    }
