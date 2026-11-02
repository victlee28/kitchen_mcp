"""Render ảnh từ JSON three.js bằng trình duyệt (Chromium không giao diện), không cần API AI.

Dùng:
  python render_browser.py fixtures/bep-chu-L.threejs.json            # ảnh vào renders/browser/<tên file>/
  python render_browser.py --design <id> [--rev N]                     # JSON mới nhất của thiết kế, lưu thêm beauty.png
  python render_browser.py file.json --views goc-anh-goc,day-dai --size 1920x1440 --out anh/

Cần: pip install playwright && python -m playwright install chromium
(Hoặc không cài gì: chạy run.bat, mở http://localhost:8080/web/render.html trong trình duyệt của bạn.)
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", nargs="?", help="file JSON three.js (Complete Kitchen Three.js Scene Schema)")
    ap.add_argument("--design", help="id thiết kế trong kitchen.db (thay cho file JSON)")
    ap.add_argument("--rev", type=int)
    ap.add_argument("--views", help="danh sách góc, cách nhau dấu phẩy (mặc định: mọi camera)")
    ap.add_argument("--size", default="1280x960", help="RỘNGxCAO, mặc định 1280x960 (khớp ảnh điều khiển)")
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--out", help="thư mục ảnh ra")
    a = ap.parse_args(argv)
    if bool(a.json) == bool(a.design):
        ap.error("truyền đúng một trong hai: file JSON hoặc --design")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Thiếu Playwright: pip install playwright && python -m playwright install chromium\n"
              "Hoặc mở http://localhost:8080/web/render.html (run.bat) để render ngay trong trình duyệt.", file=sys.stderr)
        return 2
    w, h = (int(x) for x in a.size.lower().split("x"))

    sys.path.insert(0, str(ROOT))
    import web_server
    from kitchen.service import KitchenService
    svc = KitchenService(render_dir=ROOT / "renders")
    if a.design:
        doc = svc.threejs(a.design, a.rev)
        name = f"{a.design}-rev{doc['metadata']['revision']}"
    else:
        doc = json.loads(Path(a.json).read_text(encoding="utf-8"))
        name = Path(a.json).stem
    out = Path(a.out) if a.out else ROOT / "renders" / "browser" / name
    out.mkdir(parents=True, exist_ok=True)

    srv = web_server.make_server(0, svc)  # phục vụ /web (three.js nằm trong web/vendor, không cần mạng)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://localhost:{srv.server_address[1]}/web/render.html"
    opts = {"width": w, "height": h, "exposure": a.exposure}
    if a.views:
        opts["views"] = [v.strip() for v in a.views.split(",") if v.strip()]
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
            page = b.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__ready === true", timeout=30000)
            res = page.evaluate("([doc, opts]) => window.__render(doc, opts)", [doc, opts])
            b.close()
        if errs:
            print("Lỗi trang:", *errs, sep="\n  ", file=sys.stderr)
        for r in res:
            png = base64.b64decode(r["dataUrl"].split(",", 1)[1])
            f = out / f"{r['view']}.png"
            f.write_bytes(png)
            line = f"{f}"
            if a.design:
                info = svc.images.save_beauty(a.design, r["view"], png, a.rev)
                k = info["khopNet"]
                line += f"  -> beauty.png (khớp nét: {k.get('diem')}{'' if k.get('khop') is not False else ', LỆCH?'})"
            print(line)
        print(f"Xong {len(res)} ảnh trong {out}")
        return 0 if res else 1
    finally:
        srv.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
