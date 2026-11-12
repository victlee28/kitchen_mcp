"""Kho tri thức nền theo khu vực / quốc gia (chỉ dữ liệu + migration sqlite, không phụ thuộc thư viện ngoài).

Trường của mỗi mục:
- khu_vuc  : GLOBAL | SEA | EA | NA | EU | OC  (xem kitchen/regions.py)
- quoc_gia : mã ISO alpha-2, nhiều nước cách nhau dấu phẩy; rỗng = cả khu vực
- metadata.loaiNguon : bat-buoc (quy chuẩn/luật) | tieu-chuan | khuyen-nghi | thuc-hanh (kinh nghiệm phổ biến) | chua-ro
- metadata.kiemTra   : danh sách chủ đề mà bộ kiểm tra tự động dùng (mỗi chủ đề chọn mục ưu tiên nhất theo quốc gia)
- metadata.params    : ngưỡng máy đọc được, sửa trong DB không cần sửa code

Số liệu chỉ ghi khi đọc được từ nguồn ghi ở source_url. Bản tóm tắt không thay văn bản gốc; khi thi công
phải theo bản đầy đủ, quy chuẩn địa phương và hướng dẫn lắp của nhà sản xuất thiết bị.
"""
from typing import Any

from . import builtin


def _row(item: dict[str, Any]) -> dict[str, Any]:
    """One builtin catalog item of kind ``knowledge`` (``data/items/knowledge.json``) as a row of the ``knowledge`` table."""
    return {"kind": item["kind"], "code": item["id"], "title": item["title"], "content": item["content"], "source_url": item.get("sourceUrl", ""),
            "region": item.get("region") or "GLOBAL", "country": item.get("country") or "", "metadata": item.get("metadata") or {}}


KNOWLEDGE: list[dict[str, Any]] = [_row(it) for it in builtin.RAW.items.get("knowledge", []) if isinstance(it, dict)]
"""The builtin knowledge (the base layer of the catalog kind ``knowledge``); the table holds what is in force (see ``service``)."""

BY_CODE = {k["code"]: k for k in KNOWLEDGE}


def _cols(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(knowledge)")}


def migrate(conn) -> list[str]:
    """Thêm cột khu_vuc, quoc_gia nếu DB cũ chưa có."""
    done = []
    cols = _cols(conn)
    if "region" not in cols:
        conn.execute("ALTER TABLE knowledge ADD COLUMN region TEXT NOT NULL DEFAULT 'GLOBAL'")
        done.append("region")
    if "country" not in cols:
        conn.execute("ALTER TABLE knowledge ADD COLUMN country TEXT NOT NULL DEFAULT ''")
        done.append("country")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_region ON knowledge(region, country)")
    return done


def apply(conn) -> dict:
    """Migration + bổ sung kho nền. Thêm code còn thiếu. Với code đã có: gán khu vực/quốc gia nếu còn mặc định,
    bổ sung khóa metadata còn thiếu (nguon, loaiNguon, kiemTra, params) — không ghi đè giá trị người dùng đã sửa;
    bỏ link example.com giả."""
    import json
    cols_added = migrate(conn)
    added, upgraded = [], []
    rows = {r[0]: r for r in conn.execute("SELECT code, id, region, country, metadata_json, source_url FROM knowledge")}
    for k in KNOWLEDGE:
        if k["code"] not in rows:
            conn.execute("INSERT INTO knowledge(kind,code,title,content,source_url,metadata_json,region,country) VALUES(?,?,?,?,?,?,?,?)",
                         (k["kind"], k["code"], k["title"], k["content"], k["source_url"],
                          json.dumps(k["metadata"], ensure_ascii=False), k["region"], k["country"]))
            added.append(k["code"])
            continue
        code, rid, kv, qg, meta_json, url = rows[k["code"]]
        meta = json.loads(meta_json or "{}")
        changed = False
        for key, val in k["metadata"].items():
            if key not in meta:
                meta[key] = val
                changed = True
        new_kv, new_qg = kv, qg
        if (kv or "GLOBAL") == "GLOBAL" and not qg and (k["region"] != "GLOBAL" or k["country"]):
            new_kv, new_qg = k["region"], k["country"]
            changed = True
        new_url = url
        if (url or "").startswith("https://example.com"):
            new_url = k["source_url"]
            meta.setdefault("sourceNote", "Link example.com cũ là placeholder, đã bỏ")
            changed = True
        if changed:
            conn.execute("UPDATE knowledge SET metadata_json=?, region=?, country=?, source_url=? WHERE id=?",
                         (json.dumps(meta, ensure_ascii=False), new_kv, new_qg, new_url, rid))
            upgraded.append(code)
    return {"newColumn": cols_added, "addNew": added, "update": upgraded}
