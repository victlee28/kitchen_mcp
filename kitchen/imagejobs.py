"""Image Edit Orchestrator: yêu cầu sửa ảnh -> kiểm tra -> mask/prompt -> backend -> ghép strict -> kiểm tra -> duyệt.

Hai chế độ:
- `thiet-ke`  : sửa vật liệu trong thiết kế. Phạm vi mask = mọi chi tiết đổi vật liệu theo thao tác đó
                (vd cả mặt trước module). Thao tác chỉ ghi vào thiết kế khi người dùng CHẤP NHẬN ảnh.
- `thu-nhanh` : chỉ sửa ảnh, đúng layer đã chọn. Khi chấp nhận có thể "Áp vào thiết kế" nếu đã nêu vật liệu.

Một job có thể gồm nhiều việc (`tasks`): mỗi việc một layer + vật liệu/yêu cầu riêng. Các việc không được chạm
cùng một chi tiết (mask rời nhau), ghép từng vùng vào ảnh gốc, và khi chấp nhận thì mọi thao tác thiết kế ghi thành MỘT rev.

Ảnh gốc: ảnh đã chấp nhận gần nhất cùng (thiết kế, góc nhìn, renderKey); chưa có thì albedo.png.
renderKey = băm hình học + camera + kích thước, nên đổi vật liệu không làm mất ảnh gốc / mask.
"""
from __future__ import annotations

import json
import random
import shutil
import threading
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

from . import request_check, backends, edit, geometry, hinh, imaging, layers, realism, render, vocab
from .backends import BACKENDS, BackendError
from .store import ConflictError

GROW_PX = 12     # nở mask gửi model (ngữ cảnh quanh mép)
FEATHER_PX = 2   # viền mềm khi ghép, chỉ vào trong mask
MAU_VIEW = 1280, 960
MAX_TASKS = 8
MAU_VUNG = [("RED", (255, 0, 0)), ("GREEN", (0, 200, 0)), ("BLUE", (0, 80, 255)), ("YELLOW", (255, 220, 0)),
            ("MAGENTA", (255, 0, 255)), ("CYAN", (0, 230, 230)), ("ORANGE", (255, 140, 0)), ("PURPLE", (140, 60, 200))]


def vi_tri(mask: np.ndarray) -> dict | None:
    """Vị trí vùng bằng chữ, tính từ mask: vùng ảnh (trái/giữa/phải × trên/giữa/dưới) + khung theo % kích thước ảnh."""
    b = imaging.bbox(mask)
    if b is None:
        return None
    H, W = mask.shape
    x0, y0, x1, y1 = b
    pc = [round(100 * x0 / W), round(100 * y0 / H), round(100 * x1 / W), round(100 * y1 / H)]
    cx, cy = (x0 + x1) / 2 / W, (y0 + y1) / 2 / H
    h_en, h_vi = ("left", "trái") if cx < 1 / 3 else (("right", "phải") if cx > 2 / 3 else ("center", "giữa"))
    v_en, v_vi = ("upper", "trên") if cy < 1 / 3 else (("lower", "dưới") if cy > 2 / 3 else ("middle", "giữa"))
    if (x1 - x0) > 0.75 * W:
        h_en, h_vi = "across the full width", "chạy gần hết chiều ngang"
        zone_en, zone_vi = f"{v_en} part of the image, {h_en}", f"phần {v_vi} ảnh, {h_vi}"
    else:
        zone_en = "center of the image" if (h_en, v_en) == ("center", "middle") else f"{v_en}-{h_en} area of the image"
        zone_vi = "giữa ảnh" if (h_vi, v_vi) == ("giữa", "giữa") else f"góc {v_vi} bên {h_vi}" if "giữa" not in (h_vi, v_vi) \
            else f"vùng {v_vi} {h_vi}"
    span = f"x {pc[0]}–{pc[2]}%, y {pc[1]}–{pc[3]}%"
    return {"khung": pc, "en": f"{zone_en} (about {span} of the image width/height)", "vi": f"{zone_vi} (khoảng {span} chiều ngang/dọc ảnh)"}


_PHAO_EN = {"crown": "crown molding along the top of the cabinets", "base": "base molding at the bottom of the cabinets"}


class ImageJobs:
    def __init__(self, svc):
        self.svc = svc
        self.store = svc.store
        self._threads: dict[str, threading.Thread] = {}
        self.store.mark_stale_jobs()

    # ------------------------------------------------------------------ render & layer
    def _render_dir(self, did: str, rev: int, view: str) -> Path:
        return self.svc.render_dir / did / f"rev{rev}" / view

    def ensure_render(self, did: str, rev: int | None, view: str, width: int | None = None, height: int | None = None):
        spec, r = self.store.get(did, rev)
        views = geometry.views_of(spec)
        if view not in views:
            raise ValueError(f"Không có góc nhìn '{view}'. Có: {', '.join(views)}")
        d = self._render_dir(did, r, view)
        man = d / "manifest.json"
        scene = geometry.compile_spec(spec)
        if man.exists():
            m = json.loads(man.read_text(encoding="utf-8"))
            w, h = width or m["width"], height or m["height"]
            if m.get("renderKey") == render.render_key(scene, views[view], w, h) and (d / "instance.png").exists():
                return spec, r, scene, d, m
        w, h = width or MAU_VIEW[0], height or MAU_VIEW[1]
        if not (256 <= w <= 4096 and 256 <= h <= 4096):
            raise ValueError("width/height phải trong 256–4096")
        render.render_views(spec, d.parent, [view], w, h, meta={"designId": did, "rev": r})
        return spec, r, scene, d, json.loads(man.read_text(encoding="utf-8"))

    def layers(self, did: str, view: str, rev: int | None = None, all_layers: bool = False) -> dict:
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        _, meta = imaging.load_instances(d)
        px = {i["id"]: i["pixels"] for i in meta["instances"]}
        out = []
        for x in layers.catalogue(spec, scene):
            ids = x.get("thanhPhan") or [x["id"]]
            n = sum(px.get(i, 0) for i in ids)
            if n or all_layers:
                op = layers.design_op(spec, x, "?") if x.get("vatLieuKhoa") else None
                out.append({**x, "pixels": n, "suaThietKe": op[1] if op else None})
        return {"id": did, "rev": r, "view": view, "renderKey": man["renderKey"], "width": man["width"], "height": man["height"],
                "dir": str(d), "layers": out, "anhGoc": self._reference(did, view, man["renderKey"], d)[1]}

    def mask_png(self, did: str, view: str, layer_id: str, rev: int | None = None) -> bytes:
        import io
        spec, r, scene, d, _ = self.ensure_render(did, rev, view)
        _, ids = layers.resolve(layers.catalogue(spec, scene), layer_id)
        buf = io.BytesIO()
        Image.fromarray(imaging.mask_of(d, ids).astype(np.uint8) * 255, "L").save(buf, "PNG")
        return buf.getvalue()

    def pick(self, did: str, view: str, x: int, y: int, rev: int | None = None) -> dict:
        spec, r, scene, d, _ = self.ensure_render(did, rev, view)
        hit = imaging.pick(d, x, y)
        if not hit:
            return {"chiTiet": None, "layers": []}
        cat = layers.catalogue(spec, scene)
        groups = [g["id"] for g in cat if g["id"] == hit["id"] or hit["id"] in (g.get("thanhPhan") or [])]
        return {"chiTiet": hit, "layers": groups}

    def save_beauty(self, did: str, view: str, image: bytes, rev: int | None = None) -> dict:
        """Ảnh render three.js (trình duyệt) -> beauty.png của rev/góc; dùng làm ảnh gốc khi chưa có ảnh AI đã duyệt."""
        import io
        spec, r, scene, d, man = self.ensure_render(did, rev, view)
        try:
            with Image.open(io.BytesIO(image)) as f:
                im = f.convert("RGB")
        except Exception:
            raise ValueError("Ảnh không đọc được (cần PNG/JPEG)")
        W, H = man["width"], man["height"]
        if im.size != (W, H):
            if abs(im.size[0] / im.size[1] - W / H) > 0.01:
                raise ValueError(f"Ảnh {im.size[0]}×{im.size[1]} khác tỉ lệ ảnh điều khiển {W}×{H}; render lại đúng tỉ lệ")
            im = im.resize((W, H), Image.LANCZOS)
        im.save(d / "beauty.png")
        k = imaging.edge_alignment(np.array(im), imaging.read(d / "lines.png", "L"))
        info = {"designId": did, "rev": r, "view": view, "renderKey": man["renderKey"], "size": [W, H], "khopNet": k,
                "nguon": "three.js (trình duyệt)"}
        (d / "beauty.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**info, "dir": str(d)}

    @staticmethod
    def _key_of(j: dict) -> str:
        """renderKey hình học mà ẢNH KẾT QUẢ của job khớp: job sửa hình cho ảnh của thiết kế mới."""
        return (j["result"] or {}).get("renderKeyMoi") or j["render_key"] if j["kind"] == "hinh" else j["render_key"]

    def _reference(self, did: str, view: str, key: str, d: Path) -> tuple[Path, dict]:
        acc = [j for j in self.store.list_jobs(did, view, "da-chap-nhan", 200) if self._key_of(j) == key]
        acc.sort(key=lambda j: (j["result"].get("chapNhanLuc", ""), j["updated_at"]), reverse=True)
        if acc:
            j = acc[0]
            return Path(j["result"]["dir"]) / "composite.png", {"loai": "job", "jobId": j["id"]}
        if (d / "beauty.png").exists():
            return d / "beauty.png", {"loai": "beauty"}
        return d / "albedo.png", {"loai": "albedo"}

    # ------------------------------------------------------------------ tạo job
    def create(self, did: str, view: str, target: str | None = None, instruction: str = "", mode: str = "thu-nhanh",
               vat_lieu: str | None = None, backend: str = "to-mau", reference: str | None = None, base_rev: int | None = None,
               kind: str = "edit", workflow: str | None = None, seed: int | None = None, params: dict | None = None,
               tasks: list[dict] | None = None, preview: bool = False, hinh_items: list[dict] | None = None,
               thao_tac: str | None = None, anh_sang: str | None = None) -> dict:
        """tasks: [{"targetLayer": "TD1-canh-1", "vatLieu": "...", "instruction": "..."}, ...]. Không có tasks thì
        dùng target/vat_lieu/instruction như một việc. preview=True: chỉ chuẩn bị (mask, request.json), dừng ở 'cho-gui'
        để người dùng xem trước; gửi bằng send(), hủy bằng reject()."""
        if kind not in ("edit", "gen0", "hinh"):
            raise ValueError("kind phải là edit, gen0 hoặc hinh")
        if anh_sang not in (None, "", *realism.ANH_SANG):
            raise ValueError(f"anhSang phải là một trong: {', '.join(realism.ANH_SANG)}")
        if thao_tac is not None:  # bảng thao tác: workflow + trọng số ControlNet mặc định theo loại việc
            if thao_tac not in hinh.THAO_TAC:
                raise ValueError(f"thaoTac phải là một trong: {', '.join(hinh.THAO_TAC)}")
            pre = hinh.THAO_TAC[thao_tac]
            if pre["kind"] != kind:
                raise ValueError(f"thaoTac '{thao_tac}' dùng cho kind={pre['kind']} (đang là {kind})")
            workflow = workflow or pre["workflow"]
            params = {**pre["params"], **(params or {})}
        if kind == "hinh":
            if not hinh_items:
                raise ValueError("kind=hinh cần danh sách thao tác hình học (hinh)")
            mode = "thiet-ke"  # sửa hình: chấp nhận ảnh = ghi thao tác vào thiết kế
        if backend not in BACKENDS:
            raise ValueError(f"backend phải là một trong: {', '.join(BACKENDS)}")
        if kind not in BACKENDS[backend]["kind"]:
            raise ValueError(f"backend '{backend}' không hỗ trợ {kind}")
        if mode not in ("thu-nhanh", "thiet-ke"):
            raise ValueError("mode phải là thu-nhanh hoặc thiet-ke")
        if kind == "hinh":
            tasks = []
        elif kind == "edit" and not tasks:  # một việc: yêu cầu thuộc về việc đó, không lặp ở cấp job
            tasks, instruction = self._norm_tasks(None, target, vat_lieu, instruction), ""
        else:
            tasks = self._norm_tasks(tasks, None, None, "") if kind == "edit" else []
        latest = self.store.get(did)[1]
        if base_rev is not None and base_rev != latest:
            raise ConflictError(f"baseRev={base_rev} nhưng bản mới nhất là {latest}; hãy tải lại")
        spec, rev, scene, d, man = self.ensure_render(did, latest, view)
        jid = f"job-{uuid.uuid4().hex[:10]}"
        jdir = d / "jobs" / jid
        jdir.mkdir(parents=True, exist_ok=True)
        try:
            req = self._prepare(jid, jdir, d, spec, rev, scene, man, did, view, tasks, instruction, mode, backend,
                                reference, kind, workflow, seed, params, hinh_items, thao_tac, anh_sang or "ban-ngay")
        except Exception:
            shutil.rmtree(jdir, ignore_errors=True)
            raise
        job = self.store.create_job({"id": jid, "design_id": did, "rev": rev, "view": view, "render_key": man["renderKey"],
                                     "kind": kind, "mode": mode, "target": req.get("targetLayer"), "backend": backend, "status": "dang-chay",
                                     "request": req})
        self.store.update_job(jid, result={"dir": str(jdir), **({"renderKeyMoi": req["renderKeyMoi"]} if kind == "hinh" else {})})
        try:
            self.export_request(jid)  # request.json tự chứa (chỉ dẫn + ảnh gốc + mask nhúng) cho mọi backend
        except Exception:  # noqa: BLE001 — không chặn job vì lỗi ghi file phụ
            pass
        if preview:
            return self.store.update_job(jid, "cho-gui", {"xemTruoc": True})
        return self._dispatch(job)

    def send(self, jid: str) -> dict:
        """Gửi job đang chờ (đã xem trước) sang backend. Thiết kế đổi hình học/camera sau khi tạo thì từ chối."""
        job = self.store.get_job(jid)
        if job["status"] != "cho-gui":
            raise ValueError(f"Chỉ gửi được job đang chờ gửi (hiện: {job['status']})")
        spec, rev = self.store.get(job["design_id"])
        views = geometry.views_of(spec)
        if job["view"] in views:
            W, H = job["request"]["size"]
            if render.render_key(geometry.compile_spec(spec), views[job["view"]], W, H) != job["render_key"]:
                raise ValueError("Thiết kế đã đổi hình học/góc nhìn sau khi tạo job; mask không còn khớp — hãy tạo job mới")
        if job["backend"] in ("gemini", "goi-job"):  # model nhận chỉ dẫn: request phải đủ ảnh, đúng kích thước
            kt = json.loads(self.export_request(jid).read_text(encoding="utf-8")).get("kiemTra") or {}
            if not kt.get("ok", True):
                raise ValueError("Request chưa đạt kiểm tra, chưa gửi: " + "; ".join(kt.get("loi", [])))
        job = self.store.update_job(jid, "dang-chay")
        return self._dispatch(job)

    @staticmethod
    def _norm_tasks(tasks, target, vat_lieu, instruction) -> list[dict]:
        if not tasks:
            if not target:
                raise ValueError("Cần targetLayer hoặc danh sách tasks")
            tasks = [{"targetLayer": target, "vatLieu": vat_lieu, "instruction": instruction}]
        if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
            raise ValueError(f"tasks phải là danh sách tối đa {MAX_TASKS} việc")
        out = []
        for i, t in enumerate(tasks, 1):
            if not isinstance(t, dict):
                raise ValueError(f"Việc {i} không hợp lệ")
            tl = t.get("targetLayer") or t.get("target") or t.get("target_layer")
            if not tl:
                raise ValueError(f"Việc {i} thiếu targetLayer")
            out.append({"targetLayer": str(tl), "vatLieu": (t.get("vatLieu") or t.get("vat_lieu") or None),
                        "instruction": str(t.get("instruction") or "").strip()})
        return out

    def _prepare(self, jid, jdir, d, spec, rev, scene, man, did, view, tasks, instruction, mode, backend,
                 reference, kind, workflow, seed, params, hinh_items=None, thao_tac=None, anh_sang="ban-ngay") -> dict:
        W, H = man["width"], man["height"]
        req = {"designId": did, "baseRevision": rev, "view": view, "renderKey": man["renderKey"], "kind": kind, "mode": mode,
               "instruction": instruction, "backend": backend,
               "workflow": workflow or {"gen0": "gen0-lineart-depth", "hinh": "inpaint-lineart"}.get(kind, "inpaint"),
               "seed": int(seed if seed is not None else random.randint(1, 2**31 - 1)), "params": params or {},
               "size": [W, H], "preserve": "strict"}
        lines = imaging.read(d / "lines.png", "L")
        Image.fromarray(255 - lines).save(jdir / "lines_inv.png")  # ControlNet lineart: nét trắng nền đen
        shutil.copyfile(d / "depth.png", jdir / "depth.png")
        req["negativePrompt"] = ", ".join(layers.NEGATIVE + realism.NEGATIVE)
        req["anhSang"] = anh_sang  # ánh sáng cho ảnh đầy đủ (gen-0); sửa vùng thì bám ánh sáng ảnh gốc
        if thao_tac:
            req["thaoTac"] = thao_tac
        if kind == "hinh":
            self._prepare_hinh(jdir, d, spec, man, did, view, hinh_items, instruction, reference, req)
        elif kind == "edit":
            cat = layers.catalogue(spec, scene)
            cur = spec
            inst, meta = imaging.load_instances(d)
            present = set(int(v) for v in np.unique(inst))
            visible = {x["id"] for x in meta["instances"] if x["value"] in present}
            owner: dict[str, int] = {}
            union = np.zeros((H, W), bool)
            recs = []
            for i, t in enumerate(tasks, 1):
                layer, ids = layers.resolve(cat, t["targetLayer"])
                if not layer.get("allowAppearanceChange"):
                    raise ValueError(f"Việc {i}: layer '{t['targetLayer']}' bị khóa")
                rec = dict(t)
                if mode == "thiet-ke":
                    if not t["vatLieu"]:
                        raise ValueError(f"Việc {i} ({t['targetLayer']}): chế độ thiet-ke cần vatLieu (vd 'Laminate xanh rêu mờ')")
                    op = layers.design_op(cur, layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0], t["vatLieu"])
                    if op is None:
                        raise ValueError(f"Việc {i}: '{layer['ten']}' chưa sửa được trong thiết kế; dùng chế độ thu-nhanh")
                    nxt = edit.apply_op(cur, op[0])
                    if render.scene_hash(geometry.compile_spec(nxt)) != render.scene_hash(scene):
                        raise ValueError(f"Việc {i}: thao tác làm đổi hình học; sửa ảnh chỉ nhận thay đổi vật liệu")
                    ids = layers.changed_parts(cur, nxt, scene)
                    if not ids:
                        raise ValueError(f"Việc {i}: vật liệu mới trùng vật liệu hiện tại")
                    rec.update(pendingOp=op[0], phamVi=op[1])
                    cur = nxt
                clash = sorted({owner[p] for p in ids if p in owner})
                if clash:
                    both = [p for p in ids if p in owner]
                    raise ValueError(f"Việc {i} và việc {clash[0]} cùng sửa chi tiết {', '.join(both[:4])}; tách layer hoặc gộp thành một việc")
                tmask = imaging.mask_of(d, ids)
                if not tmask.any():
                    raise ValueError(f"Việc {i}: layer '{t['targetLayer']}' không nhìn thấy ở góc '{view}'")
                for p in ids:
                    owner[p] = i
                union |= tmask
                imaging.save_mask(tmask, jdir / f"target_{i}.png")
                imaging.save_mask(imaging.grow(tmask, GROW_PX), jdir / f"mask_{i}.png")
                lay_new = layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0]
                mat = t["vatLieu"] or lay_new.get("vatLieu") or ""
                loai = lay_new.get("loai") or ""
                role_en = layers.VAI_TRO.get(loai, (None, "kitchen element"))[1]
                if loai == "phao":
                    kieu = {m.ma: m.kieu for m in cur.moldings}.get(lay_new.get("module") or "")
                    role_en = _PHAO_EN.get(kieu, role_en)
                rec.update(targetParts=ids, maskPixels=int(tmask.sum()), ten=lay_new.get("ten"),
                           prompt=layers.layer_prompt(cur, lay_new, " ".join(x for x in (t["instruction"], instruction) if x), t["vatLieu"])
                           + ", photorealistic, matching scene lighting and grain, realistic texture, soft contact shadows",
                           roleEn=role_en, viTri=vi_tri(tmask), conLai=self._others(cat, visible, ids, loai),
                           loaiEn=layers.VAI_TRO.get(loai, (None, "element"))[1],
                           materialText=" ".join(x for x in (vocab.tieng_anh(mat), mat and f"({mat})") if x))
                recs.append(rec)
            ref_path, ref_info = self._pick_reference(did, view, man["renderKey"], d, reference)
            ref, _ = imaging.load_rgb(ref_path, (W, H))
            Image.fromarray(ref).save(jdir / "reference.png")
            imaging.save_mask(union, jdir / "target.png")
            region = np.zeros((H, W), bool)
            for i in range(1, len(recs) + 1):
                region |= imaging.read(jdir / f"mask_{i}.png", "L") > 127
            imaging.save_mask(region, jdir / "mask.png")
            self._color_mask(jdir, len(recs))
            marks = [(imaging.read(jdir / f"target_{i}.png", "L") > 127, MAU_VUNG[(i - 1) % len(MAU_VUNG)][1], str(i))
                     for i in range(1, len(recs) + 1)]
            Image.fromarray(imaging.mark_regions(ref, marks, gap=GROW_PX + 2)).save(jdir / "reference_danh_dau.png")
            first = recs[0]
            req.update(tasks=recs, referenceImage=ref_info, maskPixels=int(union.sum()), globalPrompt=layers.global_prompt(cur),
                       targetLayer=first["targetLayer"] + (f" +{len(recs) - 1}" if len(recs) > 1 else ""),
                       # trường cũ (1 việc) giữ để workflow/công cụ cũ đọc được
                       prompt=first["prompt"] if len(recs) == 1 else "; ".join(f"[{k + 1}] {r['prompt']}" for k, r in enumerate(recs)),
                       vatLieu=first["vatLieu"] if len(recs) == 1 else None,
                       targetParts=[p for r in recs for p in r["targetParts"]],
                       phamVi="; ".join(r["phamVi"] for r in recs if r.get("phamVi")) or None)
        else:
            req.update(globalPrompt=layers.global_prompt(spec), anhThat=realism.full(spec, anh_sang),
                       prompt=", ".join(x for x in (layers.global_prompt(spec), realism.tags(spec, anh_sang), instruction.strip()) if x))
        if backend in ("goi-job", "comfyui"):
            backends.load_workflow(req["workflow"])  # tên workflow sai -> báo ngay
        (jdir / "job.json").write_text(json.dumps({"id": jid, **req}, ensure_ascii=False, indent=2), encoding="utf-8")
        return req

    @staticmethod
    def _others(cat: list[dict], visible: set[str], ids: list[str], loai: str) -> int:
        """Số vật CÙNG LOẠI khác vẫn thấy trong ảnh mà không thuộc việc này (để dặn model giữ nguyên chúng)."""
        if not loai or loai in ("module", "tuong", "san"):
            return 0
        mine = set(ids)
        kinds = {loai} | ({"ngan-keo", "canh-kinh"} if loai == "canh" else set())
        rest = [x for x in cat if x["kieu"] == "chi-tiet" and x["loai"] in kinds and x["id"] in visible and x["id"] not in mine]
        if loai == "phao":  # một đường phào gồm nhiều đoạn: đếm theo đường phào
            return len({x["module"] for x in rest})
        return len(rest)

    def _prepare_hinh(self, jdir, d, spec, man, did, view, items, instruction, reference, req) -> None:
        """Áp thao tác hình học lên bản sao thiết kế, render lại ĐÚNG camera cũ, so cũ/mới ra vùng thay đổi.
        Nét/depth gửi model là của thiết kế MỚI; ảnh 'hình mẫu' (màu phẳng + nét) cho model nhận chỉ dẫn."""
        W, H = man["width"], man["height"]
        ops, desc, tt = hinh.build_ops(spec, items)
        nxt = spec
        for op in ops:
            nxt = edit.apply_op(nxt, op)
        pin = hinh.pin_cameras(spec, nxt)
        if pin:
            nxt = edit.apply_op(nxt, pin)
            ops.append(pin)
        design_op = ops[0] if len(ops) == 1 else {"op": "nhieu", "ops": ops}
        render.render_views(nxt, jdir / "moi", [view], W, H, meta={"designId": did, "rev": "chua-ghi"})
        nd = jdir / "moi" / view
        key_new = json.loads((nd / "manifest.json").read_text(encoding="utf-8"))["renderKey"]
        m, info = hinh.diff_mask(d, nd)
        lines_new = imaging.read(nd / "lines.png", "L")
        forced = [ma for x in desc for ma in x.get("batBuoc", [])]
        if forced:  # đổi kiểu cánh: render nhanh không dựng khung -> bắt buộc vẽ lại mặt trước các module đó
            fm, doors = hinh.front_mask(nd, nxt, geometry.compile_spec(nxt), forced)
            m |= fm
            if any(x.get("kieuCanh") == "khung" for x in desc):
                lines_new = hinh.shaker_lines(lines_new, doors)
        if not m.any():
            raise ValueError(f"Thao tác không làm đổi gì nhìn thấy ở góc '{view}'")
        if m.mean() > 0.85:
            raise ValueError("Thao tác đổi gần như toàn ảnh (camera/khung hình đổi?); dùng gen-0 cho thiết kế mới")
        imaging.save_mask(m, jdir / "target_1.png")
        imaging.save_mask(m, jdir / "target.png")
        region = imaging.grow(m, GROW_PX)
        imaging.save_mask(region, jdir / "mask_1.png")
        imaging.save_mask(region, jdir / "mask.png")
        self._color_mask(jdir, 1)
        Image.fromarray(lines_new).save(jdir / "lines_moi.png")
        Image.fromarray(255 - lines_new).save(jdir / "lines_inv.png")  # ControlNet: nét của thiết kế MỚI
        shutil.copyfile(nd / "depth.png", jdir / "depth.png")
        Image.fromarray(hinh.preview(nd, lines_new)).save(jdir / "hinh_moi.png")
        ref_path, ref_info = self._pick_reference(did, view, man["renderKey"], d, reference)
        ref, _ = imaging.load_rgb(ref_path, (W, H))
        Image.fromarray(ref).save(jdir / "reference.png")
        Image.fromarray(imaging.mark_regions(ref, [(m, MAU_VUNG[0][1], "1")], gap=GROW_PX + 2)).save(jdir / "reference_danh_dau.png")
        en = "; ".join(x["en"] for x in desc)
        vi = "; ".join(x["vi"] for x in desc)
        chung = layers.global_prompt(nxt)
        task = {"targetLayer": "hinh", "ten": vi, "roleEn": en, "viTri": vi_tri(m), "instruction": instruction, "vatLieu": None,
                "thaoTac": tt, "targetParts": info["chiTiet"], "maskPixels": int(m.sum()),
                "prompt": ", ".join(x for x in (en, instruction, chung, realism.tags(nxt, req.get("anhSang") or "ban-ngay")) if x)}
        if "thaoTac" not in req:  # trọng số mặc định theo thao tác suy ra (params người dùng vẫn ghi đè)
            req["params"] = {**hinh.THAO_TAC[tt]["params"], **req["params"]}
        req.update(hinhGoc=items, tasks=[task], designOp=design_op, moTa=desc, thaoTac=req.get("thaoTac") or tt, renderKeyMoi=key_new,
                   khacBiet=info, ghimCamera=bool(pin), referenceImage=ref_info, maskPixels=int(m.sum()), globalPrompt=chung,
                   targetLayer=f"hinh: {vi}"[:120], prompt=task["prompt"], targetParts=info["chiTiet"], phamVi=vi, instruction="")
        if instruction:
            task["instruction"] = instruction

    @staticmethod
    def _color_mask(jdir: Path, n: int) -> None:
        """Ảnh mask màu (mỗi việc một màu) để mô tả nhiều vùng cho model nhận chỉ dẫn (Gemini, sửa tay)."""
        first = imaging.read(jdir / "mask_1.png", "L")
        out = np.zeros((*first.shape, 3), np.uint8)
        for i in range(1, n + 1):
            m = imaging.read(jdir / f"target_{i}.png", "L") > 127
            out[m] = MAU_VUNG[(i - 1) % len(MAU_VUNG)][1]
        Image.fromarray(out).save(jdir / "mask_mau.png")

    def _pick_reference(self, did, view, key, d, reference):
        if reference in (None, "", "auto"):
            return self._reference(did, view, key, d)
        if reference == "albedo":
            return d / "albedo.png", {"loai": "albedo"}
        if reference == "beauty":
            if not (d / "beauty.png").exists():
                raise ValueError("Chưa có ảnh render three.js cho góc này (mở trang render.html, chọn thiết kế, bấm Render)")
            return d / "beauty.png", {"loai": "beauty"}
        j = self.store.get_job(reference)
        if j["design_id"] != did or j["view"] != view:
            raise ValueError("Ảnh gốc thuộc thiết kế/góc nhìn khác")
        if self._key_of(j) != key:
            raise ValueError("Ảnh gốc thuộc hình học/camera khác (renderKey lệch); hãy dùng ảnh mới hoặc albedo")
        if j["status"] not in ("da-chap-nhan", "can-duyet"):
            raise ValueError(f"Job {reference} chưa có ảnh dùng được (trạng thái {j['status']})")
        return Path(j["result"]["dir"]) / "composite.png", {"loai": "job", "jobId": j["id"]}

    # ------------------------------------------------------------------ chạy backend
    def _dispatch(self, job: dict) -> dict:
        jid, b = job["id"], job["backend"]
        jdir = Path(self.store.get_job(jid)["result"]["dir"])
        req = job["request"]
        try:
            if b == "to-mau" and req["kind"] == "hinh":  # không AI: dán hình mẫu (màu phẳng + nét) vào vùng đổi để xem nhanh
                shutil.copyfile(jdir / "hinh_moi.png", jdir / "raw.png")
                return self._finish(jid, {"backend": {"ten": "to-mau", "hinhMau": True}})
            if b == "to-mau":
                img = imaging.read(jdir / "reference.png", "RGB")
                used = []
                for i, t in enumerate(req["tasks"], 1):
                    rgb = vocab.mau(t.get("vatLieu") or "") or vocab.mau(t.get("instruction") or "")
                    if not rgb:
                        raise BackendError("khong-ho-tro", f"Việc {i} ({t['targetLayer']}): không suy được màu từ vật liệu/yêu cầu; "
                                                           "ghi rõ màu (vd 'xanh rêu') hoặc dùng backend AI")
                    img = imaging.recolor(img, imaging.read(jdir / f"target_{i}.png", "L") > 127, vocab.hex_rgb(rgb))
                    used.append(rgb)
                Image.fromarray(img).save(jdir / "raw.png")
                return self._finish(jid, {"backend": {"ten": "to-mau", "mau": used}})
            if b == "goi-job":
                return self._export_package(jid, jdir, req)
            if b in ("comfyui", "gemini"):
                fn = self._run_comfy if b == "comfyui" else self._run_gemini
                t = threading.Thread(target=fn, args=(jid, jdir, req), daemon=True, name=jid)
                self._threads[jid] = t
                t.start()
                return self.store.get_job(jid)
        except BackendError as e:
            return self.store.update_job(jid, f"loi:{e.code}", error=str(e))
        raise ValueError(b)

    def _values(self, req: dict, wf: dict) -> dict:
        W, H = req["size"]
        return {**wf.get("kitchen", {}).get("macDinh", {}), **req.get("params", {}),
                "prompt": req["prompt"], "negative": req["negativePrompt"], "seed": req["seed"], "width": W, "height": H}

    def _export_package(self, jid: str, jdir: Path, req: dict) -> dict:
        wf = backends.load_workflow(req["workflow"])
        tasks = req.get("tasks") or []
        if len(tasks) > 1:
            return self._export_package_multi(jid, jdir, req, wf, tasks)
        imgs = {k: f"{jid}_{k}.png" for k in wf["kitchen"].get("anh", [])}
        files = {"reference": "reference.png", "mask": "mask.png", "lines": "lines_inv.png", "depth": "depth.png"}
        for k, name in imgs.items():
            shutil.copyfile(jdir / files[k], jdir / name)
        prompt = backends.build_prompt(wf, imgs, self._values(req, wf))
        (jdir / "workflow_api.json").write_text(json.dumps(prompt, ensure_ascii=False, indent=1), encoding="utf-8")
        (jdir / "HUONG-DAN.txt").write_text(
            f"Job {jid} ({req['kind']}, workflow {req['workflow']})\n"
            f"1. Chép {', '.join(imgs.values())} vào thư mục input của ComfyUI.\n"
            "2. ComfyUI > Workflow > Open (hoặc kéo thả) workflow_api.json, sửa tên model nếu cần, bấm Queue.\n"
            f"3. Nộp ảnh kết quả: web (nút Nộp ảnh) hoặc MCP submit_image_result('{jid}', đường_dẫn_ảnh).\n"
            f"Prompt: {req['prompt']}\nNegative: {req['negativePrompt']}\n", encoding="utf-8")
        return self.store.update_job(jid, "cho-ket-qua", {"goi": sorted(p.name for p in jdir.iterdir())})

    def _export_package_multi(self, jid, jdir, req, wf, tasks) -> dict:
        files = {"lines": "lines_inv.png", "depth": "depth.png"}
        steps = []
        for i, t in enumerate(tasks, 1):
            imgs = {}
            for k in wf["kitchen"].get("anh", []):
                if k == "reference":
                    imgs[k] = f"{jid}_reference.png" if i == 1 else f"{jid}_ket_qua_{i - 1}.png"
                elif k == "mask":
                    imgs[k] = f"{jid}_mask_{i}.png"
                    shutil.copyfile(jdir / f"mask_{i}.png", jdir / imgs[k])
                else:
                    imgs[k] = f"{jid}_{k}.png"
                    shutil.copyfile(jdir / files[k], jdir / imgs[k])
            vals = {**self._values(req, wf), "prompt": t["prompt"], "seed": req["seed"] + i - 1}
            name = f"workflow_api_{i}.json"
            (jdir / name).write_text(json.dumps(backends.build_prompt(wf, imgs, vals), ensure_ascii=False, indent=1), encoding="utf-8")
            steps.append(f"  Việc {i} [{MAU_VUNG[(i - 1) % 8][0]}] {t['targetLayer']}: {name}, ảnh vào {imgs.get('reference', '-')}, "
                         f"lưu ảnh ra thành {jid}_ket_qua_{i}.png\n     Prompt: {t['prompt']}")
        shutil.copyfile(jdir / "reference.png", jdir / f"{jid}_reference.png")
        (jdir / "HUONG-DAN.txt").write_text(
            f"Job {jid}: {len(tasks)} việc, workflow {req['workflow']}\n"
            "Cách 1 (ComfyUI): chép các file PNG vào thư mục input, chạy lần lượt từng workflow; ảnh ra của việc trước là ảnh vào của việc sau.\n"
            + "\n".join(steps) +
            "\nCách 2 (công cụ sửa theo chỉ dẫn): dùng reference.png + mask_mau.png, mỗi màu là một việc như trên.\n"
            f"Nộp ẢNH CUỐI (đã đủ mọi việc): web (nút Nộp ảnh) hoặc MCP submit_image_result('{jid}', đường_dẫn_ảnh).\n",
            encoding="utf-8")
        return self.store.update_job(jid, "cho-ket-qua", {"goi": sorted(p.name for p in jdir.iterdir())})

    def _ai_input(self, job: dict, jdir: Path, req: dict) -> tuple[str, list[tuple[str, Path]]]:
        """Chỉ dẫn dạng câu + ảnh gửi model nhận chỉ dẫn (Gemini, gói request). Một nguồn cho cả gọi API lẫn file xuất."""
        if req["kind"] == "gen0":
            d = self._render_dir(job["design_id"], job["rev"], job["view"])
            src = d / "beauty.png" if (d / "beauty.png").exists() else d / "albedo.png"
            spec, _ = self.store.get(job["design_id"], job["rev"])
            real = req.get("anhThat") or realism.full(spec, req.get("anhSang") or "ban-ngay")
            return backends.gemini_text("gen0", "", req.get("instruction", ""), req["globalPrompt"], realism=real), [("anh-dau-vao", src)]
        if req["kind"] == "hinh":
            t = req["tasks"][0]
            text = backends.gemini_text_hinh(req.get("thaoTac") or t.get("thaoTac") or "thay-vat", [x["en"] for x in req.get("moTa", [])],
                                             (t.get("viTri") or {}).get("en"), t.get("instruction") or "", self._local_real(job))
            return text, [("anh-goc-danh-dau", jdir / "reference_danh_dau.png"), ("mask", jdir / "mask.png"),
                          ("hinh-moi", jdir / "hinh_moi.png")]
        tasks = req["tasks"]
        multi = len(tasks) > 1
        marked = jdir / "reference_danh_dau.png"
        if not marked.exists():  # job tạo trước khi có ảnh đánh dấu
            ref = imaging.read(jdir / "reference.png", "RGB")
            marks = [(imaging.read(jdir / f"target_{i}.png", "L") > 127, MAU_VUNG[(i - 1) % len(MAU_VUNG)][1], str(i))
                     for i in range(1, len(tasks) + 1) if (jdir / f"target_{i}.png").exists()]
            Image.fromarray(imaging.mark_regions(ref, marks, gap=GROW_PX + 2)).save(marked)
        regions = []
        for i, t in enumerate(tasks, 1):
            extra = " ".join(x for x in (t.get("instruction"), None if multi else req.get("instruction")) if x)
            regions.append({"n": i, "color": MAU_VUNG[(i - 1) % len(MAU_VUNG)][0], "role": t.get("roleEn") or "kitchen element",
                            "mat": t.get("materialText") or t["prompt"], "extra": extra,
                            "where": (t.get("viTri") or {}).get("en"), "others": t.get("conLai") or 0,
                            "kind": t.get("loaiEn") or t.get("roleEn") or "element"})
        text = backends.gemini_text_edit(regions, req.get("instruction", "") if multi else "", self._local_real(job))
        return text, [("anh-goc-danh-dau", marked), ("mask-mau" if multi else "mask", jdir / ("mask_mau.png" if multi else "mask.png"))]

    def _local_real(self, job: dict) -> str:
        """Yêu cầu ảnh thật khi sửa vùng; vật liệu lấy theo thiết kế sau sửa nếu có (sửa hình) để mô tả bề mặt đúng."""
        spec, _ = self.store.get(job["design_id"], job["rev"])
        op = job["request"].get("designOp")
        if op:
            try:
                spec = edit.apply_op(spec, op)
            except Exception:  # noqa: BLE001
                pass
        if op:
            return realism.local(spec)
        mats = [t.get("vatLieu") for t in job["request"].get("tasks") or [] if t.get("vatLieu")]
        return realism.local(None, mats)

    def export_request(self, jid: str) -> Path:
        """Xuất request gửi AI, đã LỌC bỏ thông tin hệ thống AI không dùng (renderKey, id chi tiết, số pixel, prompt kiểu tag…).

        - request.json        : bản gọn cho người / AI đọc: chỉ dẫn, danh sách việc, ảnh đính kèm theo thứ tự (base64 để xem, lưu).
        - gemini-request.json : thân request Gemini API (generateContent): ảnh ở phần inline_data -> Gemini TỰ GIẢI MÃ và dùng ảnh.
        - anh-1-*.png, anh-2-*.png + GUI-GEMINI-WEB.txt : cho Gemini web / chat: đính kèm ảnh theo thứ tự + dán chỉ dẫn.
        Chat AI KHÔNG tự giải mã chuỗi base64 dán dưới dạng chữ, nên với giao diện chat phải đính kèm file ảnh.
        Thông tin đầy đủ để truy vết vẫn ở job.json (không gửi AI)."""
        import base64
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        req = job["request"]
        text, imgs = self._ai_input(job, jdir, req)
        size = tuple(req["size"])
        ten_anh = {"anh-goc": "anh goc can sua", "anh-goc-danh-dau": "anh goc can sua, vung sua co vien mau + so",
                   "mask": "mask (trang = vung sua)", "hinh-moi": "hinh mau thiet ke moi (mau phang + net, chi de lay hinh)", "mask-mau": "mask mau (moi mau mot viec)", "anh-dau-vao": "anh dau vao"}
        for old in jdir.glob("anh-*.png"):  # bỏ bản đánh số của lần xuất trước (tên vai trò có thể đã đổi)
            old.unlink()
        dinh_kem = []
        for k, (role, pth) in enumerate(imgs, 1):
            fname = f"anh-{k}-{role}.png"
            shutil.copyfile(pth, jdir / fname)
            dinh_kem.append({"thuTu": k, "vaiTro": role, "moTa": ten_anh.get(role, role), "file": fname,
                             "dataUrl": "data:image/png;base64," + base64.b64encode(pth.read_bytes()).decode()})
        viec = []
        for i, t in enumerate(req.get("tasks") or [], 1):
            vt = t.get("viTri") or {}
            viec.append({k: v for k, v in {
                "viec": i, "nhan": str(i), "mauVien": MAU_VUNG[(i - 1) % len(MAU_VUNG)][0],
                "mauVung": MAU_VUNG[(i - 1) % len(MAU_VUNG)][0] if len(req["tasks"]) > 1 else "WHITE",
                "ten": t.get("ten"), "doiTuong": t.get("roleEn"), "viTri": vt.get("vi"), "khungPhanTram": vt.get("khung"),
                "vatCungLoaiGiuNguyen": t.get("conLai"),
                "vatLieu": t.get("vatLieu"), "tiengAnh": t.get("materialText"), "yeuCau": t.get("instruction")}.items() if v})
        lean = {
            "schema": "kitchen-ai-edit-request/2.0",
            "jobId": jid,
            "loai": {"hinh": "hinh", "gen0": "gen0"}.get(req["kind"], "vat-lieu"),
            **({"thaoTac": req["thaoTac"]} if req.get("thaoTac") else {}),
            "cachDung": ("Gemini API: gửi nguyên file gemini-request.json (ảnh trong inline_data được Gemini tự giải mã). "
                         "Gemini web / chat: đính kèm các ảnh trong 'anhDinhKem' ĐÚNG THỨ TỰ rồi dán 'chiDan' — "
                         "không dán chuỗi base64 vào khung chat (AI sẽ đọc như chữ, không thấy ảnh)."),
            "chiDan": text,
            "anhDinhKem": dinh_kem,
            "viec": viec,
            "khongDuoc": req.get("negativePrompt"),
            "kichThuoc": list(size),
        }
        lean["kiemTra"] = request_check.check_lean(lean)
        (jdir / "request.json").write_text(json.dumps(lean, ensure_ascii=False, indent=1), encoding="utf-8")
        (jdir / "gemini-request.json").write_text(json.dumps(backends.gemini_body(text, [p for _, p in imgs], size),
                                                             ensure_ascii=False), encoding="utf-8")
        steps = "\n".join(f"  {d['thuTu']}. {d['file']}  ({d['moTa']})" for d in dinh_kem)
        kt = lean["kiemTra"]
        canh = "".join(f"  ! {x}\n" for x in kt["loi"] + kt["canhBao"])
        (jdir / "GUI-GEMINI-WEB.txt").write_text(
            f"Job {jid} — gửi bằng Gemini web (không cần API)\n"
            + (f"KIỂM TRA: {'đạt' if kt['ok'] else 'CHƯA ĐẠT — sửa trước khi gửi'}\n{canh}" )
            + "\nKHÔNG dán file JSON vào khung chat: chat AI đọc base64 như chữ (thường bị cắt) và không thấy ảnh.\n"
            f"1. Mở gemini.google.com, đính kèm ĐÚNG THỨ TỰ các ảnh (dạng file ảnh):\n{steps}\n"
            "   Ảnh 1 có viền màu + số quanh vùng cần sửa; ảnh 2 là mask của đúng vùng đó.\n"
            "2. Dán nguyên đoạn chỉ dẫn dưới đây (chỉ phần chữ) rồi gửi:\n\n"
            f"{text}\n\nKhông được: {req.get('negativePrompt')}\n\n"
            "3. Tải ảnh kết quả, nộp lại ở tab Sửa ảnh theo lớp > job > Nộp ảnh.\n", encoding="utf-8")
        return jdir / "request.json"

    def export_full(self, jid: str) -> Path:
        """Bản ĐẦY ĐỦ để kiểm tra (không gửi AI): toàn bộ yêu cầu nội bộ (renderKey, chi tiết bị sửa, thao tác thiết kế chờ ghi,
        prompt từng việc…), trạng thái job, kết quả/báo cáo nếu có, và mọi ảnh của job nhúng base64 (ảnh gốc, mask, mask màu,
        mask đích + mask nở của từng việc, ảnh AI thô, ảnh ghép)."""
        import base64
        self.export_request(jid)  # bảo đảm các file gửi AI đã có
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        anh = {}
        for f in sorted(jdir.glob("*.png")):
            if f.name.startswith(("anh-", f"{jid}_")):  # bản sao đánh số / tên upload: trùng nội dung, bỏ cho gọn
                continue
            anh[f.stem] = "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()
        res = {k: v for k, v in job["result"].items() if k != "dir"}
        out = {"schema": "kitchen-ai-edit-request-full/1.0",
               "ghiChu": "Bản đầy đủ để kiểm tra — KHÔNG gửi AI (gửi request.json / gemini-request.json).",
               "job": {k: job[k] for k in ("id", "status", "kind", "mode", "backend", "design_id", "rev", "view", "render_key",
                                           "target", "created_at", "updated_at", "error")},
               "yeuCau": job["request"], "ketQua": res, "anh": anh,
               "fileGuiAI": ["request.json", "gemini-request.json", "GUI-GEMINI-WEB.txt"]}
        p = jdir / "request.full.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def _run_gemini(self, jid: str, jdir: Path, req: dict):
        try:
            cli = backends.Gemini()
            job = self.store.get_job(jid)
            text, named = self._ai_input(job, jdir, req)
            images = [p for _, p in named]
            self.store.update_job(jid, result={"geminiPrompt": text})
            info = cli.generate(text, images, jdir / "raw.png", tuple(req["size"]))
            self._finish(jid, {"backend": {"ten": "gemini", **info}})
        except BackendError as e:
            self.store.update_job(jid, f"loi:{e.code}", error=str(e))
        except Exception as e:  # noqa: BLE001
            self.store.update_job(jid, "loi:sinh-that-bai", error=f"{type(e).__name__}: {e}")

    def _run_comfy(self, jid: str, jdir: Path, req: dict):
        try:
            wf = backends.load_workflow(req["workflow"])
            cli = backends.ComfyUI()
            tasks = req.get("tasks") or []
            if req["kind"] == "edit" and len(tasks) > 1:  # nhiều việc: chạy nối tiếp, ảnh ghép của việc trước làm ảnh vào việc sau
                cur = imaging.read(jdir / "reference.png", "RGB")
                infos = []
                for i, t in enumerate(tasks, 1):
                    Image.fromarray(cur).save(jdir / f"vao_{i}.png")
                    src = {"reference": f"vao_{i}.png", "mask": f"mask_{i}.png", "lines": "lines_inv.png", "depth": "depth.png"}
                    imgs = {k: cli.upload(jdir / src[k], f"{jid}_{i}_{k}.png") for k in wf["kitchen"].get("anh", [])}
                    vals = {**self._values(req, wf), "prompt": t["prompt"], "seed": req["seed"] + i - 1}
                    infos.append(cli.run(backends.build_prompt(wf, imgs, vals), jdir / f"raw_{i}.png"))
                    raw_i, _ = imaging.load_rgb(jdir / f"raw_{i}.png", tuple(req["size"]))
                    cur = imaging.composite(cur, raw_i, imaging.alpha(imaging.read(jdir / f"target_{i}.png", "L") > 127, FEATHER_PX))
                Image.fromarray(cur).save(jdir / "raw.png")
                return self._finish(jid, {"backend": {"ten": "comfyui", "url": cli.url, "workflow": req["workflow"], "buoc": infos}})
            files = {"reference": "reference.png", "mask": "mask.png", "lines": "lines_inv.png", "depth": "depth.png"}
            imgs = {k: cli.upload(jdir / files[k], f"{jid}_{k}.png") for k in wf["kitchen"].get("anh", [])}
            info = cli.run(backends.build_prompt(wf, imgs, self._values(req, wf)), jdir / "raw.png")
            self._finish(jid, {"backend": {"ten": "comfyui", "url": cli.url, "workflow": req["workflow"], **info}})
        except BackendError as e:
            self.store.update_job(jid, f"loi:{e.code}", error=str(e))
        except Exception as e:  # noqa: BLE001 — job không được treo ở dang-chay
            self.store.update_job(jid, "loi:sinh-that-bai", error=f"{type(e).__name__}: {e}")

    def wait(self, jid: str, timeout: float = 60) -> dict:
        t = self._threads.get(jid)
        if t:
            t.join(timeout)
        return self.store.get_job(jid)

    # ------------------------------------------------------------------ kết quả
    def submit_result(self, jid: str, image: bytes) -> dict:
        job = self.store.get_job(jid)
        if job["status"] in ("da-chap-nhan", "tu-choi", "dang-chay"):
            raise ValueError(f"Job đang ở trạng thái {job['status']}, không nhận ảnh")
        jdir = Path(job["result"]["dir"])
        import io
        try:
            im = Image.open(io.BytesIO(image)).convert("RGB")
        except Exception:
            raise ValueError("Ảnh nộp không đọc được (cần PNG/JPEG)")
        im.save(jdir / "raw.png")
        return self._finish(jid, {"backend": {"ten": job["backend"], "nopTay": True}})

    def _finish(self, jid: str, extra: dict) -> dict:
        job = self.store.get_job(jid)
        jdir = Path(job["result"]["dir"])
        req = job["request"]
        W, H = req["size"]
        raw, resized = imaging.load_rgb(jdir / "raw.png", (W, H))
        if job["kind"] == "gen0":
            Image.fromarray(raw).save(jdir / "composite.png")
            rep = {"kieu": "gen0", "doiKichThuoc": resized}
            lp = self._render_dir(job["design_id"], job["rev"], job["view"]) / "lines.png"
            if lp.exists():
                rep["khopNet"] = imaging.edge_alignment(raw, imaging.read(lp, "L"))
                if rep["khopNet"].get("khop") is False:
                    rep["canhBao"] = "Ảnh AI có vẻ lệch hình học so với bản vẽ: mask các lần sửa sau có thể không khớp"
            (jdir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
            return self.store.update_job(jid, "can-duyet", {**extra, "report": rep}, error=rep.get("canhBao"))
        ref = imaging.read(jdir / "reference.png", "RGB")
        lines_p = jdir / "lines_moi.png" if (jdir / "lines_moi.png").exists() else \
            self._render_dir(job["design_id"], job["rev"], job["view"]) / "lines.png"  # sửa hình: so biên với nét MỚI
        lines = imaging.read(lines_p, "L") if lines_p.exists() else None
        tasks = req.get("tasks") or [{"targetLayer": job["target"]}]
        comp = ref.copy()
        per = []
        raws = []
        for i, t in enumerate(tasks, 1):
            tp, mp = jdir / f"target_{i}.png", jdir / f"mask_{i}.png"
            if not tp.exists():  # job cũ (trước khi có nhiều việc)
                tp, mp = jdir / "target.png", jdir / "mask.png"
            raw_i, _ = imaging.load_rgb(jdir / f"raw_{i}.png", (W, H)) if (jdir / f"raw_{i}.png").exists() else (raw, resized)
            tm = imaging.read(tp, "L") > 127
            comp = imaging.composite(comp, raw_i, imaging.alpha(tm, FEATHER_PX))
            raws.append((raw_i, tm, imaging.read(mp, "L") > 127))
        Image.fromarray(comp).save(jdir / "composite.png")
        for i, (t, (raw_i, tm, region)) in enumerate(zip(tasks, raws), 1):
            c = imaging.check(ref, raw_i, comp, tm, region, lines)
            per.append({"viec": i, "targetLayer": t["targetLayer"], "maskPixels": int(tm.sum()), "trongMask": c["trongMask"],
                        **({"bien": c["bien"]} if "bien" in c else {}), "anhTho": c["anhTho"]})
        union = imaging.read(jdir / "target.png", "L") > 127
        region_all = imaging.read(jdir / "mask.png", "L") > 127
        overall = imaging.check(ref, raw, comp, union, region_all, lines)
        rep = {"kieu": "edit", "doiKichThuoc": resized, "renderKey": job["render_key"], "rev": job["rev"],
               "targetLayer": job["target"], "maskPixels": int(union.sum()), "cheDoBaoToan": "strict", **overall, "viec": per}
        khong_doi = [p["viec"] for p in per if not p["trongMask"]["coThayDoi"]]
        if khong_doi and len(khong_doi) == len(per):
            rep["canhBao"] = "Vùng đích gần như không đổi — model có thể đã bỏ qua mask/prompt"
        elif khong_doi:
            rep["canhBao"] = f"Việc {', '.join(map(str, khong_doi))} gần như không đổi; các việc khác đã đổi"
        ok = rep["ngoaiMask"]["datBaoToan"] and len(khong_doi) < len(per)
        status = "can-duyet" if ok else "loi:khong-dat-kiem-tra"
        (jdir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.store.update_job(jid, status, {**extra, "report": rep}, error=rep.get("canhBao"))

    # ------------------------------------------------------------------ duyệt
    def accept(self, jid: str, ap_vao_thiet_ke: bool = False, base_rev: int | None = None) -> dict:
        import datetime as _dt
        job = self.store.get_job(jid)
        if job["status"] != "can-duyet":
            raise ValueError(f"Chỉ chấp nhận job đang cần duyệt (hiện: {job['status']})")
        req = job["request"]
        thiet_ke = None
        if job["kind"] == "hinh":  # sửa hình: ảnh chỉ đúng khi thiết kế đổi theo -> luôn ghi rev
            res = self.svc.apply(job["design_id"], req["designOp"], base_rev if base_rev is not None else job["rev"], f"image-job:{jid}")
            W, H = req["size"]
            _, _, _, _, man = self.ensure_render(job["design_id"], res["rev"], job["view"], W, H)
            if man["renderKey"] != req["renderKeyMoi"]:
                raise ValueError("Render của rev mới lệch hình mẫu của job (renderKey khác) — báo lỗi cho nhà phát triển")
            thiet_ke = {"rev": res["rev"], "op": req["designOp"], "phamVi": req.get("phamVi")}
        elif job["mode"] == "thiet-ke" or ap_vao_thiet_ke:
            tasks = req.get("tasks") or [{"targetLayer": job["target"], "vatLieu": req.get("vatLieu"),
                                          "pendingOp": req.get("pendingOp"), "phamVi": req.get("phamVi")}]
            ops, pham_vi, bo_qua = [], [], []
            spec, _ = self.store.get(job["design_id"])
            scene = geometry.compile_spec(spec)
            cur = spec
            for i, t in enumerate(tasks, 1):
                op, pv = t.get("pendingOp"), t.get("phamVi")
                if op is None:
                    if not t.get("vatLieu"):
                        bo_qua.append(f"việc {i}: không nêu vật liệu")
                        continue
                    r = layers.design_op(cur, layers.resolve(layers.catalogue(cur, scene), t["targetLayer"])[0], t["vatLieu"])
                    if r is None:
                        bo_qua.append(f"việc {i}: layer chưa sửa được trong thiết kế")
                        continue
                    op, pv = r
                cur = edit.apply_op(cur, op)
                ops.append(op)
                pham_vi.append(pv)
            if not ops:
                raise ValueError("Không có việc nào áp được vào thiết kế (" + "; ".join(bo_qua) + ")")
            op = ops[0] if len(ops) == 1 else {"op": "nhieu", "ops": ops}
            res = self.svc.apply(job["design_id"], op, base_rev if base_rev is not None else job["rev"], f"image-job:{jid}")
            thiet_ke = {"rev": res["rev"], "op": op, "phamVi": "; ".join(pham_vi), **({"boQua": bo_qua} if bo_qua else {})}
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        return self.store.update_job(jid, "da-chap-nhan", {"chapNhanLuc": now, **({"thietKe": thiet_ke} if thiet_ke else {})})

    def reject(self, jid: str) -> dict:
        job = self.store.get_job(jid)
        if job["status"] == "da-chap-nhan":
            raise ValueError("Job đã chấp nhận")
        return self.store.update_job(jid, "tu-choi")

    def regenerate(self, jid: str, seed: int | None = None) -> dict:
        j = self.store.get_job(jid)
        r = j["request"]
        ref = r.get("referenceImage") or {}
        if j["kind"] == "hinh":
            return self.create(j["design_id"], j["view"], None, (r.get("tasks") or [{}])[0].get("instruction") or "", "thiet-ke", None,
                               j["backend"], ref.get("jobId") or (ref.get("loai") if ref.get("loai") in ("albedo", "beauty") else None),
                               None, "hinh", r.get("workflow"), seed, r.get("params"), None, bool(j["result"].get("xemTruoc")),
                               r.get("hinhGoc"), r.get("thaoTac"), r.get("anhSang"))
        tasks = [{k: t.get(k) for k in ("targetLayer", "vatLieu", "instruction")} for t in r.get("tasks") or []] or None
        return self.create(j["design_id"], j["view"], None if tasks else r.get("targetLayer"), r.get("instruction", ""), j["mode"],
                           None if tasks else r.get("vatLieu"), j["backend"],
                           ref.get("jobId") or (ref.get("loai") if ref.get("loai") in ("albedo", "beauty") else None), None, j["kind"],
                           r.get("workflow"), seed, r.get("params"), tasks, bool(j["result"].get("xemTruoc")),
                           None, None, r.get("anhSang"))

    def get(self, jid: str) -> dict:
        return self.store.get_job(jid)

    def list(self, did: str | None = None, view: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        return self.store.list_jobs(did, view, status, limit)
