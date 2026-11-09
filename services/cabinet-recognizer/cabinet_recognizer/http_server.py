"""HTTP service (adapter mỏng, stdlib).

  python -m cabinet_recognizer.http_server --port 8765

  POST /recognize   body = ảnh (image/png, image/jpeg)  hoặc  JSON {"imageBase64": "...", "region"?: "VN", "note"?: "gợi ý của người dùng"}
                    -> 200 {"spec": {...}, "kitchen": {"spec": KitchenSpec, "issues": [...]}}  |  4xx/5xx {"error": {kind, code, message}}
                    `spec` là định dạng riêng của bộ nhận diện; `kitchen` là bản đã đổi sang KitchenSpec kèm danh sách điều bị mất/xấp xỉ.
  POST /jobs        cùng body như /recognize, nhưng KHÔNG gọi API: tạo job (thư mục jobs/<mã>/), chạy tới bước cần AI rồi dừng
                    -> 202 {"id", "state": "waiting", "step", "answered"}   (người/Claude trả lời vào jobs/<mã>/inbox/answers/<bước>.json)
  POST /jobs/<mã>/resume   (hoặc GET /jobs/<mã>)  chạy tiếp từ các câu trả lời đã có
                    -> 200 {"id", "state": "waiting"|"done"|"error", ...}; khi "done" có thêm "kitchen": {"spec", "issues"} như /recognize
  GET  /health      -> {"ok": true, "provider": ..., "model": ...}
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from PIL import Image

from .config import Config
from .errors import RecognizerError, http_status
from .pipeline import recognize_auto
from .prompts import clean_note
from .to_kitchen import to_kitchen_spec
from .vision import VisionClient, make_client
from .web_inbox import JOB_ID, create_job, run_job

MAX_BYTES = 20 * 1024 * 1024


def _to_png(data: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # ảnh hỏng là lỗi đầu vào  # noqa: BLE001
        raise RecognizerError("validation", "bad-image", str(e)) from e
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _kitchen(rec: dict[str, Any]) -> dict[str, Any]:
    try:
        return to_kitchen_spec(rec)
    except (KeyError, TypeError, ValueError) as e:       # kết quả nhận diện thiếu trường mà bước đổi sang KitchenSpec cần
        raise RecognizerError("validation", "convert-failed", f"không đổi được sang KitchenSpec: {e!r}") from e


def _job_payload(job: Path, status: dict[str, Any]) -> dict[str, Any]:
    """The job's status; when finished also the converted ``kitchen`` ({"spec", "issues"}), read back from the files ``run_job`` wrote."""
    out = {k: v for k, v in status.items() if k in ("id", "state", "step", "answered", "error", "warnings", "layout", "modules")}
    if status.get("state") == "done":
        out["kitchen"] = {"spec": json.loads((job / "kitchen-spec.json").read_text(encoding="utf-8")), "issues": status.get("kitchenIssues", [])}
    return out


class NoModelClient:
    """Stands in when no model client can be built (no API key): ``/recognize`` answers with that error, while ``/jobs`` (the inbox, which
    never calls a model) keeps working."""

    def __init__(self, error: RecognizerError) -> None:
        self.error = error

    def complete(self, step: str, prompt: str, images: list[bytes]) -> str:
        raise self.error


def client_or_none(config: Config) -> VisionClient:
    try:
        return make_client(config)
    except RecognizerError as e:
        if e.code != "missing-api-key":
            raise
        print(f"Chua co khoa API ({e.message}): /recognize se bao loi, /jobs (hop thu) van chay.")
        return NoModelClient(e)


def make_handler(config: Config, client: VisionClient, jobs_root: Path | None = None) -> type[BaseHTTPRequestHandler]:
    root = jobs_root or Path("jobs")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _request(self) -> tuple[bytes, str, str]:
            """(PNG, region, note) of a POST body: raw image bytes, or JSON {"imageBase64", "region"?, "note"?}."""
            n = int(self.headers.get("content-length", "0"))
            if not 0 < n <= MAX_BYTES:
                raise RecognizerError("validation", "bad-size", f"body {n} bytes")
            body = self.rfile.read(n)
            region, note = config.region, ""
            if self.headers.get("content-type", "").startswith("application/json"):
                req = json.loads(body)
                region = str(req.get("region", region))
                note = clean_note(req.get("note"))
                body = base64.b64decode(req["imageBase64"])
            return _to_png(body), region, note

        def _job(self, job_id: str) -> Path:
            job = root / job_id
            if not JOB_ID.match(job_id) or not (job / "job.json").is_file():
                raise RecognizerError("not-found", "no-such-job", job_id)
            return job

        def do_GET(self) -> None:  # noqa: N802
            parts = self.path.strip("/").split("/")
            if self.path == "/health":
                self._send(200, {"ok": True, "provider": config.provider, "model": config.model})
            elif len(parts) == 2 and parts[0] == "jobs":
                self._resume(parts[1])
            else:
                self._send(404, {"error": {"kind": "not-found", "code": "route", "message": self.path}})

        def _resume(self, job_id: str) -> None:
            try:
                job = self._job(job_id)
                self._send(200, _job_payload(job, run_job(job)))
            except RecognizerError as e:
                self._send(http_status(e), {"error": e.to_data()})

        def do_POST(self) -> None:  # noqa: N802
            parts = self.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "resume":
                return self._resume(parts[1])
            if self.path not in ("/recognize", "/jobs"):
                self._send(404, {"error": {"kind": "not-found", "code": "route", "message": self.path}})
                return
            try:
                png, region, note = self._request()
                if self.path == "/jobs":
                    root.mkdir(parents=True, exist_ok=True)
                    job = create_job(root, png, note, region, datetime.now())
                    self._send(202, _job_payload(job, run_job(job)))
                    return
                result = recognize_auto(png, client, region=region, retries=config.max_retries, note=note)
                self._send(200, {"spec": result["spec"], "kitchen": _kitchen(result["spec"])})
            except RecognizerError as e:
                self._send(http_status(e), {"error": e.to_data()})
            except (ValueError, KeyError) as e:
                self._send(400, {"error": {"kind": "validation", "code": "bad-request", "message": str(e)}})

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--jobs", default="jobs", help="thư mục chứa job của chế độ hộp thư (POST /jobs)")
    a = ap.parse_args()
    config = Config.from_env()
    server = ThreadingHTTPServer((a.host, a.port), make_handler(config, client_or_none(config), Path(a.jobs)))
    print(f"cabinet_recognizer on http://{a.host}:{a.port}  ({config.provider}/{config.model})")
    server.serve_forever()


if __name__ == "__main__":
    main()
