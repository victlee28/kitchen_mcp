"""Image editing jobs: layers, masks, strict compositing, validation and review."""
from __future__ import annotations

import base64
import io
import dataclasses
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import geometry, imaging, layers, prompts, render, threejs_export  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import load_spec  # noqa: E402
from kitchen.store import ConflictError  # noqa: E402

FIX = ROOT / "fixtures" / "l-shaped-kitchen.json"
VIEW = "original-angle"


def _spec():
    return load_spec(json.loads(FIX.read_text(encoding="utf-8")))


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="imgjob-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        cls.did = cls.svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        cls.svc.images.ensure_render(cls.did, None, VIEW, 640, 480)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestInstanceAndLayers(_Base):
    def test_instance_matches_pid_and_manifest(self):
        d = self.tmp / "renders" / self.did / "rev1" / VIEW
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((man["width"], man["height"]), (640, 480))
        for f in ("instance.png", "instances.json", "albedo.png"):
            self.assertIn(f, man["files"])
        inst, meta = imaging.load_instances(d)
        self.assertEqual(inst.shape, (480, 640))
        ids = [i["id"] for i in meta["instances"]]
        self.assertEqual(len(ids), len(set(ids)), "ID chi tiết không trùng")
        self.assertEqual(sum(i["pixels"] for i in meta["instances"]), int((inst > 0).sum()))

    def test_two_doors_same_module_disjoint(self):
        d = self.tmp / "renders" / self.did / "rev1" / VIEW
        a, b = imaging.mask_of(d, ["TD1-door-1"]), imaging.mask_of(d, ["TD1-door-2"])
        self.assertTrue(a.any() and b.any())
        self.assertFalse((a & b).any())
        g = imaging.mask_of(d, ["TD1-door-1", "TD1-door-2"])
        self.assertEqual(int(g.sum()), int(a.sum() + b.sum()))

    def test_render_key_ignores_material(self):
        s = _spec()
        s2 = s.model_copy(deep=True)
        s2.common.material["base"] = "Laminate xanh rêu"
        v = geometry.views_of(s)[VIEW]
        k1 = render.render_key(geometry.compile_spec(s), v, 640, 480)
        k2 = render.render_key(geometry.compile_spec(s2), v, 640, 480)
        self.assertEqual(k1, k2)
        s3 = s.model_copy(deep=True)
        s3.module[1].height += 10
        self.assertNotEqual(k1, render.render_key(geometry.compile_spec(s3), v, 640, 480))

    def test_catalogue_ids_unique_and_refs_valid(self):
        s = _spec()
        cat = layers.catalogue(s, geometry.compile_spec(s))
        ids = [x["id"] for x in cat]
        self.assertEqual(len(ids), len(set(ids)))
        singles = {x["id"] for x in cat if x["variant"] == "part"}
        for g in cat:
            for t in g.get("component") or []:
                self.assertIn(t, singles)

    def test_layers_api_and_pick(self):
        r = self.svc.images.layers(self.did, VIEW)
        self.assertEqual(r["baseImage"]["type"], "albedo")
        lid = {x["id"]: x for x in r["layers"]}
        self.assertIn("frontSections:TD1", lid)
        self.assertEqual(lid["TD1-door-1"]["designEdit"], "cả mặt trước module TD1")
        inst = imaging.mask_of(Path(r["dir"]), ["TD1-door-1"])
        ys, xs = np.nonzero(inst)
        p = self.svc.images.pick(self.did, VIEW, int(xs[len(xs) // 2]), int(ys[len(ys) // 2]))
        self.assertEqual(p["part"]["id"], "TD1-door-1")
        self.assertIn("frontSections:TD1", p["layers"])

    def test_threejs_sourceref_points_to_compiled_parts(self):
        s = _spec()
        doc = threejs_export.export(s, "x", 1)
        part_ids = {p.id for p in geometry.compile_spec(s).parts}
        refs = [d["sourceRef"] for m in doc["modules"] for d in m["doors"] + m["drawers"] + m["parts"]]
        self.assertTrue(refs)
        self.assertTrue(set(refs) <= part_ids)
        self.assertIn("instance", doc["renderSettings"]["controlPasses"])


class TestImageJobsIsIndependent(unittest.TestCase):
    def test_it_does_not_import_or_hold_the_service(self):
        import ast
        src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "kitchen" / "images").glob("*.py")))
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.ImportFrom):
                mods |= {n.module or ""} | {a.name for a in n.names}
        self.assertNotIn("service", mods)
        self.assertNotIn("self.svc", src)

    def test_it_runs_with_only_a_store_a_render_dir_and_an_apply_callback(self):
        from kitchen.images import ImageJobs
        svc = KitchenService(Path(tempfile.mkdtemp()) / "k.db", Path(tempfile.mkdtemp()))
        calls = []
        jobs = ImageJobs(svc.store, svc.render_dir, lambda *a: calls.append(a) or {"rev": 2})
        self.assertEqual(jobs.list(), [])
        self.assertEqual(jobs.render_dir, svc.render_dir)
        self.assertIsNot(jobs, svc.images)


class TestImageJobs(_Base):
    def test_quick_edit_strict_composite(self):
        rev0 = self.svc.store.get(self.did)[1]
        j = self.svc.images.create(self.did, VIEW, "TD1-door-1", mode="quick", material="Laminate xanh rêu mờ")
        self.assertEqual(j["status"], "needs-review")
        rep = j["result"]["report"]
        self.assertTrue(rep["outsideMask"]["setPreserve"])
        self.assertTrue(rep["insideMask"]["changed"])
        d = Path(j["result"]["dir"])
        ref = np.array(Image.open(d / "reference.png"))
        comp = np.array(Image.open(d / "composite.png"))
        tgt = np.array(Image.open(d / "target.png").convert("L")) > 127
        self.assertTrue((ref[~tgt] == comp[~tgt]).all(), "ngoài mask phải đúng từng pixel ảnh gốc")
        other = imaging.mask_of(Path(self.svc.images.layers(self.did, VIEW)["dir"]), ["TD1-door-2"])
        self.assertTrue((ref[other] == comp[other]).all(), "cánh bên cạnh không bị ảnh hưởng")
        self.assertEqual(self.svc.store.get(self.did)[1], rev0, "thử nhanh không đổi thiết kế")

    def test_design_mode_applies_only_on_accept(self):
        rev0 = self.svc.store.get(self.did)[1]
        j = self.svc.images.create(self.did, VIEW, "TD1-door-1", mode="design", material="Acrylic kem bóng")
        self.assertEqual(sorted(j["request"]["targetParts"]), ["TD1-door-1", "TD1-door-2"])
        self.assertEqual(self.svc.store.get(self.did)[1], rev0, "chưa duyệt thì chưa đổi thiết kế")
        a = self.svc.images.accept(j["id"])
        self.assertEqual(a["status"], "accepted")
        spec, rev = self.svc.store.get(self.did)
        self.assertEqual(rev, rev0 + 1)
        self.assertEqual(spec.find("TD1").material, "Acrylic kem bóng")
        r = self.svc.images.layers(self.did, VIEW)
        self.assertEqual(r["baseImage"], {"type": "job", "jobId": j["id"]}, "ảnh đã duyệt thành ảnh gốc, renderKey giữ nguyên")

    def test_rejections(self):
        im = self.svc.images
        rev0 = self.svc.store.get(self.did)[1]
        with self.assertRaises(KeyError):
            im.create(self.did, VIEW, "NONE", material="xanh rêu")
        with self.assertRaises(ValueError):
            im.create(self.did, "no-corner", "TD1-door-1", material="xanh rêu")
        with self.assertRaises(ConflictError):
            im.create(self.did, VIEW, "TD1-door-1", material="xanh rêu", base_rev=0)
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, "TD1-door-1", mode="design")  # thiếu vật liệu
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, "type:plinth", mode="design", material="xanh rêu")  # len chân chưa sửa được trong thiết kế
        j = im.create(self.did, VIEW, "TD1-door-1", material="Vân đá")  # to-mau không suy được màu
        self.assertEqual(j["status"], "error:unsupported")
        self.assertEqual(self.svc.store.get(self.did)[1], rev0, "lỗi backend không đổi thiết kế")

    def test_package_and_submit(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, "type:countertop", mode="quick", material="Đá trắng vân mây", backend="job-package")
        self.assertEqual(j["status"], "awaiting-result")
        d = Path(j["result"]["dir"])
        self.assertTrue((d / "request.json").exists())
        self.assertTrue((d / "AI-CHAT-GUIDE.txt").exists())
        self.assertTrue((d / "image-1-marked-base-image.png").exists())
        self.assertTrue((d / "image-2-mask.png").exists())
        same = (d / "reference.png").read_bytes()
        bad = im.submit_result(j["id"], same)
        self.assertEqual(bad["status"], "error:check-failed", "ảnh không đổi vùng đích bị đánh dấu")
        ref = np.array(Image.open(d / "reference.png"))
        raw = ref.copy()
        raw[...] = (200, 40, 40)  # model "vẽ lan" ra cả ảnh
        buf = io.BytesIO(); Image.fromarray(raw).save(buf, "PNG")
        ok = im.submit_result(j["id"], buf.getvalue())
        rep = ok["result"]["report"]
        self.assertEqual(ok["status"], "needs-review")
        self.assertTrue(rep["outsideMask"]["setPreserve"])
        self.assertGreater(rep["rawImage"]["changesOutsideEditZone"], 50, "chẩn đoán phát hiện model vẽ ngoài mask")
        with self.assertRaises(ValueError):
            im.submit_result(j["id"], b"not an image")

    def test_accept_conflict(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, "TD1-door-2", mode="design", material="Laminate xanh navy")
        self.svc.apply(self.did, {"op": "common", "changes": {"doorGap": 3}}, None, "test")
        with self.assertRaises(ConflictError):
            im.accept(j["id"])
        self.assertEqual(im.get(j["id"])["status"], "needs-review")


class TestHandles(_Base):
    def test_handles_in_geometry_render_and_layers(self):
        s = _spec()
        sc = geometry.compile_spec(s)
        hs = [p for p in sc.parts if p.type == "handle"]
        fronts = {p.id for p in sc.parts if p.type in ("door", "glass-door", "drawer")}
        self.assertEqual(len(hs), len(fronts), "mỗi cánh/ngăn kéo một tay nắm (kiểu thanh)")
        self.assertTrue(all(h.parent in fronts for h in hs))
        r = self.svc.images.layers(self.did, VIEW)
        ids = {x["id"]: x for x in r["layers"]}
        self.assertIn("handle:TD1", ids)
        self.assertEqual(ids["type:handle"]["designEdit"], "mọi tay nắm")
        a = imaging.mask_of(Path(r["dir"]), ["TD1-handle-1"])
        door = imaging.mask_of(Path(r["dir"]), [next(h.parent for h in hs if h.id == "TD1-handle-1")])
        self.assertTrue(a.any())
        self.assertFalse((a & door).any(), "tay nắm che cánh: pixel thuộc tay nắm, không thuộc cánh")
        doc = threejs_export.export(s, "x", 1)
        refs = {d["hardware"]["sourceRef"] for m in doc["modules"] for d in m["doors"] + m["drawers"] if d.get("hardware")}
        self.assertEqual(refs, {h.id for h in hs})

    def test_handle_style_none_and_knob(self):
        s = _spec()
        s.common.handle.variant = "none"
        self.assertFalse([p for p in geometry.compile_spec(s).parts if p.type == "handle"])
        s.common.handle.variant = "knob"
        hs = [p for p in geometry.compile_spec(s).parts if p.type == "handle"]
        self.assertTrue(hs)
        self.assertTrue(all(abs((h.max[1] - h.min[1]) - 30) < 0.01 for h in hs))

    def test_handle_material_job_design_mode(self):
        j = self.svc.images.create(self.did, VIEW, "handle:TD1", mode="design", material="Đồng vàng xước")
        self.assertEqual(j["request"]["scope"], "tay nắm module TD1")
        self.assertEqual(len(j["request"]["tasks"][0]["targetParts"]), 2, "handles are stored per module: only TD1's handles change")
        self.svc.images.reject(j["id"])
        j = self.svc.images.create(self.did, VIEW, "type:handle", mode="design", material="Đồng vàng xước")
        self.assertEqual(j["request"]["scope"], "mọi tay nắm")
        self.assertGreater(len(j["request"]["tasks"][0]["targetParts"]), 2, "every handle selected -> common handle material")
        self.svc.images.reject(j["id"])


class TestMultiTask(_Base):
    TASKS = [{"targetLayer": "frontSections:TD1", "material": "Laminate xanh rêu mờ"},
             {"targetLayer": "type:countertop", "material": "Đá nhân tạo đen"},
             {"targetLayer": "type:handle", "material": "Inox vàng", "instruction": "brushed brass"}]

    def test_multi_quick_and_accept_one_rev(self):
        im = self.svc.images
        rev0 = self.svc.store.get(self.did)[1]
        tasks = [dict(t) for t in self.TASKS]
        tasks[2]["material"] = "Kim loại vàng"
        j = im.create(self.did, VIEW, tasks=tasks, mode="quick")
        self.assertEqual(j["status"], "needs-review", j["error"])
        rep = j["result"]["report"]
        self.assertEqual(len(rep["task"]), 3)
        self.assertTrue(all(v["insideMask"]["changed"] for v in rep["task"]))
        self.assertTrue(rep["outsideMask"]["setPreserve"])
        self.assertEqual(j["target"], "frontSections:TD1 +2")
        d = Path(j["result"]["dir"])
        for i in (1, 2, 3):
            self.assertTrue((d / f"target_{i}.png").exists())
        a = im.accept(j["id"], apply_to_design=True)
        spec, rev = self.svc.store.get(self.did)
        self.assertEqual(rev, rev0 + 1, "mọi việc ghi thành một rev")
        self.assertEqual(a["result"]["design"]["op"]["op"], "multi")
        self.assertEqual(spec.find("TD1").material, "Laminate xanh rêu mờ")
        self.assertEqual(spec.common.material["countertop"], "Đá nhân tạo đen")
        self.assertEqual(spec.common.handle.material, "Kim loại vàng")

    def test_request_json_self_contained(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="job-package", tasks=[dict(t) for t in self.TASKS])
        d = Path(j["result"]["dir"])
        r = json.loads((d / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(r["schema"], "kitchen-ai-edit-request/2.0")
        for bo in ("renderKey", "tasks", "submitResult", "job"):
            self.assertNotIn(bo, r, "đã lọc thông tin hệ thống AI không dùng")
        self.assertLessEqual({"task", "label", "borderColor", "zoneColor", "name", "target", "position", "boxPercent", "material", "english"},
                             set(r["task"][0]))
        self.assertEqual([a["role"] for a in r["attachedImages"]], ["marked-base-image", "color-mask"])
        self.assertTrue(r["validation"]["ok"], r["validation"])
        self.assertEqual([a["order"] for a in r["attachedImages"]], [1, 2])
        self.assertIn("Region 1 (RED outline)", r["instruction"])
        self.assertIn("REMOVE the colored outlines", r["instruction"])
        ref = np.array(Image.open(io.BytesIO(base64.b64decode(r["attachedImages"][0]["dataUrl"].split(",")[1]))).convert("RGB"))
        self.assertEqual(list(ref.shape[1::-1]), r["dimensions"])
        g = json.loads((d / "gemini-request.json").read_text(encoding="utf-8"))
        parts = g["contents"][0]["parts"]
        self.assertEqual(parts[0]["text"], r["instruction"])
        self.assertEqual([p_["inline_data"]["mime_type"] for p_ in parts[1:]], ["image/png", "image/png"], "ảnh ở inline_data để Gemini tự giải mã")
        self.assertEqual(parts[1]["inline_data"]["data"], r["attachedImages"][0]["dataUrl"].split(",")[1])
        self.assertTrue((d / "image-1-marked-base-image.png").exists() and (d / "image-2-color-mask.png").exists())
        guide = (d / "AI-CHAT-GUIDE.txt").read_text(encoding="utf-8")
        self.assertIn("Do not paste JSON or base64", guide)
        self.assertIn("image-2-color-mask.png", guide)
        self.assertIn("ChatGPT, Claude or Gemini", guide)
        full = json.loads(im.export_full(j["id"]).read_text(encoding="utf-8"))
        self.assertEqual(full["schema"], "kitchen-ai-edit-request-full/1.0")
        self.assertEqual(full["job"]["render_key"], j["render_key"], "bản đầy đủ giữ thông tin nội bộ")
        self.assertEqual(len(full["request"]["tasks"]), 3)
        self.assertIn("targetParts", full["request"]["tasks"][0])
        for k in ("reference", "mask_color", "target_1", "mask_3"):
            self.assertTrue(full["image"][k].startswith("data:image/png;base64,"), k)
        self.assertFalse(any(k.startswith("image-") for k in full["image"]), "không lặp bản sao đánh số")
        lean = json.loads(Path(self.svc.ai_export(self.did, views=[VIEW], embed=True)["file"]).read_text(encoding="utf-8"))
        self.assertNotIn("threejs", lean)
        v = lean["views"][0]
        self.assertTrue(v["attachedImages"][0]["dataUrl"].startswith("data:image/png;base64,"))
        api = json.loads((Path(self.svc.render_dir) / self.did / f"rev{lean['revision']}" / "ai" / v["geminiApi"]).read_text(encoding="utf-8"))
        self.assertEqual(api["contents"][0]["parts"][0]["text"], v["instruction"])

    def test_overlap_and_errors(self):
        im = self.svc.images
        with self.assertRaises(ValueError) as e:
            im.create(self.did, VIEW, tasks=[{"targetLayer": "TD1-door-1", "material": "xanh rêu"},
                                             {"targetLayer": "frontSections:TD1", "material": "kem"}])
        self.assertEqual(getattr(e.exception, "code", None), "tasks-overlap")
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, tasks=[{"targetLayer": "TD1-door-1"}] * 9)
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, tasks=[{"material": "kem"}])
        # thiết kế: hai việc cùng đổi một khóa vật liệu chung -> việc sau trùng chi tiết của việc trước
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, mode="design", tasks=[{"targetLayer": "type:countertop", "material": "Đá đen"},
                                                              {"targetLayer": "type:countertop", "material": "Đá xám"}])
        j = im.create(self.did, VIEW, tasks=[{"targetLayer": "TD1-door-1", "material": "xanh rêu"},
                                             {"targetLayer": "TD1-door-2", "material": "Vân đá"}])
        self.assertEqual(j["status"], "error:unsupported")
        self.assertIn("Việc 2", j["error"])

    def test_multi_package_and_partial(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, tasks=self.TASKS[:2], backend="job-package", mode="design")
        self.assertEqual(j["status"], "awaiting-result")
        d = Path(j["result"]["dir"])
        self.assertTrue((d / "image-1-marked-base-image.png").exists())
        self.assertTrue((d / "image-2-color-mask.png").exists())
        self.assertTrue((d / "mask_color.png").exists())
        guide = (d / "AI-CHAT-GUIDE.txt").read_text(encoding="utf-8")
        self.assertIn("Region 1", guide)
        self.assertIn("Region 2", guide)
        ref = imaging.read(d / "reference.png")
        raw = ref.copy()
        m1 = imaging.read(d / "target_1.png", "L") > 127
        raw[m1] = (30, 160, 60)  # chỉ làm việc 1
        buf = io.BytesIO(); Image.fromarray(raw).save(buf, "PNG")
        r = im.submit_result(j["id"], buf.getvalue())
        self.assertEqual(r["status"], "needs-review")
        self.assertIn("Việc 2", r["error"])


class TestMarkingAndChecks(_Base):
    """A: ảnh gốc đánh dấu viền + số; B: vị trí bằng chữ; C: kiểm tra request trước khi gửi."""

    def test_outline_never_inside_targets(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="job-package", tasks=[{"targetLayer": "frontSections:TD1", "material": "Laminate xanh rêu"},
                                                                 {"targetLayer": "handle:TD1", "material": "Đồng vàng"}])
        d = Path(j["result"]["dir"])
        ref = imaging.read(d / "reference.png")
        mk = imaging.read(d / "reference_marked.png")
        diff = np.abs(mk.astype(int) - ref.astype(int)).max(-1) > 0
        region = imaging.read(d / "mask.png", "L") > 127
        self.assertTrue(diff.any(), "có vẽ viền")
        self.assertFalse((diff & region).any(), "viền và nhãn nằm hoàn toàn ngoài vùng gửi model (nên không lọt vào ảnh ghép)")
        for i in (1, 2):
            t = imaging.read(d / f"target_{i}.png", "L") > 127
            ring = imaging.grow(t, 20) & ~imaging.grow(t, 12)
            self.assertTrue((diff & ring).any(), f"việc {i} có viền bao quanh")
        tasks = j["request"]["tasks"]
        self.assertEqual(tasks[0]["roleEn"], "cabinet door front")
        self.assertRegex(tasks[0]["position"]["en"], r"x \d+–\d+%, y \d+–\d+%")
        x0, y0, x1, y1 = tasks[0]["position"]["frame"]
        self.assertTrue(0 <= x0 < x1 <= 100 and 0 <= y0 < y1 <= 100)
        self.assertGreater(tasks[0]["remaining"], 0, "đếm các cánh khác cùng loại để dặn giữ nguyên")

    def test_position_words(self):
        from kitchen.images import describe_position
        m = np.zeros((100, 200), bool); m[5:20, 10:40] = True
        self.assertTrue(describe_position(m)["en"].startswith("upper-left area"))
        m = np.zeros((100, 200), bool); m[80:95, 5:195] = True
        self.assertIn("full width", describe_position(m)["en"])
        self.assertIsNone(describe_position(np.zeros((10, 10), bool)))

    def test_check_detects_broken_requests(self):
        from kitchen import request_check
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="job-package", target="type:countertop", material="Đá nhân tạo đen")
        text = (Path(j["result"]["dir"]) / "request.json").read_text(encoding="utf-8")
        self.assertTrue(request_check.check_text(text)["ok"])
        cut = request_check.check_text(text[: len(text) // 3])
        self.assertFalse(cut["ok"]); self.assertIn("CẮT", cut["errors"][0])
        lean = json.loads(text)
        lean["attachedImages"] = lean["attachedImages"][:1]
        self.assertIn("Thiếu ảnh mask", " ".join(request_check.check_lean(lean)["errors"]))
        lean = json.loads(text)
        lean["attachedImages"][1]["dataUrl"] = lean["attachedImages"][1]["dataUrl"][:-7]
        self.assertFalse(request_check.check_lean(lean)["ok"], "base64 bị cắt")
        g = (Path(j["result"]["dir"]) / "gemini-request.json").read_text(encoding="utf-8")
        self.assertTrue(request_check.check_text(g)["ok"])
        self.assertTrue(request_check.check_text(g.replace(" ", "\u00a0", 3))["warning"])

    def test_send_blocked_when_check_fails(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="job-package", preview=True, target="type:countertop", material="Đá nhân tạo đen")
        (Path(j["result"]["dir"]) / "mask.png").write_bytes(b"")  # mask hỏng -> không đọc được
        with self.assertRaises(Exception):
            im.send(j["id"])
        self.assertEqual(im.get(j["id"])["status"], "awaiting-send", "không gửi khi kiểm tra lỗi")


class TestGeometryEdit(_Base):
    """Sửa hình: áp thao tác lên bản sao thiết kế, render lại cùng camera, mask = vùng khác cũ/mới; accept ghi rev."""

    def test_remove_module_flow(self):
        im = self.svc.images
        rev0 = self.svc.store.get(self.did)[1]
        j = im.create(self.did, VIEW, backend="recolor", kind="geometry_edit", geometry_items=[{"type": "remove-module", "id": "TD3"}])
        self.assertEqual(j["status"], "needs-review", j["error"])
        r = j["request"]
        self.assertEqual(r["operation"], "remove-item")
        self.assertEqual(r["designOp"], {"op": "remove", "id": "TD3", "closeGap": False})
        self.assertEqual(r["params"], {})
        self.assertIn("TD3-door-1", r["different"]["xoa"])
        d = Path(j["result"]["dir"])
        m = imaging.read(d / "target.png", "L") > 127
        old = imaging.mask_of(Path(self.svc.images.view_dir(self.did, rev0, VIEW)), ["TD3-door-1"])
        self.assertTrue((m | ~old).all(), "vùng đổi phủ hết cánh bị xóa")
        self.assertLess(m.mean(), 0.3, "chỉ vùng thay đổi, không phải cả ảnh")
        self.assertFalse((imaging.read(d / "lines_moi.png", "L") == imaging.read(
            Path(self.svc.images.view_dir(self.did, rev0, VIEW)) / "lines.png", "L")).all(), "nét gửi model là của thiết kế mới")
        self.assertTrue(j["result"]["report"]["outsideMask"]["setPreserve"])
        req = json.loads((d / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(req["type"], "geometry_edit")
        self.assertEqual([a["role"] for a in req["attachedImages"]], ["marked-base-image", "mask", "new-geometry"])
        self.assertTrue(req["validation"]["ok"], req["validation"])
        self.assertIn("IMAGE 3", req["instruction"])
        self.assertIn("remove the base cabinet", req["instruction"])
        a = im.accept(j["id"])
        spec, rev = self.svc.store.get(self.did)
        self.assertEqual(rev, rev0 + 1)
        self.assertNotIn("TD3", [x.id for x in spec.module])
        self.assertEqual(a["result"]["design"]["rev"], rev)
        lay = im.layers(self.did, VIEW)
        self.assertEqual(lay["renderKey"], r["newRenderKey"])
        self.assertEqual(lay["baseImage"], {"type": "job", "jobId": j["id"]}, "ảnh đã duyệt thành ảnh gốc của rev mới")

    def test_handles_and_door_style(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="job-package", kind="geometry_edit", geometry_items=[{"type": "handle", "variant": "knob"}])
        self.assertEqual(j["status"], "awaiting-result", j["error"])
        self.assertGreater(j["request"]["maskPixels"], 0)
        d = Path(j["result"]["dir"])
        self.assertTrue((d / "AI-CHAT-GUIDE.txt").exists())
        k = im.create(self.did, VIEW, backend="recolor", kind="geometry_edit", geometry_items=[{"type": "door-style", "id": "TD1", "variant": "frame"}])
        self.assertEqual(k["status"], "needs-review", k["error"])
        self.assertEqual(k["request"]["different"]["pixels"], 0, "render nhanh không dựng khung cánh")
        self.assertGreater(k["request"]["maskPixels"], 0, "vẫn bắt buộc vẽ lại mặt trước TD1")
        kd = Path(k["result"]["dir"])
        old = Path(self.svc.images.view_dir(self.did, k["rev"], VIEW)) / "lines.png"
        self.assertGreater(int((imaging.read(kd / "lines_moi.png", "L") < 128).sum()), int((imaging.read(old, "L") < 128).sum()),
                           "có thêm nét khung shaker")
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, backend="recolor", kind="geometry_edit", geometry_items=[{"type": "handle", "variant": "sai"}])
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, backend="recolor", kind="geometry_edit", geometry_items=[])

    def test_conflict_and_presets(self):
        im = self.svc.images
        j = im.create(self.did, VIEW, backend="recolor", kind="geometry_edit", geometry_items=[{"type": "remove-module", "id": "TD4"}])
        spec, rev = self.svc.store.get(self.did)
        self.svc.apply(self.did, {"op": "common", "changes": {"handle": {**spec.common.handle.model_dump(mode="json"), "length": 200}}}, rev)
        with self.assertRaises(ConflictError):
            im.accept(j["id"])
        e = im.create(self.did, VIEW, backend="job-package", target="type:countertop", material="Đá đen", operation="change-material")
        self.assertEqual(e["request"]["params"], {})
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, backend="job-package", target="type:countertop", material="Đá đen", operation="remove-item")

    def test_pin_cameras(self):
        from kitchen import edit, geometry_edit
        spec = _spec().model_copy(update={"cameraViews": {}})
        nxt = edit.apply_op(spec, {"op": "remove", "id": "TC1"})  # tủ cao ở mép: khung bao đổi
        pin = geometry_edit.pin_cameras(spec, nxt)
        self.assertIsNotNone(pin, "góc nhìn mặc định dịch theo khung bao")
        fixed = edit.apply_op(nxt, pin)
        self.assertEqual({k: v.model_dump() for k, v in geometry.views_of(fixed).items()},
                         {k: v.model_dump() for k, v in geometry.views_of(spec).items()})
        self.assertIsNone(geometry_edit.pin_cameras(_spec(), edit.apply_op(_spec(), {"op": "remove", "id": "TD5"})), "đã có gocNhin cố định")


class TestRealism(_Base):
    """Câu lệnh luôn kèm yêu cầu ảnh thật; ánh sáng chọn được cho ảnh đầy đủ; sửa vùng bám ảnh gốc."""

    def test_prompts(self):
        from kitchen import prompts
        im = self.svc.images
        g = im.create(self.did, VIEW, backend="job-package", kind="gen0", lighting="dim-evening")
        r = json.loads((Path(g["result"]["dir"]) / "request.json").read_text(encoding="utf-8"))
        self.assertIn("rectilinear lens", r["instruction"])
        self.assertIn("2700", r["instruction"], "ánh sáng buổi tối")
        self.assertNotIn("natural daylight", r["instruction"], "không lẫn ánh sáng mâu thuẫn")
        self.assertIn("reveal gaps", r["instruction"])
        self.assertIn("professional architectural interior photograph", g["request"]["prompt"])
        self.assertIn("CGI", g["request"]["negativePrompt"])
        e = im.create(self.did, VIEW, backend="job-package", target="type:countertop", material="Đá marble trắng vân mây")
        t = json.loads((Path(e["result"]["dir"]) / "request.json").read_text(encoding="utf-8"))["instruction"]
        self.assertIn("as if captured in the same shot", t)
        self.assertIn("veining", t, "mô tả bề mặt theo vật liệu mới")
        self.assertNotIn("wood surfaces", t, "chỉ mô tả vật liệu của vùng sửa")
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, backend="job-package", kind="gen0", lighting="sai")
        lean = json.loads(Path(self.svc.ai_export(self.did, views=[VIEW], embed=True, lighting="late-afternoon")["file"]).read_text(encoding="utf-8"))
        self.assertEqual(lean["lighting"], "late-afternoon")
        self.assertIn("late-afternoon", lean["views"][0]["instruction"])
        self.assertIn("window", prompts.full(_spec()) if any(openings for t in (_spec().room.wall if _spec().room else []) for openings in t.openings)
                      else "window")


class TestBeauty(_Base):
    def test_save_beauty_and_reference_order(self):
        im = self.svc.images
        r = im.layers(self.did, VIEW)
        self.assertEqual(r["baseImage"]["type"], "albedo")
        d = Path(r["dir"])
        buf = io.BytesIO(); Image.open(d / "albedo.png").resize((1280, 960)).save(buf, "PNG")  # cùng tỉ lệ, khác cỡ -> co về
        info = im.save_beauty(self.did, VIEW, buf.getvalue())
        self.assertEqual(info["size"], [640, 480])
        self.assertTrue(info["lineMatch"]["khop"])
        self.assertEqual(im.layers(self.did, VIEW)["baseImage"]["type"], "beauty", "chưa có ảnh duyệt: ưu tiên render three.js")
        j = im.create(self.did, VIEW, "TD1-door-1", material="xanh rêu")
        self.assertEqual(j["request"]["referenceImage"]["type"], "beauty")
        im.accept(j["id"])
        self.assertEqual(im.layers(self.did, VIEW)["baseImage"]["type"], "job", "ảnh đã duyệt đứng trước")
        self.assertEqual(im.create(self.did, VIEW, "TD1-door-2", material="kem", reference="beauty")["request"]["referenceImage"]["type"], "beauty")
        buf = io.BytesIO(); Image.new("RGB", (500, 500)).save(buf, "PNG")
        with self.assertRaises(ValueError):
            im.save_beauty(self.did, VIEW, buf.getvalue())


class TestImportedBase(_Base):
    def _png(self, size):
        d = Path(self.svc.images.layers(self.did, VIEW)["dir"])
        buf = io.BytesIO(); Image.open(d / "albedo.png").resize(size).save(buf, "PNG")
        return buf.getvalue()

    def test_import_replaces_base_and_newest_wins(self):
        im = self.svc.images
        info = im.import_base(self.did, VIEW, self._png((1280, 960)))  # same ratio, other size -> resized
        self.assertEqual(info["size"], [640, 480])
        self.assertEqual(im.layers(self.did, VIEW)["baseImage"]["type"], "imported")
        j = im.create(self.did, VIEW, "TD1-door-1", material="xanh rêu")
        self.assertEqual(j["request"]["referenceImage"]["type"], "imported")
        im.accept(j["id"])
        self.assertEqual(im.layers(self.did, VIEW)["baseImage"]["type"], "job", "a job accepted after the import is the base")
        im.import_base(self.did, VIEW, self._png((640, 480)))
        self.assertEqual(im.layers(self.did, VIEW)["baseImage"]["type"], "imported", "a newer import replaces the accepted job")
        self.assertEqual(im.create(self.did, VIEW, "TD1-door-2", material="kem", reference="imported")["request"]["referenceImage"]["type"], "imported")

    def test_clear_and_bad_input(self):
        im = self.svc.images
        with self.assertRaises(ValueError):
            im.create(self.did, VIEW, "TD1-door-1", material="kem", reference="imported")  # nothing imported yet
        im.import_base(self.did, VIEW, self._png((640, 480)))
        self.assertTrue(im.clear_imported_base(self.did, VIEW)["removed"])
        self.assertEqual(im.layers(self.did, VIEW)["baseImage"]["type"], "albedo")
        self.assertFalse(im.clear_imported_base(self.did, VIEW)["removed"])
        buf = io.BytesIO(); Image.new("RGB", (500, 500)).save(buf, "PNG")
        with self.assertRaises(ValueError):
            im.import_base(self.did, VIEW, buf.getvalue())
        with self.assertRaises(ValueError):
            im.import_base(self.did, VIEW, b"not an image")


    def test_fit_crop_pad_and_stale_status(self):
        im = self.svc.images
        sq = io.BytesIO(); Image.new("RGB", (500, 500), (200, 120, 60)).save(sq, "PNG")
        for fit in ("crop", "pad"):
            info = im.import_base(self.did, VIEW, sq.getvalue(), fit=fit)
            self.assertEqual((info["size"], info["fit"]), ([640, 480], fit))
        with self.assertRaises(ValueError):
            im.import_base(self.did, VIEW, sq.getvalue(), fit="stretch")
        # a job left in 'running' by a stopped process is marked interrupted
        j = im.create(self.did, VIEW, "TD1-door-1", material="kem")
        with self.svc.store._conn() as c:
            c.execute("UPDATE image_jobs SET status='running', heartbeat_at=0 WHERE id=?", (j["id"],))   # its owner stopped beating long ago
        self.assertEqual(self.svc.store.mark_stale_jobs(), 1)
        self.assertEqual(self.svc.store.get_job(j["id"])["status"], "error:interrupted")


class TestAiExport(_Base):
    def test_json_and_zip(self):
        import zipfile
        r = self.svc.ai_export(self.did)
        doc = json.loads(Path(r["file"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], "kitchen-ai-image-request/1.0")
        self.assertEqual(doc["design"]["revision"], self.svc.store.get(self.did)[1])
        self.assertEqual(len(doc["views"]), 8)
        v = next(x for x in doc["views"] if x["id"] == VIEW)
        self.assertIn("flat slab cabinet doors", v["prompt"], "giữ kiểu cánh phẳng (Gemini hay tự đổi sang khung)")
        self.assertEqual(v["camera"]["id"], f"CAM-{VIEW}")
        self.assertIn("modules", doc["threejs"])
        self.assertTrue(any(m["english"] for m in doc["material"]))
        z = self.svc.ai_export(self.did, views=[VIEW, "long-run"], with_images=True)
        names = zipfile.ZipFile(z["zip"]).namelist()
        self.assertIn("ai-request.json", names)
        self.assertIn(f"{VIEW}/lines.png", names)
        self.assertIn("long-run/depth.png", names)
        with self.assertRaises(ValueError):
            self.svc.ai_export(self.did, views=["none"])


class _FakeGemini(BaseHTTPRequestHandler):
    calls: list = []
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeGemini.calls.append({"path": self.path, "key": self.headers.get("x-goog-api-key"), "body": body})
        if _FakeGemini.mode == "429":
            b = b'{"error":{"code":429,"message":"quota"}}'
            self.send_response(429); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        parts = body["contents"][0]["parts"]
        imgs = [np.array(Image.open(io.BytesIO(base64.b64decode(p["inline_data"]["data"]))).convert("RGB")) for p in parts if "inline_data" in p]
        if _FakeGemini.mode == "noimage":
            out = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": [{"text": "không thể"}]}}]}
        else:
            im = imgs[0].copy()
            if len(imgs) > 1:  # edit: tô vùng mask; trả ảnh lớn gấp đôi để thử co giãn về đúng kích thước
                im[imgs[1].max(-1) > 127] = (90, 120, 80)
                im = np.array(Image.fromarray(im).resize((im.shape[1] * 2, im.shape[0] * 2)))
            buf = io.BytesIO(); Image.fromarray(im).save(buf, "PNG")
            out = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}}]}}]}
        b = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


class TestGeminiAdapter(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeGemini)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.envfile = cls.tmp / "mcp-image.env"
        cls.envfile.write_text("GEMINI_API_KEY=test-key\nGEMINI_IMAGE_MODEL=gemini-thu\n", encoding="utf-8")
        cls.config = dataclasses.replace(cls.svc.images.config, gemini_api_key=None, gemini_env_file=str(cls.envfile),
                                         gemini_base_url=f"http://127.0.0.1:{cls.srv.server_address[1]}/v1beta")
        cls.svc.images.config = cls.config

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        super().tearDownClass()

    def _run(self, **kw):
        j = self.svc.images.create(self.did, VIEW, backend="gemini", **kw)
        return self.svc.images.wait(j["id"], 30)

    def test_gen0_and_edit(self):
        _FakeGemini.mode = "ok"
        g = self._run(kind="gen0", instruction="warm evening light")
        self.assertEqual(g["status"], "needs-review", g["error"])
        call = _FakeGemini.calls[-1]
        self.assertEqual(call["key"], "test-key")
        self.assertIn("/models/gemini-thu:generateContent", call["path"])
        self.assertEqual(call["body"]["generationConfig"]["imageConfig"]["aspectRatio"], "4:3")
        self.assertIn("warm evening light", call["body"]["contents"][0]["parts"][0]["text"])
        self.assertTrue(g["result"]["report"]["lineMatch"]["khop"], "ảnh giữ nguyên hình học thì khớp nét")
        self.svc.images.accept(g["id"])
        e = self._run(target="TD1-door-1", material="Laminate xanh rêu mờ")
        self.assertEqual(e["status"], "needs-review", e["error"])
        self.assertEqual(e["request"]["referenceImage"]["jobId"], g["id"])
        self.assertEqual(len([p for p in _FakeGemini.calls[-1]["body"]["contents"][0]["parts"] if "inline_data" in p]), 2)
        self.assertIn("sage green", e["result"]["geminiPrompt"])
        rep = e["result"]["report"]
        self.assertTrue(rep["resize"])
        self.assertTrue(rep["outsideMask"]["setPreserve"])

    def test_geometry_three_images(self):
        _FakeGemini.mode = "ok"
        e = self.svc.images.wait(self.svc.images.create(self.did, VIEW, backend="gemini", kind="geometry_edit",
                                                        geometry_items=[{"type": "remove-module", "id": "TD5"}])["id"], 30)
        self.assertEqual(e["status"], "needs-review", e["error"])
        parts = _FakeGemini.calls[-1]["body"]["contents"][0]["parts"]
        self.assertEqual(len([p for p in parts if "inline_data" in p]), 3, "ảnh đánh dấu + mask + hình mẫu thiết kế mới")
        self.assertIn("IMAGE 3", parts[0]["text"])

    def test_multi_one_call(self):
        _FakeGemini.mode = "ok"
        n0 = len(_FakeGemini.calls)
        e = self._run(tasks=[{"targetLayer": "frontSections:TD1", "material": "Laminate xanh rêu"},
                             {"targetLayer": "handle:TD1", "material": "Đồng vàng"}])
        self.assertEqual(e["status"], "needs-review", e["error"])
        self.assertEqual(len(_FakeGemini.calls) - n0, 1, "nhiều việc, một lần gọi Gemini")
        text = _FakeGemini.calls[-1]["body"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Region 1 (RED outline): the cabinet door front in the", text)
        self.assertIn("Region 2 (GREEN outline): the cabinet handle", text)
        self.assertIn("brushed brass", text)
        self.assertIn("other cabinet handles in the photo are NOT outlined — leave them unchanged", text)

    def test_preview_then_send(self):
        _FakeGemini.mode = "ok"
        im = self.svc.images
        n0 = len(_FakeGemini.calls)
        j = im.create(self.did, VIEW, backend="gemini", preview=True,
                      tasks=[{"targetLayer": "frontSections:TD1", "material": "Laminate xanh rêu"}, {"targetLayer": "handle:TD1", "material": "Đồng vàng"}])
        self.assertEqual(j["status"], "awaiting-send")
        self.assertEqual(len(_FakeGemini.calls), n0, "xem trước: chưa gọi Gemini")
        req = json.loads((Path(j["result"]["dir"]) / "request.json").read_text(encoding="utf-8"))
        s = im.wait(im.send(j["id"])["id"], 30)
        self.assertEqual(s["status"], "needs-review", s["error"])
        sent = _FakeGemini.calls[-1]["body"]["contents"][0]["parts"]
        self.assertEqual(sent[0]["text"], req["instruction"], "gửi đúng chỉ dẫn đã xem trước")
        self.assertEqual(sent[1]["inline_data"]["data"], req["attachedImages"][0]["dataUrl"].split(",")[1], "gửi đúng ảnh gốc đã xem trước")
        api = json.loads((Path(j["result"]["dir"]) / "gemini-request.json").read_text(encoding="utf-8"))
        self.assertEqual(api["contents"], _FakeGemini.calls[-1]["body"]["contents"], "gemini-request.json = đúng thân request đã gửi")
        with self.assertRaises(ValueError):
            im.send(j["id"])
        h = im.create(self.did, VIEW, "TD1-door-1", instruction="x", backend="gemini", preview=True)
        self.assertEqual(im.reject(h["id"])["status"], "rejected")
        k = im.create(self.did, VIEW, "TD1-door-1", instruction="x", backend="gemini", preview=True)
        self.svc.apply(self.did, {"op": "update", "id": "TD1", "changes": {"height": 700}}, None, "test")
        with self.assertRaises(ValueError) as e:
            im.send(k["id"])
        self.assertEqual(getattr(e.exception, "code", None), "job-stale")

    def test_errors(self):
        _FakeGemini.mode = "429"
        self.assertEqual(self._run(target="TD1-door-1", instruction="x")["status"], "error:overloaded")
        _FakeGemini.mode = "noimage"
        f = self._run(target="TD1-door-1", instruction="x")
        self.assertEqual(f["status"], "error:generation-failed")
        self.assertIn("SAFETY", f["error"])
        _FakeGemini.mode = "ok"
        self.svc.images.config = dataclasses.replace(self.config, gemini_env_file=None)
        try:
            self.assertEqual(self._run(target="TD1-door-1", instruction="x")["status"], "error:unsupported")
        finally:
            self.svc.images.config = self.config
        self.assertNotIn("test-key", json.dumps(self.svc.images.list(self.did)), "không lộ khóa trong job")


class TestHttpApi(_Base):
    def test_endpoints(self):
        import urllib.request
        import web_server
        srv = web_server.make_server(0, self.svc)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Host": "localhost"})
            with urllib.request.urlopen(req) as r:
                return r.read(), r.headers.get("Content-Type")
        try:
            data, _ = call(f"/api/designs/{self.did}/layers?view={VIEW}")
            self.assertTrue(json.loads(data)["layers"])
            png, ct = call(f"/api/designs/{self.did}/mask?view={VIEW}&layer=TD1-door-1")
            self.assertEqual(ct, "image/png")
            self.assertTrue((np.array(Image.open(io.BytesIO(png))) > 0).any())
            j = json.loads(call(f"/api/designs/{self.did}/image-jobs",
                                {"view": VIEW, "targetLayer": "type:countertop", "backend": "job-package", "material": "Đá đen"})[0])
            ref = Image.open(Path(j["result"]["dir"]) / "reference.png")
            buf = io.BytesIO(); Image.new("RGB", ref.size, (20, 20, 20)).save(buf, "PNG")
            r = json.loads(call(f"/api/image-jobs/{j['id']}/result", {"imageBase64": base64.b64encode(buf.getvalue()).decode()})[0])
            self.assertEqual(r["status"], "needs-review")
            ck = json.loads(call("/api/check-request", {"text": '{"schema": "kitchen-ai-edit-request/2.0", "chiDan": "x", "anhDinhKem": [{"thuTu": 1, "da'})[0])
            self.assertFalse(ck["ok"])
            a = json.loads(call(f"/api/image-jobs/{j['id']}/accept", {"applyToDesign": True})[0])
            self.assertEqual(a["result"]["design"]["scope"], "toàn bộ mặt đá")
            self.assertEqual(self.svc.store.get(self.did)[0].common.material["countertop"], "Đá đen")
            lst = json.loads(call(f"/api/image-jobs?design={self.did}")[0])
            self.assertTrue(any(x["id"] == j["id"] for x in lst))
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
