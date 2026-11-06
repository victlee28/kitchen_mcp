"""Natural-language instructions sent with the images to a model that takes instructions (Gemini, the request package).

Pure text builders: the callers pass in what the job knows (regions, changes, the realism text) and get the sentence back.
"""
from __future__ import annotations


def gemini_text(kind: str, prompt: str, instruction: str, style_prompt: str, role: str = "", realism: str = "") -> str:
    """Chỉ dẫn dạng câu cho Gemini (model hiểu ngôn ngữ tự nhiên tốt hơn danh sách tag)."""
    if kind == "gen0":
        return ("The image is a flat-shaded 3D render of a kitchen design with black construction lines. "
                "Turn it into a photorealistic interior photograph. Keep EXACTLY the same camera, perspective, framing, "
                "layout, cabinet sizes, door and drawer divisions, appliance positions, wall and floor edges. "
                "Do not add, remove, move or resize anything; do not crop. Replace flat colors with realistic materials "
                f"of the same hue. Scene: {style_prompt}. {realism} {instruction}".strip().replace("  ", " "))
    return ("Edit the FIRST image. The SECOND image is a mask: change only the region that is white in the mask "
            f"({role}). Make it: {prompt}. {instruction} "
            "Keep the exact shape, edges, panel gaps, perspective and lighting; leave every other pixel of the first "
            "image unchanged; return the full image at the same framing.").strip()


def gemini_text_edit(regions: list[dict], instruction: str = "", realism: str = "") -> str:
    """Chỉ dẫn sửa ảnh cho Gemini khi ảnh 1 đã ĐÁNH DẤU (viền màu + số quanh từng vùng) và ảnh 2 là mask.

    Mỗi region: color (RED…), n (số nhãn), role, mat, extra, where (vị trí bằng chữ), others (số vật cùng loại khác giữ nguyên).
    Ba lớp chỉ định vùng cùng lúc — viền trên ảnh, mask, vị trí bằng chữ — để model không đoán sai đối tượng."""
    multi = len(regions) > 1
    head = ("You are given two images. IMAGE 1 is the kitchen photo to edit; the area"
            + ("s to change are" if multi else " to change is")
            + " surrounded by a thin colored OUTLINE with a number label. IMAGE 2 is the "
            + ("color-coded mask: each colored area is exactly the region of the same-colored outline in image 1."
               if multi else "mask: the white area is exactly the region inside the outline in image 1."))
    lines = []
    for r in regions:
        what = f"the {r['role']}" + (f" in the {r['where']}" if r.get("where") else "")
        n, kind = r.get("others") or 0, r.get("kind") or r["role"]
        keep = ("" if not n else f" The other {kind} in the photo is NOT outlined — leave it unchanged." if n == 1
                else f" The {n} other {kind}s in the photo are NOT outlined — leave them unchanged.")
        lines.append(f"- Region {r['n']} ({r['color']} outline): {what}. Make it {r['material_text']}. {r.get('extra') or ''}".rstrip()
                     + keep)
    return (head + "\nChanges:\n" + "\n".join(lines) + "\n"
            + (f"{instruction}\n" if instruction else "")
            + (f"{realism}\n" if realism else "")
            + "Change ONLY the pixels inside the outlined region(s); everything outside them must stay identical to image 1. "
              "Keep the exact shape, edges, panel gaps, perspective and lighting of the edited parts. "
              "REMOVE the colored outlines and number labels in your result (draw what is really behind them). "
              "Return the full image at the same size and framing.")


_SHAPE_DIRECTION = {
    "remove-item": ("Where an object is removed, image 3 shows what is behind it (wall, floor, the side of the neighbouring cabinet, "
                "the countertop end, the plinth): paint those surfaces with the same materials, colors and lighting as the matching "
                "surfaces elsewhere in image 1, so nothing of the removed object remains."),
    "add-item": ("Paint the new object(s) shown in image 3 with realistic materials that match the existing cabinets of image 1 "
                 "(same finish, color and hardware style unless stated)."),
    "replace-item": ("Keep the materials, colors and finish that image 1 has in this region; change only the shape / style so it "
                 "matches image 3."),
}


def gemini_text_geometry(operation: str, changes: list[str], where: str | None, instruction: str = "", realism: str = "") -> str:
    """Sửa hình: ảnh 1 có viền, ảnh 2 mask, ảnh 3 hình mẫu thiết kế mới (màu phẳng + nét) cùng camera."""
    return ("You are given three images of the same kitchen from the same camera. IMAGE 1 is the photo to edit; the area to "
            "change is surrounded by a thin RED outline with the label 1. IMAGE 2 is the mask: white = exactly the region inside "
            "the outline. IMAGE 3 is a flat-colored technical drawing (black lines) of how the kitchen must look AFTER the change, "
            "same camera and framing: inside the outlined region, follow image 3 exactly for which objects exist and for their "
            "shapes, edges and positions.\n"
            "Changes:\n" + "\n".join(f"- {c}" for c in changes) + "\n"
            + (f"The region is in the {where}.\n" if where else "")
            + _SHAPE_DIRECTION.get(operation, _SHAPE_DIRECTION["replace-item"]) + "\n"
            + (f"{instruction}\n" if instruction else "")
            + (f"{realism}\n" if realism else "")
            + "Image 3 is only a shape guide: do NOT copy its flat colors or black lines — the result must look like the photograph "
              "in image 1, with consistent perspective, shadows and lighting. Everything outside the outline must stay identical "
              "to image 1. REMOVE the red outline and number label. Return the full image at the same size and framing.")


def gemini_text_multi(regions: list[tuple[str, str, str, str]], instruction: str = "") -> str:
    """Nhiều vùng trong một lần gọi: ảnh thứ hai tô mỗi vùng một màu. regions: (màu, vai trò, vật liệu, yêu cầu)."""
    lines = [f"- {color} region ({role}): make it {material_text}. {extra}".strip() for color, role, material_text, extra in regions]
    return ("Edit the FIRST image. The SECOND image is a color-coded mask; apply each change only inside its colored region:\n"
            + "\n".join(lines) + "\n"
            + (f"{instruction}\n" if instruction else "")
            + "Keep the exact shape, edges, panel gaps, perspective and lighting; leave all black (unmasked) areas of the first "
              "image unchanged; return the full image at the same framing.")



def style_note(image_number: int, view: str) -> str:
    """Sentence naming the extra image that carries the look of the kitchen, taken from another camera angle."""
    return (f"IMAGE {image_number} is a STYLE REFERENCE only: an approved photograph of this same kitchen from another camera angle ('{view}'). "
            "Match its materials, colors, wood grain, stone veining, surface finish and the mood and color temperature of its light. "
            "Do NOT copy its composition, camera, framing or objects, and do not let it change the shapes in the other image(s).")
