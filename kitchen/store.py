"""Lưu trữ SQLite: kho tri thức + thiết kế có lịch sử phiên bản (append-only)."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import knowledge_seed, regions
from .spec import KitchenSpec, dump_spec

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK(kind IN ('standard','rule','material')),
 code TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
 source_url TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_knowledge_kind ON knowledge(kind, active);
CREATE TABLE IF NOT EXISTS designs (
 id TEXT PRIMARY KEY, ten TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS revisions (
 design_id TEXT NOT NULL REFERENCES designs(id), rev INTEGER NOT NULL, spec_json TEXT NOT NULL,
 thao_tac TEXT NOT NULL, nguon TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (design_id, rev)
);
CREATE TABLE IF NOT EXISTS image_jobs (
 id TEXT PRIMARY KEY, design_id TEXT NOT NULL REFERENCES designs(id), rev INTEGER NOT NULL, view TEXT NOT NULL,
 render_key TEXT NOT NULL, kind TEXT NOT NULL, mode TEXT NOT NULL, target TEXT, backend TEXT NOT NULL,
 status TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_image_jobs_design ON image_jobs(design_id, view, render_key, status);
"""

class ConflictError(Exception):
    """base_rev không còn là bản mới nhất."""


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:32] or "thiet-ke"


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            self.seed_result = knowledge_seed.apply(c)  # migration cột khu_vuc/quoc_gia + kho nền (chỉ thêm, không ghi đè)

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ---------- knowledge
    def knowledge(self, query: str = "", kinds: list[str] | None = None, quoc_gia: str | None = None,
                  khu_vuc: str | None = None, chi_vung: bool = False) -> list[dict]:
        """Tìm theo từ khóa (khớp từng từ). Có quốc gia/khu vực thì xếp mục của nơi đó lên trước:
        quốc gia > khu vực > toàn cầu > nước khác. `chi_vung`: bỏ mục của nước/khu vực khác."""
        qg, kv = regions.chuan_hoa(quoc_gia, khu_vuc)
        clauses, args = ["active=1"], []
        words = [w for w in re.split(r"\s+", query.strip()) if len(w) >= 2]
        if words:
            ors = []
            for w in words:
                ors.append("(title LIKE ? OR content LIKE ? OR code LIKE ?)")
                args += [f"%{w}%"] * 3
            clauses.append("(" + " OR ".join(ors) + ")")
        if kinds:
            clauses.append("kind IN (%s)" % ",".join("?" * len(kinds)))
            args += kinds
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(f"SELECT * FROM knowledge WHERE {' AND '.join(clauses)} ORDER BY kind, id", args)]
        out = []
        for r in rows:
            r["metadata"] = json.loads(r.pop("metadata_json") or "{}")
            d = regions.diem_uu_tien(r, qg, kv)
            if chi_vung and (qg or kv) and d < 10:
                continue
            text = f"{r['title']} {r['content']} {r['code']}".lower()
            r["_kw"] = sum(w.lower() in text for w in words)
            r["_d"] = d
            r["uuTien"] = regions.nhan_uu_tien(d) if (qg or kv) else None
            out.append(r)
        rank = regions.NGUON_RANK
        out.sort(key=lambda r: (-r["_d"], -r["_kw"], -rank.get(r["metadata"].get("loaiNguon", "chua-ro"), 0), r["id"]))
        for r in out:
            r.pop("_kw"); r.pop("_d")
            if r["uuTien"] is None:
                r.pop("uuTien")
        return out

    def upsert_knowledge(self, kind: str, code: str, title: str, content: str, source_url: str = "",
                         metadata: dict | None = None, khu_vuc: str = "GLOBAL", quoc_gia: str = "") -> dict:
        kv = (khu_vuc or "GLOBAL").upper()
        if kv not in regions.KHU_VUC:
            raise ValueError(f"khu_vuc phải là một trong: {', '.join(regions.KHU_VUC)}")
        ds = [x.strip().upper() for x in (quoc_gia or "").split(",") if x.strip()]
        for q in ds:
            regions.chuan_hoa(q)
        qg = ",".join(ds)
        meta = json.dumps(metadata or {}, ensure_ascii=False)
        with self._conn() as c:
            row = c.execute("SELECT id FROM knowledge WHERE code=? AND active=1", (code,)).fetchone()
            if row:
                c.execute("UPDATE knowledge SET kind=?, title=?, content=?, source_url=?, metadata_json=?, khu_vuc=?, quoc_gia=? WHERE id=?",
                          (kind, title, content, source_url, meta, kv, qg, row["id"]))
                return {"ok": True, "code": code, "thaoTac": "cap-nhat", "khuVuc": kv, "quocGia": qg}
            c.execute("INSERT INTO knowledge(kind,code,title,content,source_url,metadata_json,khu_vuc,quoc_gia) VALUES(?,?,?,?,?,?,?,?)",
                      (kind, code, title, content, source_url, meta, kv, qg))
            return {"ok": True, "code": code, "thaoTac": "them-moi", "khuVuc": kv, "quocGia": qg}

    def regions_summary(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT khu_vuc, quoc_gia, kind, COUNT(*) n FROM knowledge WHERE active=1 GROUP BY 1,2,3 ORDER BY 1,2,3").fetchall()
        return [dict(r) for r in rows]

    def set_active(self, code: str, active: bool) -> int:
        with self._conn() as c:
            return c.execute("UPDATE knowledge SET active=? WHERE code=?", (int(active), code)).rowcount

    def rule_rows(self) -> list[dict]:
        return self.knowledge("", ["rule", "standard"])

    # ---------- designs
    def create_design(self, spec: KitchenSpec, nguon: str = "") -> dict:
        did = f"{_slug(spec.ten)}-{uuid.uuid4().hex[:6]}"
        with self._conn() as c:
            c.execute("INSERT INTO designs(id, ten) VALUES(?,?)", (did, spec.ten))
            c.execute("INSERT INTO revisions(design_id, rev, spec_json, thao_tac, nguon) VALUES(?,?,?,?,?)",
                      (did, 1, json.dumps(dump_spec(spec), ensure_ascii=False), json.dumps({"op": "create"}), nguon))
        return {"id": did, "rev": 1}

    def get(self, design_id: str, rev: int | None = None) -> tuple[KitchenSpec, int]:
        with self._conn() as c:
            if rev is None:
                row = c.execute("SELECT rev, spec_json FROM revisions WHERE design_id=? ORDER BY rev DESC LIMIT 1", (design_id,)).fetchone()
            else:
                row = c.execute("SELECT rev, spec_json FROM revisions WHERE design_id=? AND rev=?", (design_id, rev)).fetchone()
        if not row:
            raise KeyError(f"Không có thiết kế '{design_id}'" + (f" rev {rev}" if rev else ""))
        return KitchenSpec.model_validate_json(row["spec_json"]), row["rev"]

    def add_revision(self, design_id: str, base_rev: int | None, spec: KitchenSpec, op: dict, nguon: str = "") -> int:
        with self._conn() as c:
            row = c.execute("SELECT MAX(rev) FROM revisions WHERE design_id=?", (design_id,)).fetchone()
            latest = row[0]
            if latest is None:
                raise KeyError(f"Không có thiết kế '{design_id}'")
            if base_rev is not None and base_rev != latest:
                raise ConflictError(f"base_rev={base_rev} nhưng bản mới nhất là {latest}; hãy tải lại rồi sửa")
            c.execute("INSERT INTO revisions(design_id, rev, spec_json, thao_tac, nguon) VALUES(?,?,?,?,?)",
                      (design_id, latest + 1, json.dumps(dump_spec(spec), ensure_ascii=False), json.dumps(op, ensure_ascii=False), nguon))
            c.execute("UPDATE designs SET ten=? WHERE id=?", (spec.ten, design_id))
            return latest + 1

    def list_designs(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT d.id, d.ten, d.created_at, MAX(r.rev) AS rev, MAX(r.created_at) AS updated_at "
                "FROM designs d JOIN revisions r ON r.design_id=d.id GROUP BY d.id ORDER BY updated_at DESC")]

    def history(self, design_id: str) -> list[dict]:
        with self._conn() as c:
            rows = [dict(r) for r in c.execute("SELECT rev, thao_tac, nguon, created_at FROM revisions WHERE design_id=? ORDER BY rev", (design_id,))]
        for r in rows:
            r["thaoTac"] = json.loads(r.pop("thao_tac"))
        return rows

    # ---------- image jobs (dữ liệu sinh ảnh, tách khỏi revisions thiết kế)
    _JOB_COLS = ("id", "design_id", "rev", "view", "render_key", "kind", "mode", "target", "backend", "status", "error",
                 "created_at", "updated_at")

    def _job(self, r) -> dict:
        d = {k: r[k] for k in self._JOB_COLS}
        d["request"] = json.loads(r["request_json"])
        d["result"] = json.loads(r["result_json"] or "{}")
        return d

    def create_job(self, job: dict) -> dict:
        with self._conn() as c:
            c.execute("INSERT INTO image_jobs(id, design_id, rev, view, render_key, kind, mode, target, backend, status, request_json) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (job["id"], job["design_id"], job["rev"], job["view"], job["render_key"], job["kind"], job["mode"],
                       job.get("target"), job["backend"], job["status"], json.dumps(job["request"], ensure_ascii=False)))
        return self.get_job(job["id"])

    def update_job(self, jid: str, status: str | None = None, result: dict | None = None, error: str | None = None) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT result_json FROM image_jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise KeyError(f"Không có job '{jid}'")
            res = {**json.loads(row["result_json"] or "{}"), **(result or {})}
            c.execute("UPDATE image_jobs SET status=COALESCE(?, status), result_json=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                      (status, json.dumps(res, ensure_ascii=False), error, jid))
        return self.get_job(jid)

    def get_job(self, jid: str) -> dict:
        with self._conn() as c:
            r = c.execute("SELECT * FROM image_jobs WHERE id=?", (jid,)).fetchone()
        if not r:
            raise KeyError(f"Không có job '{jid}'")
        return self._job(r)

    def list_jobs(self, design_id: str | None = None, view: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        cl, args = [], []
        for col, v in (("design_id", design_id), ("view", view), ("status", status)):
            if v:
                cl.append(f"{col}=?"); args.append(v)
        where = ("WHERE " + " AND ".join(cl)) if cl else ""
        with self._conn() as c:
            rows = c.execute(f"SELECT * FROM image_jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?", (*args, int(limit))).fetchall()
        return [self._job(r) for r in rows]

    def mark_stale_jobs(self) -> int:
        """Job đang chạy khi tiến trình dừng giữa chừng -> lỗi (không treo mãi)."""
        with self._conn() as c:
            return c.execute("UPDATE image_jobs SET status='loi:bi-ngat', error='Tiến trình dừng khi job đang chạy', "
                             "updated_at=CURRENT_TIMESTAMP WHERE status='dang-chay'").rowcount

