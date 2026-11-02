"""Lớp dịch vụ dùng chung cho MCP server và HTTP API (adapter chỉ gọi vào đây)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import edit, geometry, intent, regions, render, rules, threejs_export
from .spec import KitchenSpec, dump_spec, load_spec
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Nạp .env đơn giản (KEY=VALUE), không ghi đè biến môi trường đã có."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class KitchenService:
    def __init__(self, db_path: str | Path | None = None, render_dir: str | Path | None = None):
        load_dotenv()
        self.store = Store(db_path or os.getenv("KITCHEN_DB") or ROOT / "kitchen.db")
        self.render_dir = Path(render_dir or os.getenv("KITCHEN_RENDERS") or ROOT / "renders")
        from .imagejobs import ImageJobs
        self.images = ImageJobs(self)

    # ---- tạo
    def _summary(self, did: str, rev: int, spec: KitchenSpec, **extra) -> dict:
        v = self.validate_spec(spec)
        return {"id": did, "rev": rev, "ten": spec.ten, "soModule": len(spec.module), "quocGia": spec.quocGia, "khuVuc": spec.khuVuc,
                "module": [{"ma": m.ma, "loai": m.loai, "tuong": m.tuong, "tu": m.tu, "rong": m.rong, "y": m.y, "cao": m.cao}
                           for m in spec.module],
                "kiemTra": {"hopLe": v["hopLe"], "dem": v["dem"], "issues": v["issues"][:20]},
                "gocNhin": list(geometry.views_of(spec)), **extra}

    def create_from_spec(self, spec: dict | KitchenSpec, nguon: str = "spec") -> dict:
        s = spec if isinstance(spec, KitchenSpec) else load_spec(spec)
        r = self.store.create_design(s, nguon)
        return self._summary(r["id"], 1, s)

    def create_from_template(self, mau: dict | intent.MauBep, ten: str = "Thiết kế tủ bếp") -> dict:
        m = mau if isinstance(mau, intent.MauBep) else intent.MauBep.model_validate(mau)
        s = intent.from_template(m, ten, self.store.rule_rows())
        r = self.store.create_design(s, "mau")
        return self._summary(r["id"], 1, s, mau=m.model_dump())

    def create_from_prompt(self, prompt: str, ten: str | None = None) -> dict:
        mau, llm = intent.parse_prompt_llm(prompt)
        notes: list[str] = []
        nguon = "deepseek"
        if mau is None:
            mau, notes = intent.parse_prompt(prompt)
            nguon = "regex"
        s = intent.from_template(mau, ten or prompt[:60], self.store.rule_rows())
        r = self.store.create_design(s, f"prompt:{nguon}")
        return self._summary(r["id"], 1, s, mau=mau.model_dump(), phanTich={"nguon": nguon, "ghiChu": notes, "deepseek": llm})

    # ---- đọc / sửa
    def get(self, did: str, rev: int | None = None) -> dict:
        s, r = self.store.get(did, rev)
        return {"id": did, "rev": r, "spec": dump_spec(s)}

    def apply(self, did: str, op: dict[str, Any], base_rev: int | None, nguon: str = "") -> dict:
        s, cur = self.store.get(did)
        new = edit.apply_op(s, op)
        rev = self.store.add_revision(did, base_rev, new, op, nguon)
        return self._summary(did, rev, new)

    def revert(self, did: str, rev: int, base_rev: int | None) -> dict:
        old, _ = self.store.get(did, rev)
        return self.apply(did, {"op": "replace", "spec": dump_spec(old), "tuRev": rev}, base_rev, "revert")

    def history(self, did: str) -> list[dict]:
        return self.store.history(did)

    def list_designs(self) -> list[dict]:
        return self.store.list_designs()

    # ---- kiểm tra / hình học / ảnh
    def validate_spec(self, spec: KitchenSpec, quoc_gia: str | None = None, khu_vuc: str | None = None) -> dict:
        return rules.validate(spec, self.store.rule_rows(), quoc_gia, khu_vuc)

    def validate(self, did: str, rev: int | None = None, quoc_gia: str | None = None, khu_vuc: str | None = None) -> dict:
        """Kiểm tra theo quốc gia/khu vực (mặc định: của spec)."""
        s, r = self.store.get(did, rev)
        return {"id": did, "rev": r, **self.validate_spec(s, quoc_gia, khu_vuc)}

    def scene(self, did: str, rev: int | None = None) -> dict:
        s, r = self.store.get(did, rev)
        return {"id": did, "rev": r, **geometry.scene_json(s)}

    def threejs(self, did: str, rev: int | None = None, quoc_gia: str | None = None) -> dict:
        """Tài liệu theo Complete Kitchen Three.js Scene Schema v1.1 (tương thích v1.0)."""
        s, r = self.store.get(did, rev)
        return threejs_export.export(s, did, r, self.store.rule_rows(), quoc_gia)

    def render(self, did: str, rev: int | None = None, views: list[str] | None = None,
               width: int = 1280, height: int = 960) -> dict:
        if not (256 <= width <= 4096 and 256 <= height <= 4096):
            raise ValueError("width/height phải trong 256–4096")
        s, r = self.store.get(did, rev)
        out = self.render_dir / did / f"rev{r}"
        res = render.render_views(s, out, views, width, height, meta={"designId": did, "rev": r})
        return {"id": did, "rev": r, **res}

    def ai_export(self, did: str, rev: int | None = None, views: list[str] | None = None, quoc_gia: str | None = None,
                  with_images: bool = False, embed: bool = False, anh_sang: str = "ban-ngay") -> dict:
        """Gói JSON cuối cùng gửi AI tạo ảnh (renders/<id>/rev<N>/ai/ai-request.json, + zip khi kèm ảnh;
        embed=True: ai-request.full.json có nhúng ảnh nên gửi của từng góc)."""
        from . import ai_export
        return ai_export.build(self, did, rev, views, quoc_gia, with_images, embed, anh_sang)

    # ---- tri thức
    def search_knowledge(self, query: str = "", kinds: list[str] | None = None, quoc_gia: str | None = None,
                         khu_vuc: str | None = None, chi_vung: bool = False) -> list[dict]:
        return self.store.knowledge(query, kinds, quoc_gia, khu_vuc, chi_vung)

    def molding_profiles(self, did: str | None = None) -> dict:
        from . import moldings
        profs = dict(moldings.PRESETS)
        if did:
            spec, _ = self.store.get(did)
            profs.update({p.ma: p for p in spec.moldingProfiles})
        return {k: {"ma": p.ma, "ten": p.ten, "moTa": p.moTa, "kieu": "base" if "base" in k else "crown", "cao": p.cao, "nho": p.nho,
                    "points": p.points} for k, p in profs.items()}

    def list_regions(self) -> dict:
        return {"khuVuc": regions.KHU_VUC, "quocGia": {k: {"ten": v[0], "khuVuc": v[1]} for k, v in regions.QUOC_GIA.items()},
                "soMuc": self.store.regions_summary()}

    def add_knowledge(self, **kw) -> dict:
        return self.store.upsert_knowledge(**kw)
