"""Cập nhật kho tri thức nền (theo khu vực/quốc gia) vào kitchen.db — chỉ cần Python chuẩn.

    python seed_knowledge.py [đường_dẫn_db]

Thêm cột khu_vuc/quoc_gia nếu DB cũ chưa có; thêm mục còn thiếu; với mục đã có chỉ gán vùng khi còn mặc định
và bổ sung khóa metadata còn thiếu — nội dung bạn đã sửa được giữ nguyên. Server cũng tự chạy bước này khi khởi động.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kitchen import knowledge_seed  # noqa: E402

db = sys.argv[1] if len(sys.argv) > 1 else os.getenv("KITCHEN_DB") or str(Path(__file__).with_name("kitchen.db"))
conn = sqlite3.connect(db)
with conn:
    res = knowledge_seed.apply(conn)
tong = conn.execute("SELECT khu_vuc, COUNT(*) FROM knowledge WHERE active=1 GROUP BY khu_vuc ORDER BY khu_vuc").fetchall()
print(json.dumps({"db": db, **res, "theoKhuVuc": dict(tong)}, ensure_ascii=False, indent=1))
conn.close()
