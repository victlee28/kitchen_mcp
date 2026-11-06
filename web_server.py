"""HTTP API + web editor cục bộ (chỉ 127.0.0.1). Adapter mỏng gọi kitchen.service.

Tĩnh: chỉ /web/* và /renders/*. Không bật CORS; POST bắt buộc Content-Type application/json;
kiểm tra Host để chặn DNS rebinding.

API:
  GET  /api/designs                      danh sách
  POST /api/designs                      {"color": {...}} | {"prompt": "..."} | {"spec": {...}}
  GET  /api/designs/<id>[?rev=N]         spec
  GET  /api/designs/<id>/scene[?rev=N]   scene đã biên dịch (khối hộp)
  GET  /api/designs/<id>/threejs[?rev=N&quocGia=VN]  JSON theo Complete Kitchen Three.js Scene Schema v1.1
  GET  /api/designs/<id>/validate[?quocGia=VN]  kiểm tra theo quốc gia/khu vực
  GET  /api/knowledge?q=&kinds=&quocGia=&khuVuc=&chiVung=1   tra cứu tri thức có ưu tiên vùng
  GET  /api/regions                       khu vực, quốc gia, số mục
  GET  /api/designs/<id>/history         lịch sử
  POST /api/designs/<id>/ops             {"baseRev": N, "op": {...}, "expect"?: opHash của /propose: chỉ lưu đúng thao tác đã xem trước}
  POST /api/designs/<id>/interpret       {"text": "xóa TD3", "baseRev"?: N, "scope"?: ["TD1"], "useLlm"?: false} câu lệnh tự do -> thao tác + bản xem trước (không lưu) hoặc câu hỏi làm rõ
  POST /api/designs/<id>/template        {"template": {"kind": "run-i", "structureId": "STRUCT-..", "point": {"x": mm, "z": mm}}, "baseRev"?: N} tủ chữ I dựa vào cạnh gần điểm bấm nhất của vật thể, cánh quay ra ngoài; xem trước, không lưu
  POST /api/designs/<id>/recognize       {"source": {"kind": "photo"|"drawing", "imageBase64": "..."}, "recognizer"?: "tên", "baseRev"?: N} ảnh/bản vẽ -> bản nháp + xem trước (không lưu); chưa có bộ nhận diện thì status "unavailable"
  POST /api/designs/<id>/propose         {"baseRev": N, "op": {...}, "scope"?: ["TD1"]} xem trước, không lưu: diff, validation mới/đã hết, module bị ảnh hưởng
  POST /api/designs/<id>/revert          {"baseRev": N, "rev": M}
  POST /api/designs/<id>/render          {"rev"?, "views"?, "width"?, "height"?}
  POST /api/design                       (tương thích cũ) {"customer_prompt": "..."}

Sửa ảnh theo lớp:
  GET  /api/designs/<id>/layers?view=&rev=&all=1      layer thấy được ở góc nhìn (+ renderKey, ảnh gốc hiện dùng)
  GET  /api/designs/<id>/mask?view=&layer=&rev=       mask PNG (trắng = layer)
  GET  /api/designs/<id>/pick?view=&x=&y=&rev=&radius= chi tiết tại pixel (radius: ưu tiên tay nắm trong bán kính px) + các layer chứa nó
  POST /api/designs/<id>/image-jobs                   {view, targetLayer, instruction, mode, vatLieu, backend, reference, baseRev, kind, workflow, seed, params}
                                                      hoặc nhiều việc: {view, tasks: [{targetLayer, vatLieu, instruction}, ...], mode, backend, ...}
  GET  /api/image-jobs?design=&view=&status=          danh sách job
  GET  /api/image-jobs/<job>                          chi tiết + url file
  GET  /api/image-jobs/<job>/request[?dang=ai|day-du|gemini|web]  request gửi AI đã lọc / thân Gemini API (inline_data) / hướng dẫn Gemini web
  POST /api/image-jobs/<job>/result                   {"imageBase64": "..."} (backend job-package)
  POST /api/image-jobs/<job>/accept                   {"applyToDesign": bool, "baseRev": N}
  POST /api/image-jobs/<job>/reject | /regenerate     {}
  POST /api/image-jobs/<job>/send                     gửi job tạo với xemTruoc=true (đang 'cho-gui') sang backend
  GET  /api/image-backends                            backend + workflow ComfyUI có sẵn
  POST /api/check-request                             {"text": "<nội dung file request>"} kiểm tra file bị cắt / thiếu ảnh / base64 hỏng
  GET  /api/designs/<id>/ai-export[?rev=&views=&nhungAnh=1|dang=day-du]  JSON gửi AI (rút gọn, nhúng ảnh) / bản đầy đủ
  POST /api/designs/<id>/ai-export                    {rev?, views?, kemAnh?} ghi renders/<id>/rev<N>/ai/ (+ ai-package.zip)
  POST /api/designs/<id>/beauty                       {view, rev, imageBase64} ảnh render three.js (web/render.html) -> beauty.png
  POST /api/designs/<id>/base-image                   {view, rev, imageBase64, fit?: reject|crop|pad} replace the base image (ChatGPT render) -> base_imported.png; {view, rev, remove: true} restores the default
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import ValidationError

from kitchen.service import KitchenService
from kitchen import errors

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("web-server")
SVC: KitchenService | None = None
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
MAX_BODY = 5 * 1024 * 1024
MAX_IMAGE_BODY = 40 * 1024 * 1024  # nộp ảnh kết quả (base64)


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "KitchenDesign/0.2"

    # ---------- tiện ích
    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ALLOWED_HOSTS

    def _body(self, limit: int = MAX_BODY) -> dict:
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ApiError(415, "Content-Type phải là application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ApiError(413, "Body quá lớn")
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError as e:
            raise ApiError(400, f"JSON lỗi: {e}")
        if not isinstance(data, dict):
            raise ApiError(400, "Body phải là object JSON")
        return data

    def _static(self, path: str):
        rel = unquote(path).lstrip("/")
        if rel in ("", "web"):
            rel = "web/index.html"
        if rel.endswith("/"):
            rel += "index.html"
        base = ROOT / rel.split("/", 1)[0]
        target = (ROOT / rel).resolve()
        if rel.split("/", 1)[0] not in ("web", "renders") or not target.is_relative_to(base.resolve()) or not target.is_file():
            raise ApiError(404, "Không tìm thấy")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # ---------- định tuyến
    def _route(self, method: str):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        rev = int(q["rev"]) if q.get("rev") else None
        p = u.path
        s = SVC
        if method == "GET" and not p.startswith("/api/"):
            return self._static(p)
        if p == "/api/knowledge" and method == "GET":
            kinds = [k for k in (q.get("kinds") or "").split(",") if k] or None
            return self._json(200, s.search_knowledge(q.get("q", ""), kinds, q.get("country"), q.get("region"), q.get("regionOnly") == "1"))
        if p == "/api/molding-profiles" and method == "GET":
            return self._json(200, s.molding_profiles(q.get("design")))
        if p == "/api/regions" and method == "GET":
            return self._json(200, s.list_regions())
        if p == "/api/designs" and method == "GET":
            return self._json(200, s.list_designs())
        if p == "/api/designs" and method == "POST":
            b = self._body()
            if "spec" in b:
                return self._json(201, s.create_from_spec(b["spec"]))
            if "prompt" in b:
                if not str(b["prompt"]).strip():
                    raise ApiError(400, "prompt rỗng")
                return self._json(201, s.create_from_prompt(str(b["prompt"])))
            return self._json(201, s.create_from_template(b.get("color") or {}, b.get("name") or "Thiết kế tủ bếp"))
        if p == "/api/design" and method == "POST":  # tương thích bản cũ
            b = self._body()
            prompt = str(b.get("customer_prompt", "")).strip()
            if not prompt:
                raise ApiError(400, "customer_prompt không được rỗng")
            return self._json(200, s.create_from_prompt(prompt))
        if p == "/api/floorplans/import" and method == "POST":
            b = self._body()
            floorplan = b.get("floorplan")
            if not isinstance(floorplan, dict):
                raise ApiError(400, "floorplan must be a JSON object")
            return self._json(201, s.import_floorplan(floorplan, b.get("name"), b.get("roomId")))
        if p == "/api/floorplans/rooms" and method == "POST":
            b = self._body(MAX_BODY)
            floorplan = b.get("floorplan")
            if not isinstance(floorplan, dict):
                raise ApiError(400, "floorplan must be a JSON object")
            return self._json(200, {"rooms": s.list_floorplan_rooms(floorplan)})
        if p == "/api/check-request" and method == "POST":
            return self._json(200, s.check_request(str(self._body(MAX_IMAGE_BODY).get("text", ""))))
        if p == "/api/image-backends" and method == "GET":
            return self._json(200, s.image_backends())
        if p == "/api/image-jobs" and method == "GET":
            return self._json(200, [self._job_out(j) for j in s.images.list(q.get("design"), q.get("view"), q.get("status"))])
        m = re.fullmatch(r"/api/image-jobs/(job-[a-f0-9]+)(?:/(result|accept|reject|regenerate|request|send))?", p)
        if m:
            jid, sub = m.groups()
            if method == "GET" and sub == "request":  # ?dang=ai (mặc định, đã lọc) | day-du (kiểm tra) | gemini (thân API) | web (hướng dẫn chat)
                format = q.get("format", "ai")
                f = s.images.export_full(jid) if format == "full" else s.images.export_request(jid)
                f = {"gemini": f.with_name("gemini-request.json"), "web": f.with_name("GEMINI-WEB-GUIDE.txt")}.get(format, f)
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8" if format == "web" else "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{jid}-{f.name}"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if method == "GET" and sub is None:
                return self._json(200, self._job_out(s.images.get(jid)))
            if method == "POST" and sub == "result":
                b = self._body(MAX_IMAGE_BODY)
                try:
                    raw = base64.b64decode(str(b.get("imageBase64", "")).split(",")[-1], validate=True)
                except (binascii.Error, ValueError):
                    raise ApiError(400, "imageBase64 không hợp lệ")
                return self._json(200, self._job_out(s.images.submit_result(jid, raw)))
            if method == "POST" and sub == "accept":
                b = self._body()
                return self._json(200, self._job_out(s.images.accept(jid, bool(b.get("applyToDesign")), b.get("baseRev"))))
            if method == "POST" and sub == "send":
                self._body()
                return self._json(200, self._job_out(s.images.send(jid)))
            if method == "POST" and sub == "reject":
                self._body()
                return self._json(200, self._job_out(s.images.reject(jid)))
            if method == "POST" and sub == "regenerate":
                b = self._body()
                return self._json(201, self._job_out(s.images.regenerate(jid, b.get("seed"))))
            raise ApiError(405, "Phương thức không hỗ trợ")
        m = re.fullmatch(r"/api/designs/([a-z0-9-]+)(?:/(scene|threejs|validate|history|ops|revert|render|layers|mask|pick|image-jobs|beauty|base-image|ai-export|floorplan-bind|view-status|regenerate-stale|propose|interpret|recognize|template))?", p)
        if not m:
            raise ApiError(404, "Không có endpoint")
        did, sub = m.groups()
        if method == "GET":
            if sub is None:
                return self._json(200, s.get(did, rev))
            if sub == "scene":
                return self._json(200, s.scene(did, rev))
            if sub == "threejs":
                return self._json(200, s.threejs(did, rev, q.get("country")))
            if sub == "validate":
                return self._json(200, s.validate(did, rev, q.get("country"), q.get("region")))
            if sub == "history":
                return self._json(200, s.history(did))
            if sub == "ai-export":  # tải thẳng JSON cuối cùng (không ghi ảnh)
                emb = q.get("embedImages") == "1" and q.get("format") != "full"  # day-du = ai-request.json đầy đủ (cảnh three.js…)
                res = s.ai_export(did, rev, [v for v in (q.get("views") or "").split(",") if v] or None, q.get("country"), False, emb,
                                  q.get("lighting") or "daylight")
                body = Path(res["file"]).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{did}-rev{res["rev"]}-{Path(res["file"]).name}"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if sub == "view-status":
                return self._json(200, {"views": s.images.view_status(did, rev)})
            if sub == "layers":
                res = s.images.layers(did, self._need(q, "view"), rev, q.get("all") == "1")
                res["url"] = self._url(res.pop("dir"))
                res["baseImage"]["url"] = self._ref_url(res)
                return self._json(200, res)
            if sub == "mask":
                return self._send(200, s.images.mask_png(did, self._need(q, "view"), self._need(q, "layer"), rev), "image/png")
            if sub == "pick":
                return self._json(200, s.images.pick(did, self._need(q, "view"), int(self._need(q, "x")), int(self._need(q, "y")), rev, int(q.get("radius") or 0)))
        if method == "POST":
            b = self._body(MAX_IMAGE_BODY if sub in ("beauty", "base-image", "recognize") else MAX_BODY)
            if sub == "regenerate-stale":
                return self._json(201, s.images.regenerate_stale(did, b.get("views") if isinstance(b.get("views"), list) else None,
                                                                 b.get("backend") or "recolor", b.get("baseRev")))
            if sub == "floorplan-bind":
                be = b.get("backEdge")
                return self._json(200, s.bind_floorplan(did, int(be) if be is not None else None, float(b.get("offset") or 0), b.get("rev")))
            if sub == "beauty":
                try:
                    raw = base64.b64decode(str(b.get("imageBase64", "")).split(",")[-1], validate=True)
                except (binascii.Error, ValueError):
                    raise ApiError(400, "imageBase64 không hợp lệ")
                res = s.images.save_beauty(did, str(b.get("view") or ""), raw, b.get("rev"))
                res["url"] = (self._url(res.pop("dir")) or "") + "beauty.png"
                return self._json(200, res)
            if sub == "base-image":
                if b.get("remove"):
                    res = s.images.clear_imported_base(did, str(b.get("view") or ""), b.get("rev"))
                    res.pop("dir")
                    return self._json(200, res)
                try:
                    raw = base64.b64decode(str(b.get("imageBase64", "")).split(",")[-1], validate=True)
                except (binascii.Error, ValueError):
                    raise ApiError(400, "imageBase64 không hợp lệ")
                res = s.images.import_base(did, str(b.get("view") or ""), raw, b.get("rev"), "ChatGPT (manual import)", str(b.get("fit") or "reject"))
                res["url"] = (self._url(res.pop("dir")) or "") + "base_imported.png"
                return self._json(200, res)
            if sub == "ai-export":
                views = b.get("views") if isinstance(b.get("views"), list) else None
                res = s.ai_export(did, b.get("rev"), views, b.get("country"), bool(b.get("withImage")), False, b.get("lighting") or "daylight")
                u = self._url(res.pop("dir"))
                res["url"] = {"json": u and u + "ai-request.json", **({"zip": u and u + "ai-package.zip"} if res.get("zip") else {})}
                res.pop("file"); res.pop("zip", None)
                return self._json(200, res)
            if sub == "ops":
                if "op" not in b:
                    raise ApiError(400, "thiếu op")
                if b.get("expect") is not None and not isinstance(b["expect"], str):
                    raise ApiError(400, "expect phải là opHash của bản xem trước")
                return self._json(200, s.apply(did, b["op"], b.get("baseRev"), "web", b.get("expect")))
            if sub == "propose":
                if not isinstance(b.get("op"), dict):
                    raise ApiError(400, "thiếu op")
                scope = b.get("scope")
                if scope is not None and not (isinstance(scope, list) and all(isinstance(x, str) for x in scope)):
                    raise ApiError(400, "scope phải là danh sách id module")
                return self._json(200, s.propose(did, b["op"], b.get("baseRev"), scope, b.get("country")))
            if sub == "template":
                if not isinstance(b.get("template"), dict):
                    raise ApiError(400, "thiếu template")
                return self._json(200, s.template(did, b["template"], b.get("baseRev"), b.get("country")))
            if sub == "recognize":
                if not isinstance(b.get("source"), dict):
                    raise ApiError(400, "thiếu source")
                return self._json(200, s.recognize(did, b["source"], b.get("recognizer"), b.get("baseRev"), b.get("country")))
            if sub == "interpret":
                if not isinstance(b.get("text"), str):
                    raise ApiError(400, "thiếu text")
                scope = b.get("scope")
                if scope is not None and not (isinstance(scope, list) and all(isinstance(x, str) for x in scope)):
                    raise ApiError(400, "scope phải là danh sách id module")
                return self._json(200, s.interpret(did, b["text"], b.get("baseRev"), scope, b.get("country"), bool(b.get("useLlm"))))
            if sub == "revert":
                return self._json(200, s.revert(did, int(b["rev"]), b.get("baseRev")))
            if sub == "image-jobs":
                job = s.images.create(did, str(b.get("view") or ""), b.get("targetLayer"), instruction=str(b.get("instruction") or ""),
                                      mode=b.get("mode") or "quick", material=b.get("material") or None, backend=b.get("backend") or "recolor",
                                      reference=b.get("reference"), base_rev=b.get("baseRev"), kind=b.get("kind") or "edit", workflow=b.get("workflow"),
                                      seed=b.get("seed"), params=b.get("params") if isinstance(b.get("params"), dict) else None,
                                      tasks=b.get("tasks") if isinstance(b.get("tasks"), list) and b.get("tasks") else None,
                                      preview=bool(b.get("preview")), geometry_items=b.get("geometry_edit") if isinstance(b.get("geometry_edit"), list) else None,
                                      operation=b.get("operation") or None, lighting=b.get("lighting") or None,
                                      style_from=b.get("styleFrom") or None)
                return self._json(201, self._job_out(job))
            if sub == "render":
                res = s.render(did, b.get("rev"), b.get("views"), int(b.get("width", 1280)), int(b.get("height", 960)))
                for v in res["views"].values():  # đường dẫn tương đối để web hiển thị
                    v["url"] = "/" + Path(v["dir"]).resolve().relative_to(ROOT).as_posix() + "/"
                return self._json(200, res)
        raise ApiError(405, "Phương thức không hỗ trợ")

    @staticmethod
    def _need(q: dict, k: str) -> str:
        if not q.get(k):
            raise ApiError(400, f"thiếu tham số {k}")
        return q[k]

    @staticmethod
    def _url(path: str) -> str | None:
        try:
            return "/" + Path(path).resolve().relative_to(ROOT).as_posix() + "/"
        except ValueError:
            return None  # thư mục render ngoài dự án (test)

    def _ref_url(self, layers_res: dict) -> str | None:
        ref = layers_res["baseImage"]
        if ref["type"] == "job":
            u = self._url(SVC.images.get(ref["jobId"])["result"]["dir"])
            return u and u + "composite.png"
        name = {"beauty": "beauty.png", "imported": "base_imported.png"}.get(ref["type"], "albedo.png")
        return layers_res["url"] and layers_res["url"] + name

    def _job_out(self, j: dict) -> dict:
        d = j["result"].get("dir")
        u = self._url(d) if d else None
        if u:
            image = sorted(x.name for x in Path(d).glob("image-[0-9]-*.png"))  # ảnh đính kèm gửi AI, đánh số theo thứ tự
            files = [f for f in ("request.json", "request.full.json", "gemini-request.json", "GEMINI-WEB-GUIDE.txt", *image,
                                 "reference.png", "reference_marked.png", "new_geometry.png", "target.png", "mask.png", "mask_color.png", "raw.png", "composite.png",
                                 "workflow_api.json", "INSTRUCTIONS.txt", "report.json") if (Path(d) / f).exists()]
            j = {**j, "url": u, "files": {f: u + f for f in files}}
        return j

    def _handle(self, method: str):
        t = time.perf_counter()
        try:
            if not self._host_ok():
                raise ApiError(403, "Host không được phép")
            self._route(method)
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except errors.KitchenError as e:             # one mapping: kind -> status; the stable code is added for clients
            self._json(errors.http_status(e), {"error": str(e), "code": e.code})
        except FileNotFoundError as e:
            self._json(404, {"error": str(e)})
        except ValidationError as e:
            self._json(422, {"error": "Dữ liệu không hợp lệ", "part": [
                {"position": ".".join(map(str, x["loc"])), "errors": x["msg"]} for x in e.errors()[:10]]})
        except (KeyError, ValueError) as e:
            self._json(404 if isinstance(e, KeyError) else 400, {"error": str(e).strip("'\"")})
        except Exception:
            log.exception("[HTTP] %s %s lỗi", method, self.path)
            self._json(500, {"error": "Lỗi máy chủ, xem log"})
        finally:
            log.info("[HTTP] %s %s %.2fs", method, self.path, time.perf_counter() - t)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def log_message(self, format, *args):
        pass


def make_server(port: int = 8080, svc: KitchenService | None = None) -> ThreadingHTTPServer:
    global SVC
    SVC = svc or KitchenService(render_dir=ROOT / "renders")
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    port = int(os.getenv("KITCHEN_PORT", "8080"))
    srv = make_server(port)
    print(f"Web editor: http://localhost:{port}/web/", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
