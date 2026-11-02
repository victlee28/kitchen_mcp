"""Chạy: python -m unittest discover -s tests -v   (từ thư mục gốc dự án)"""
import http.client
import json
import shutil
import tempfile
import threading
import unicodedata
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((ROOT / "fixtures" / "bep-chu-L.json").read_text(encoding="utf-8"))

from kitchen import edit, geometry, intent, rules  # noqa: E402
from kitchen.render import render_views  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import load_spec  # noqa: E402
from kitchen.store import ConflictError  # noqa: E402


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "t.db", self.tmp / "renders")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestIntent(unittest.TestCase):
    """Hồi quy các bug regex của bản cũ."""

    def p(self, s):
        return intent.parse_prompt(s)[0]

    def test_mm_khong_bi_nhan_1000(self):
        m = self.p("Tủ bếp dài 3000mm, sâu 600 mm, cao 2200mm")
        self.assertEqual((m.daiTuongSau, m.sauTuDuoi, m.dinhTu), (3000, 600, 2200))

    def test_cao_cap_khong_phai_chieu_cao(self):
        self.assertEqual(self.p("Tủ bếp cao cấp dài 3m, cao 2.4m").dinhTu, 2400)

    def test_chu_L_hai_canh(self):
        m = self.p("Bếp chữ L cạnh dài 2,8m và 3,2m")
        self.assertEqual((m.hinh, m.daiTuongSau, m.daiTuongPhai), ("L", 2800, 3200))

    def test_nfd(self):
        self.assertEqual(self.p(unicodedata.normalize("NFD", "Tủ bếp dài 4m")).daiTuongSau, 4000)

    def test_vat_lieu_mat_da_trang(self):
        self.assertEqual(self.p("tủ sồi, mặt đá trắng").vatLieu.get("matDa"), "Đá nhân tạo trắng")

    def test_mau_hop_le(self):
        for prompt in ["Tủ bếp chữ I dài 3.6m có tủ lạnh", "Bếp chữ L dài 2,4m x 2m", "Tủ bếp dài 2m, tủ nóc"]:
            spec = intent.from_template(self.p(prompt))
            v = rules.validate(spec)
            self.assertEqual(v["dem"]["error"], 0, (prompt, v["issues"]))
            # cảnh báo chỉ được là khuyến nghị NKBA (bếp nhỏ thiếu mặt bàn thao tác), không lỗi hình học
            self.assertEqual([i for i in v["issues"] if i["mucDo"] == "warning" and not i["quyTac"].startswith("NKBA")], [], prompt)


class TestSpecGeometry(unittest.TestCase):
    def test_fixture(self):
        s = load_spec(FIXTURE)
        self.assertEqual(len(s.module), 16)
        sc = geometry.compile_spec(s)
        mods = {p.module for p in sc.parts if p.module}
        self.assertTrue({m.ma for m in s.module} <= mods)
        top = max(p.max[1] for p in sc.parts if p.loai == "mat-da")
        self.assertEqual(top, 900)  # mặt đá đúng cao độ (bản cũ: 1120)

    def test_quy_uoc_tuong(self):
        sc = geometry.compile_spec(load_spec(FIXTURE))
        td1 = [p for p in sc.parts if p.module == "TD1"]
        self.assertLessEqual(max(p.max[0] for p in td1), -550 + 1e-6)  # tường sau chạy theo -x
        td3 = [p for p in sc.parts if p.module == "TD3"]
        self.assertGreaterEqual(min(p.min[2] for p in td3), 1440 - 1e-6)  # tường phải chạy theo +z


class TestRules(unittest.TestCase):
    def test_fixture_khong_quoc_gia(self):
        v = rules.validate(load_spec(FIXTURE))
        self.assertTrue(v["hopLe"])
        warn = {i["quyTac"] for i in v["issues"] if i["mucDo"] != "info"}
        self.assertEqual(warn, {"KITCHEN-DEFAULT-001"})  # chỉ mục toàn cầu; tiêu chuẩn các nước chỉ tham khảo
        self.assertTrue(all(i.get("thamKhao") for i in v["issues"] if i["quyTac"].startswith(("NKBA", "AS-", "EN-"))))
        self.assertFalse(any(i["quyTac"] == "GEO-CAO-DO" for i in v["issues"]))  # TT5 hút mùi được miễn

    def test_uu_tien_theo_quoc_gia(self):
        f = load_spec(FIXTURE)
        got = lambda qg: {i["quyTac"]: i for i in rules.validate(f, quoc_gia=qg)["issues"]}
        us = got("US")
        self.assertEqual((us["NKBA-10"]["mucDo"], us["NKBA-10"]["doDuoc"]), ("warning", [610, 375]))
        au = got("AU")
        self.assertEqual((au["AS-NZS-5601-1"]["mucDo"], au["AS-NZS-5601-1"]["doDuoc"]), ("error", 635))  # 1700-165-900
        self.assertEqual(got("GB")["HUT-MUI-001"]["mucDo"], "warning")
        self.assertEqual(got("DE")["EN-1116"]["mucDo"], "warning")  # mặt bàn sâu 570 < 600
        vn = rules.validate(f, quoc_gia="VN")
        self.assertEqual(vn["dem"]["warning"] + vn["dem"]["error"], 0)  # VN chỉ có quy ước thị trường -> info
        self.assertIn("VN-TU-BEP-PHO-BIEN", vn["quyTacDaDung"]["mat-da-cao"])

    def test_tham_so_tu_kb(self):
        rows = [{"code": "KITCHEN-DEFAULT-001", "khu_vuc": "GLOBAL", "quoc_gia": "",
                 "metadata": {"kiemTra": ["sau-tu-duoi"], "params": {"sauTuDuoi_min": 500, "sauTuDuoi_max": 650}}}]
        self.assertFalse(any(i["quyTac"] == "KITCHEN-DEFAULT-001" for i in rules.validate(load_spec(FIXTURE), rows)["issues"]))

    def test_tat_quy_tac_qua_kb(self):
        codes = {i["quyTac"] for i in rules.validate(load_spec(FIXTURE), [], "AU")["issues"]}
        self.assertFalse(codes & {"AS-NZS-5601-1", "NKBA-10", "KITCHEN-DEFAULT-001"})


    def test_va_cham(self):
        s = edit.update_module(load_spec(FIXTURE), "TD3", {"tu": 1300}, don_day=False)
        v = rules.validate(s)
        self.assertTrue(any(i["quyTac"] == "GEO-VA-CHAM" and set(i["module"]) == {"TD2", "TD3"} for i in v["issues"]))



class TestRegions(Tmp):
    def test_mau_theo_vung(self):
        for qg, mat in (("VN", 850), ("DE", 900), (None, 900)):
            s = intent.from_template(intent.MauBep(quocGia=qg, daiTuongSau=3600, tuLanh=True))
            self.assertEqual((s.chung.matDa, s.quocGia), (mat, qg))
            v = rules.validate(s)
            self.assertFalse(any(i.get("chuDe") == "hut-mui" for i in v["issues"]), qg)

    def test_nhan_quoc_gia_tu_mo_ta(self):
        self.assertEqual(intent.parse_prompt("Bếp chữ L chuẩn Úc dài 3m")[0].quocGia, "AU")
        self.assertIsNone(intent.parse_prompt("tủ bếp thẩm mỹ, ý tưởng hiện đại")[0].quocGia)

    def test_tra_cuu_uu_tien(self):
        self.assertEqual(self.svc.search_knowledge("hút mùi", None, "AU")[0]["code"], "AS-NZS-5601-1")
        self.assertEqual(self.svc.search_knowledge("hút mùi", None, "GB")[0]["code"], "HUT-MUI-001")
        vn_only = self.svc.search_knowledge("", ["rule", "standard"], "VN", chi_vung=True)
        self.assertTrue(vn_only)
        self.assertTrue(all(r["khu_vuc"] in ("GLOBAL", "SEA") for r in vn_only))
        with self.assertRaises(ValueError):
            self.svc.search_knowledge("", None, "XX")

    def test_migration_db_cu(self):
        import sqlite3
        from kitchen import knowledge_seed
        c = sqlite3.connect(self.tmp / "old.db")
        c.executescript("CREATE TABLE knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, code TEXT NOT NULL, title TEXT NOT NULL,"
                        " content TEXT NOT NULL, source_url TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1,"
                        " created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
                        "INSERT INTO knowledge(kind,code,title,content,source_url) VALUES('rule','NKBA-10','x','do nguoi dung sua','');")
        r = knowledge_seed.apply(c)
        c.commit()
        self.assertEqual(r["cotMoi"], ["khu_vuc", "quoc_gia"])
        row = c.execute("SELECT khu_vuc, quoc_gia, content FROM knowledge WHERE code='NKBA-10'").fetchone()
        self.assertEqual(row, ("NA", "US,CA", "do nguoi dung sua"))  # gán vùng nhưng giữ nội dung người dùng
        self.assertEqual(knowledge_seed.apply(c)["themMoi"], [])
        c.close()

class TestThreejs(unittest.TestCase):
    """Xuất theo Complete Kitchen Three.js Scene Schema: hợp lệ cả v1.0.0 lẫn v1.1.0, tham chiếu đúng, hình học khớp compiler."""

    @classmethod
    def setUpClass(cls):
        import jsonschema
        from kitchen import threejs_export as tx
        cls.tx = tx
        cls.validators = [jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / f).read_text(encoding="utf-8")))
                          for f in ("kitchen-threejs.v1.0.0.schema.json", "kitchen-threejs.schema.json")]

    def check(self, spec, **kw):
        doc = self.tx.export(spec, "thu", 1, **kw)
        for v in self.validators:
            errs = [f"{list(e.path)}: {e.message}" for e in v.iter_errors(doc)]
            self.assertEqual(errs, [], errs[:3])
        self.assertEqual(self.tx.integrity(doc), [])
        return doc

    @staticmethod
    def world_box(frame_tf, child_tf, dims):
        from kitchen.threejs_export import Frame, _rot
        mf = Frame((frame_tf["position"]["x"], frame_tf["position"]["y"], frame_tf["position"]["z"]), frame_tf["rotation"]["y"])
        p = child_tf["position"]
        corners = [(p["x"] + dx, p["y"] + dy, p["z"] + dz) for dx in (0, dims["width"]) for dy in (0, dims["height"]) for dz in (0, dims["depth"])]
        w = [tuple(a + b for a, b in zip(mf.pos, _rot(c, mf.rot))) for c in corners]
        return [min(x[i] for x in w) for i in range(3)], [max(x[i] for x in w) for i in range(3)]

    def test_fixture_hop_le_va_khop_hinh_hoc(self):
        spec = load_spec(FIXTURE)
        doc = self.check(spec, quoc_gia="VN")
        self.assertEqual(len(doc["modules"]), 16)
        self.assertEqual(len(doc["cameras"]), 8)
        self.assertEqual(doc["metadata"]["region"]["countryCode"], "VN")
        parts = geometry.compile_spec(spec).parts
        for m in doc["modules"]:
            ref = [p for p in parts if p.module == m["sourceRef"] and p.loai != "tay-nam"]  # tay nắm kiểm riêng
            doors = sorted(tuple(map(lambda v: round(v, 1), self.world_box(m["transform"], d["transform"], d["dimensions"])[0]))
                           for d in m["doors"])
            want = sorted(tuple(round(v, 1) for v in p.min) for p in ref if p.loai in ("canh", "canh-kinh"))
            self.assertEqual(doors, want, m["sourceRef"])
            boxes = [self.world_box(m["transform"], x["transform"], x["dimensions"]) for x in m["parts"] + m["doors"] + m["drawers"]]
            lo = [min(b[0][i] for b in boxes) for i in range(3)]
            hi = [max(b[1][i] for b in boxes) for i in range(3)]
            rlo = [min(p.min[i] for p in ref) for i in range(3)]
            rhi = [max(p.max[i] for p in ref) for i in range(3)]
            for i in range(3):
                self.assertAlmostEqual(lo[i], rlo[i], delta=0.1, msg=m["sourceRef"])
                self.assertAlmostEqual(hi[i], rhi[i], delta=0.1, msg=m["sourceRef"])

    def test_ban_le_tay_nam_va_mat_da(self):
        doc = self.check(load_spec(FIXTURE))
        td1 = next(m for m in doc["modules"] if m["sourceRef"] == "TD1")
        self.assertEqual([d["hingeSide"] for d in td1["doors"]], ["Left", "Right"])
        self.assertTrue(all("hardware" in d for d in td1["doors"]))
        tt3 = next(m for m in doc["modules"] if m["sourceRef"] == "TT3")
        self.assertTrue(all(d["glass"] for d in tt3["doors"]))
        tops = [a for a in doc["accessories"] if a["type"] == "Countertop"]
        self.assertEqual(sorted(c["type"] for t in tops for c in t["cutouts"]), ["cooktop", "sink"])
        self.assertTrue(any(l["type"] == "RectAreaLight" for l in doc["lighting"]))  # LED dưới tủ trên

    def test_mau_va_sau_khi_sua(self):
        for qg in ("VN", "AU", None):
            self.check(intent.from_template(intent.MauBep(hinh="L", daiTuongSau=3000, daiTuongPhai=2600, tuLanh=True, tuNoc=True, quocGia=qg)))
        s = edit.add_module(load_spec(FIXTURE), {"rong": 450, "canh": [450]}, sau_module="TD3")
        self.check(edit.remove_module(s, "TT4"))

    def test_khong_tay_nam(self):
        s = load_spec(FIXTURE)
        s.chung.tayNam.kieu = "khong"
        doc = self.check(s)
        self.assertFalse(any("hardware" in d for m in doc["modules"] for d in m["doors"]))


class TestMoldings(Tmp):
    """Phào cổ điển: dữ liệu, đường chạy, kiểm tra trần + hành động, xuất three.js, render."""

    def classic(self):
        from kitchen import moldings as M
        s = load_spec(FIXTURE)
        s.moldings = M.default_moldings()
        return s, M

    def test_profile_hop_le(self):
        from kitchen.spec import MoldingProfile
        from pydantic import ValidationError
        p = MoldingProfile(ma="x", points=[(0, 0), (0, 10), (10, 10), (10, 0)])  # chiều kim đồng hồ -> tự đảo
        self.assertEqual(p.points[0], (10.0, 0.0))
        for bad in ([(0, 0), (1, 1)], [(0, 0), (10, 10), (10, 0), (0, 10)], [(0, -5), (10, -5), (10, 10)]):
            with self.assertRaises(ValidationError):
                MoldingProfile(ma="b", points=bad)

    def test_mau_co_dien(self):
        m = intent.parse_prompt("Tạo tủ bếp chữ L phong cách cổ điển, có phào nóc và phào chân, dài 3m x 2,6m")[0]
        s = intent.from_template(m)
        self.assertEqual((s.phongCach, [x.kieu for x in s.moldings]), ("Classic", ["crown", "base"]))
        self.assertEqual(rules.validate(s)["dem"]["error"], 0)  # mẫu chừa chỗ phào dưới trần
        s2 = intent.from_template(intent.parse_prompt("Tủ bếp hiện đại dài 3m")[0])
        self.assertEqual(s2.moldings, [])

    def test_duong_chay_chu_L(self):
        s, M = self.classic()
        runs = {(r.molding.ma, tuple(r.tuong)): r for r in M.compute_runs(s)}
        crown = runs[("phao-noc", ("phai", "sau"))]
        self.assertIn((-320.0, 320.0), crown.points)  # góc trong chữ L: một đỉnh vát góc, không nối thẳng
        self.assertEqual(crown.points[0], (0.0, 2830.0))  # đầu hở tường phải quay về tường
        tc1 = runs[("phao-noc", ("sau",))]
        self.assertEqual(tc1.modules, ["TC1"])  # tủ cao sâu hơn: đoạn riêng, quay về tường ở đầu hở
        base = runs[("phao-chan", ("phai", "sau"))]
        self.assertNotIn("TC1", base.modules)  # không chạy phào chân qua hốc tủ lạnh
        self.assertAlmostEqual(base.length, 550 + 2830 - 550 + 1250 - 550 + 550, delta=1)

    def test_vuot_tran_va_hanh_dong(self):
        s, M = self.classic()
        v = rules.validate(s)
        i = next(x for x in v["issues"] if x["quyTac"] == "MOLDING-TRAN-001")
        self.assertEqual((i["mucDo"], i["doDuoc"], i["gioiHan"]), ("error", 2700, 2640))
        ha, giu = i["hanhDong"]
        s2 = edit.apply_op(s, ha["op"])
        self.assertEqual((s2.chung.dinhTu, s2.tim("TC1").cao, s2.tim("TT2").cao), (2550, 2550, 270))
        self.assertFalse(any(x["quyTac"] == "MOLDING-TRAN-001" for x in rules.validate(s2)["issues"]))
        s3 = edit.apply_op(s, giu["op"])
        i3 = next(x for x in rules.validate(s3)["issues"] if x["quyTac"] == "MOLDING-TRAN-001")
        self.assertEqual(i3["mucDo"], "info")
        self.assertTrue(any(x["quyTac"] == "AS-NZS-5601-1" for x in rules.validate(s2, quoc_gia="AU")["issues"]))  # hút mùi vẫn kiểm

    def test_canh_lat_len(self):
        s, M = self.classic()
        i = next(x for x in rules.validate(s)["issues"] if x["quyTac"] == "MOLDING-CANH-LAT-001")
        self.assertEqual(set(i["module"]), {"TT2", "TT7", "TT8", "TT9"})

    def test_xuat_threejs(self):
        import jsonschema
        from kitchen import threejs_export as tx
        s, M = self.classic()
        doc = tx.export(M.lower_top(s, 2550), "co-dien", 1)
        for f in ("kitchen-threejs.v1.0.0.schema.json", "kitchen-threejs.schema.json"):
            v = jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / f).read_text(encoding="utf-8")))
            self.assertEqual([e.message for e in v.iter_errors(doc)], [])
        self.assertEqual(tx.integrity(doc), [])
        self.assertEqual(sorted(d["type"] for d in doc["decorations"]), ["Base_Molding", "Crown_Molding", "Crown_Molding"])
        self.assertTrue(all(a["parameters"]["profile"] for a in doc["assets"] if a["id"].startswith("ASSET-MOLDING")))
        self.assertEqual(tx.export(load_spec(FIXTURE), "x", 1)["decorations"], [])  # spec cũ: không có phào

    def test_render_co_phao(self):
        import numpy as np
        from kitchen.render import SEG_MAU
        s, M = self.classic()
        s = M.lower_top(s, 2550)
        res = render_views(s, self.tmp / "m", ["goc-anh-goc"], 480, 360)
        d = Path(res["views"]["goc-anh-goc"]["dir"])
        seg = np.asarray(Image.open(d / "seg.png"))
        self.assertGreater(int((seg == np.array(SEG_MAU["phao"], np.uint8)).all(-1).sum()), 200)
        self.assertIn("phao-noc", res["views"]["goc-anh-goc"]["moduleThayDuoc"])
        self.assertIn("phao-chan", res["views"]["goc-anh-goc"]["moduleThayDuoc"])

    def test_js_sweep_khop_python(self):
        import shutil as sh
        import subprocess
        node = sh.which("node")
        if not node:
            self.skipTest("không có Node.js")
        s, M = self.classic()
        runs = M.compute_runs(s)
        payload = [{"profile": [list(p) for p in r.profile.points], "points": [{"x": x, "y": r.y, "z": z} for x, z in r.points]} for r in runs]
        script = ("const m = await import(process.argv[1]); const d = JSON.parse(process.argv[2]);"
                  "console.log(JSON.stringify(d.map(r => m.sweepRings(r.profile, r.points))));")
        out = subprocess.run([node, "--input-type=module", "-e", script, (ROOT / "web" / "scene-loader.js").as_uri(), json.dumps(payload)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        js = json.loads(out.stdout)
        for r, jr in zip(runs, js):
            py = M.sweep_rings(r.profile.points, r.points, r.y)
            err = max(abs(a - b) for ring_p, ring_j in zip(py, jr) for vp, vj in zip(ring_p, ring_j) for a, b in zip(vp, vj))
            self.assertLess(err, 1e-6)


class TestEdit(unittest.TestCase):
    def setUp(self):
        self.s = load_spec(FIXTURE)

    def test_them_don_day(self):
        s = edit.add_module(self.s, {"rong": 450, "canh": [450]}, sau_module="TD3")
        new = [m for m in s.module if m.ma not in {x.ma for x in self.s.module}][0]
        self.assertEqual((new.tuong, new.tu, new.cao), ("phai", 1810, 840))
        self.assertEqual(s.tim("TD4").tu, 2260)
        self.assertEqual(s.tim("TT3").tu, 630)  # tầng trên không bị dịch
        self.assertEqual(next(t for t in s.thietBi if t.ma == "TB4").tam, 2580)  # bếp dịch theo
        self.assertFalse(any(i["mucDo"] == "error" for i in rules.validate(s)["issues"]))

    def test_xoa_don_day(self):
        s = edit.remove_module(self.s, "TD3")
        self.assertEqual(s.tim("TD4").tu, 1440)

    def test_doi_rong_giu_ti_le_canh(self):
        s = edit.update_module(self.s, "TD1", {"rong": 800})
        self.assertEqual(s.tim("TD1").canh, [400, 400])
        self.assertEqual(s.tim("TC1").tu, 1350)

    def test_khong_sua_tai_cho(self):
        edit.remove_module(self.s, "TD3")
        self.assertEqual(len(self.s.module), 16)


class TestStore(Tmp):
    def test_revisions_va_xung_dot(self):
        r = self.svc.create_from_spec(FIXTURE)
        a = self.svc.apply(r["id"], {"op": "remove", "ma": "TD3"}, 1)
        self.assertEqual(a["rev"], 2)
        with self.assertRaises(ConflictError):
            self.svc.apply(r["id"], {"op": "remove", "ma": "TD4"}, 1)
        b = self.svc.revert(r["id"], 1, 2)
        self.assertEqual(b["soModule"], 16)
        self.assertEqual([h["rev"] for h in self.svc.history(r["id"])], [1, 2, 3])

    def test_knowledge_upsert_va_tim(self):
        self.svc.add_knowledge(kind="material", code="MAT-WOOD-OAK", title="Oak 2", content="x")
        rows = [r for r in self.svc.search_knowledge("", ["material"]) if r["code"] == "MAT-WOOD-OAK"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(self.svc.search_knowledge("Tủ bếp gỗ oak sáng dài 3m"))  # tìm theo từ khóa, không cần khớp cả câu


class TestRender(Tmp):
    def test_render_fixture(self):
        res = render_views(load_spec(FIXTURE), self.tmp / "r", ["goc-anh-goc", "mat-bang"], 480, 360)
        for v in res["views"].values():
            d = Path(v["dir"])
            for f in v["files"]:
                self.assertTrue((d / f).exists(), f)
            lines = Image.open(d / "lines.png")
            self.assertEqual(lines.size, (480, 360))
            dark = int((__import__("numpy").asarray(lines) < 128).sum())
            self.assertGreater(dark, 2000)
            self.assertGreater(len(v["moduleThayDuoc"]), 8)
        cam = json.loads((Path(res["views"]["goc-anh-goc"]["dir"]) / "camera.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(cam["cx"], 240)

    def test_render_xac_dinh(self):
        s = load_spec(FIXTURE)
        a = render_views(s, self.tmp / "a", ["khu-nau"], 320, 240)
        b = render_views(s, self.tmp / "b", ["khu-nau"], 320, 240)
        pa, pb = (Path(x["views"]["khu-nau"]["dir"]) / "lines.png" for x in (a, b))
        self.assertEqual(pa.read_bytes(), pb.read_bytes())


class TestHttp(Tmp):
    def setUp(self):
        super().setUp()
        import web_server
        self.ws = web_server
        self.srv = web_server.make_server(0, self.svc)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, method, path, body=None, ctype="application/json", host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": host or f"localhost:{self.port}"}
        if body is not None:
            headers["Content-Type"] = ctype
        c.request(method, path, body=body if isinstance(body, (str, bytes)) or body is None else json.dumps(body), headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def test_chi_phuc_vu_web(self):
        self.assertEqual(self.req("GET", "/web/")[0], 200)
        for p in ["/kitchen.db", "/server.py", "/.env", "/web/../server.py", "/renders/../kitchen.db"]:
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_cors_va_content_type(self):
        st, h, _ = self.req("POST", "/api/designs", json.dumps({"mau": {}}), ctype="text/plain")
        self.assertEqual(st, 415)
        self.assertNotIn("Access-Control-Allow-Origin", h)
        self.assertEqual(self.req("GET", "/api/designs", host="evil.example")[0], 403)

    def test_luong_api(self):
        st, _, d = self.req("POST", "/api/designs", {"spec": FIXTURE})
        self.assertEqual(st, 201)
        did = json.loads(d)["id"]
        st, _, d = self.req("POST", f"/api/designs/{did}/ops", {"baseRev": 1, "op": {"op": "update", "ma": "TD1", "thayDoi": {"rong": 800}}})
        self.assertEqual((st, json.loads(d)["rev"]), (200, 2))
        st, _, d = self.req("POST", f"/api/designs/{did}/ops", {"baseRev": 1, "op": {"op": "remove", "ma": "TD1"}})
        self.assertEqual(st, 409)
        st, _, d = self.req("POST", f"/api/designs/{did}/ops", {"baseRev": 2, "op": {"op": "update", "ma": "TD1", "thayDoi": {"cao": -5}}})
        self.assertEqual(st, 422)
        st, _, d = self.req("GET", f"/api/designs/{did}/scene")
        self.assertGreater(len(json.loads(d)["parts"]), 50)
        st, _, d = self.req("GET", f"/api/designs/{did}/threejs?quocGia=AU")
        doc = json.loads(d)
        self.assertEqual((st, doc["schemaVersion"], doc["metadata"]["region"]["countryCode"]), (200, "1.1.0", "AU"))


if __name__ == "__main__":
    unittest.main()
