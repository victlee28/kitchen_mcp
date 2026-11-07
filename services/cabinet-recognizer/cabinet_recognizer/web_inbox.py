"""Trang web nhỏ cho chế độ hộp thư (adapter, stdlib).

  python -m cabinet_recognizer.web_inbox --port 8770      -> mở http://127.0.0.1:8770

Luồng: chọn ảnh + ghi chú -> tạo job (jobs/<id>/) -> service chạy tới bước cần AI rồi dừng.
Người/AI trả lời vào jobs/<id>/inbox/answers/<bước>.json (lệnh cho AI: xem README).
Bấm "Nhận kết quả" -> service chạy lại; xong thì tải result.json.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image

from .errors import RecognizerError
from .pipeline import recognize_auto
from .to_kitchen import to_kitchen_spec
from .vision import InboxClient, VisionClient

JOB_ID = re.compile(r"^[0-9]{8}-[0-9]{6}(-[0-9]+)?$")
MAX_BYTES = 25 * 1024 * 1024
HERE = Path(__file__).resolve().parent
VIEWER = HERE / "viewer.html"
BUILDER = HERE.parent / "tools" / "threejs" / "kitchen3d.js"   # bộ dựng three.js dùng chung với tools/threejs


class NoteClient:
    """Gắn ghi chú của người dùng vào cuối mọi câu hỏi gửi AI."""

    def __init__(self, inner: VisionClient, note: str) -> None:
        self.inner, self.note = inner, note.strip()

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        if self.note:
            prompt = f"{prompt}\n\nUser notes about this kitchen (use them if relevant): {self.note}"
        return self.inner.complete(step, prompt, images)


def run_job(job: Path) -> dict[str, Any]:
    """Chạy (hoặc chạy tiếp) một job; trả trạng thái và ghi status.json."""
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    client = NoteClient(InboxClient(str(job / "inbox")), meta.get("note", ""))
    debug: dict[str, Any] = {}
    status: dict[str, Any] = {"id": job.name, "createdAt": meta["createdAt"], "note": meta.get("note", "")}
    try:
        res = recognize_auto((job / "image.png").read_bytes(), client, region=meta.get("region", "VN"), debug=debug)
        (job / "result.json").write_text(json.dumps(res["spec"], ensure_ascii=False, indent=2), encoding="utf-8")
        conv = to_kitchen_spec(res["spec"])
        (job / "kitchen-spec.json").write_text(json.dumps(conv["spec"], ensure_ascii=False, indent=2), encoding="utf-8")
        status["kitchenIssues"] = conv["issues"]
        status.update(state="done", modules=len(res["spec"]["modules"]), layout=res["spec"].get("layout"),
                      warnings=res["spec"].get("warnings", []))
    except RecognizerError as e:
        if e.code.endswith("awaiting-answer"):
            pend = sorted(p.name for p in (job / "inbox" / "pending").iterdir()
                          if not (job / "inbox" / "answers" / f"{p.name}.json").exists())
            status.update(state="waiting", step=pend[-1] if pend else "?",
                          answered=sorted(p.stem for p in (job / "inbox" / "answers").glob("*.json")))
        else:
            status.update(state="error", error=e.to_data())
    out = job / "debug"
    out.mkdir(exist_ok=True)
    for k, v in debug.get("annotated_runs", {}).items():
        (out / f"annotated-{k}.png").write_bytes(v)
    if "annotated_png" in debug:
        (out / "annotated.png").write_bytes(debug["annotated_png"])
    (job / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def create_job(root: Path, image: bytes, note: str, region: str, now: datetime) -> Path:
    try:
        img = Image.open(io.BytesIO(image))
        img.load()
    except Exception as e:  # ảnh hỏng là lỗi đầu vào  # noqa: BLE001
        raise RecognizerError("validation", "bad-image", str(e)) from e
    base = now.strftime("%Y%m%d-%H%M%S")
    job, n = root / base, 1
    while job.exists():
        n += 1
        job = root / f"{base}-{n}"
    (job / "inbox" / "answers").mkdir(parents=True)
    (job / "inbox" / "pending").mkdir(parents=True)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    (job / "image.png").write_bytes(buf.getvalue())
    (job / "job.json").write_text(json.dumps({"createdAt": now.isoformat(timespec="seconds"), "note": note,
                                              "region": region}, ensure_ascii=False, indent=2), encoding="utf-8")
    return job


PAGE = """<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nhận diện tủ bếp</title><style>
body{font-family:system-ui,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1d1f22;background:#f6f6f4}
h1{font-size:22px}.card{background:#fff;border:1px solid #ddd;border-radius:10px;padding:16px;margin:14px 0}
label{display:block;font-weight:600;margin:10px 0 4px}textarea{width:100%;min-height:80px;font:inherit;padding:8px;box-sizing:border-box}
button{background:#2b6cdf;color:#fff;border:0;border-radius:6px;padding:9px 16px;font-size:14px;cursor:pointer}button.sec{background:#555}
button:disabled{opacity:.5}#preview{max-width:100%;max-height:260px;margin-top:8px;border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:7px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
.st{font-weight:600}.waiting{color:#b26b00}.done{color:#178a3c}.error{color:#c0392b}code{background:#eef;padding:1px 5px;border-radius:4px}
.msg{background:#fff7e6;border:1px solid #f0c36d;padding:10px;border-radius:6px;margin-top:10px}
</style></head><body>
<h1>Nhận diện tủ bếp → JSON</h1>
<div class="card">
 <label>Ảnh tủ bếp</label><input type="file" id="img" accept="image/*"><br><img id="preview" hidden>
 <label>Ghi chú / prompt (không bắt buộc)</label>
 <textarea id="note" placeholder="Ví dụ: bếp chữ L, tủ lạnh rộng 910, mặt bếp cao 880..."></textarea>
 <label>Vùng tiêu chuẩn</label><select id="region"><option>VN</option><option>US</option><option>EU</option><option>JP</option></select><br><br>
 <button id="send">Gửi</button><div id="sendmsg"></div>
</div>
<div class="card"><h3 style="margin-top:0">Các job</h3><table id="jobs"><tr><th>Mã job</th><th>Ghi chú</th><th>Trạng thái</th><th></th></tr></table></div>
<script>
const $=s=>document.querySelector(s);
$('#img').onchange=()=>{const f=$('#img').files[0]; if(f){$('#preview').src=URL.createObjectURL(f);$('#preview').hidden=false}};
function stText(s){ if(s.state==='done') return `<span class="st done">Xong</span> · ${s.layout||''} · ${s.modules} module`+(s.warnings&&s.warnings.length?` · ${s.warnings.length} cảnh báo`:'');
  if(s.state==='waiting') return `<span class="st waiting">Chờ AI trả lời bước <code>${s.step}</code></span><br><small>Đã trả lời: ${(s.answered||[]).join(', ')||'chưa có'}</small>`;
  if(s.state==='error') return `<span class="st error">Lỗi</span> <code>${s.error.code}</code><br><small>${s.error.message}</small>`; return s.state; }
function row(s){ const tr=document.createElement('tr'); tr.id='j'+s.id;
  tr.innerHTML=`<td><code>${s.id}</code></td><td>${(s.note||'').replace(/</g,'&lt;')}</td><td>${stText(s)}</td>
  <td><button class="sec" onclick="resume('${s.id}',this)">Nhận kết quả</button> ${s.state==='done'?`<a href="/jobs/${s.id}/view" target="_blank"><button>Xem 3D</button></a> <a href="/jobs/${s.id}/result.json?download=1">JSON nhận diện</a> · <a href="/jobs/${s.id}/kitchen-spec.json?download=1">KitchenSpec</a>`+((s.kitchenIssues||[]).length?`<br><small>${s.kitchenIssues.length} điểm chuyển đổi xấp xỉ</small>`:''):''}</td>`; return tr; }
async function load(){ const r=await fetch('/jobs'); const js=await r.json(); const t=$('#jobs'); t.querySelectorAll('tr[id]').forEach(x=>x.remove()); js.forEach(s=>t.appendChild(row(s))); }
async function resume(id,btn){ btn.disabled=true; const r=await fetch('/jobs/'+id+'/resume',{method:'POST'}); const s=await r.json(); btn.disabled=false;
  document.getElementById('j'+id).replaceWith(row(s)); if(s.state==='done') location.href='/jobs/'+id+'/result.json?download=1'; }
$('#send').onclick=async()=>{ const f=$('#img').files[0]; if(!f){$('#sendmsg').textContent='Chọn ảnh trước';return}
  $('#send').disabled=true; $('#sendmsg').textContent='Đang xử lý...';
  const b64=await new Promise(res=>{const fr=new FileReader(); fr.onload=()=>res(fr.result.split(',')[1]); fr.readAsDataURL(f)});
  const r=await fetch('/jobs',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({imageBase64:b64,note:$('#note').value,region:$('#region').value})});
  const s=await r.json(); $('#send').disabled=false;
  if(s.state==='waiting') $('#sendmsg').innerHTML=`<div class="msg">Đã tạo job <code>${s.id}</code>. Hãy nhắn Claude: <b>"trả lời hộp thư job ${s.id}"</b>. Khi Claude báo xong, bấm <b>Nhận kết quả</b> ở dòng của job.</div>`;
  else $('#sendmsg').textContent=s.error?('Lỗi: '+s.error.message):'Xong'; load(); };
load();
</script></body></html>"""


def make_handler(root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: Any) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _job(self, jid: str) -> Path | None:
            return root / jid if JOB_ID.match(jid) and (root / jid / "job.json").exists() else None

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/static/kitchen3d.js":
                self._send(200, BUILDER.read_bytes(), "text/javascript; charset=utf-8")
            elif path.startswith("/jobs/") and path.endswith("/view"):
                job = self._job(path.split("/")[2])
                if job is None or not (job / "result.json").exists():
                    self._json(404, {"error": "chưa có kết quả"})
                else:
                    page = VIEWER.read_text(encoding="utf-8").replace("__JOB__", job.name)
                    self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/jobs":
                out = []
                for j in sorted(root.glob("*/status.json"), reverse=True):
                    out.append(json.loads(j.read_text(encoding="utf-8")))
                self._json(200, out)
            elif path.startswith("/jobs/") and path.split("/")[-1] in ("result.json", "kitchen-spec.json"):
                job = self._job(path.split("/")[2])
                fname = path.split("/")[-1]
                if job is None or not (job / fname).exists():
                    self._json(404, {"error": "chưa có kết quả"})
                else:
                    label = "tu-bep" if fname == "result.json" else "kitchen-spec"
                    extra = {"content-disposition": f'attachment; filename="{label}-{job.name}.json"'} if "download" in self.path else {}
                    self._send(200, (job / fname).read_bytes(), "application/json; charset=utf-8", extra)
            else:
                self._json(404, {"error": "không có trang này"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path == "/jobs":
                    n = int(self.headers.get("content-length", "0"))
                    if not 0 < n <= MAX_BYTES:
                        raise RecognizerError("validation", "bad-size", f"{n} bytes")
                    req = json.loads(self.rfile.read(n))
                    job = create_job(root, base64.b64decode(req["imageBase64"]), str(req.get("note", ""))[:2000],
                                     str(req.get("region", "VN"))[:8], datetime.now())
                    self._json(200, run_job(job))
                elif self.path.startswith("/jobs/") and self.path.endswith("/resume"):
                    job = self._job(self.path.split("/")[2])
                    if job is None:
                        self._json(404, {"error": "không có job"})
                    else:
                        self._json(200, run_job(job))
                else:
                    self._json(404, {"error": "không có trang này"})
            except RecognizerError as e:
                self._json(422, {"state": "error", "error": e.to_data()})
            except (ValueError, KeyError) as e:
                self._json(400, {"state": "error", "error": {"code": "bad-request", "message": str(e)}})

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--jobs", default="jobs", help="thư mục chứa job")
    ap.add_argument("--resume", help="chạy tiếp một job rồi thoát (dùng cho AI trả lời hộp thư)")
    a = ap.parse_args()
    root = Path(a.jobs)
    root.mkdir(parents=True, exist_ok=True)
    if a.resume:
        print(json.dumps(run_job(root / a.resume), ensure_ascii=False, indent=1))
        return
    print(f"Mở http://{a.host}:{a.port}  (job lưu ở {root.resolve()})")
    ThreadingHTTPServer((a.host, a.port), make_handler(root)).serve_forever()


if __name__ == "__main__":
    main()
