"""HTTP service (adapter mỏng, stdlib).

  python -m cabinet_recognizer.http_server --port 8765

  POST /recognize   body = ảnh (image/png, image/jpeg)  hoặc  JSON {"imageBase64": "...", "region"?: "VN", "note"?: "gợi ý của người dùng"}
                    -> 200 {"spec": {...}, "kitchen": {"spec": KitchenSpec, "issues": [...]}}  |  4xx/5xx {"error": {kind, code, message}}
                    `spec` là định dạng riêng của bộ nhận diện; `kitchen` là bản đã đổi sang KitchenSpec kèm danh sách điều bị mất/xấp xỉ.
  GET  /health      -> {"ok": true, "provider": ..., "model": ...}
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from PIL import Image

from .config import Config
from .errors import RecognizerError, http_status
from .pipeline import recognize_auto
from .prompts import clean_note
from .to_kitchen import to_kitchen_spec
from .vision import VisionClient, make_client

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


def make_handler(config: Config, client: VisionClient) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True, "provider": config.provider, "model": config.model})
            else:
                self._send(404, {"error": {"kind": "not-found", "code": "route", "message": self.path}})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/recognize":
                self._send(404, {"error": {"kind": "not-found", "code": "route", "message": self.path}})
                return
            try:
                n = int(self.headers.get("content-length", "0"))
                if not 0 < n <= MAX_BYTES:
                    raise RecognizerError("validation", "bad-size", f"body {n} bytes")
                body = self.rfile.read(n)
                region = config.region
                note = ""
                if self.headers.get("content-type", "").startswith("application/json"):
                    req = json.loads(body)
                    region = str(req.get("region", region))
                    note = clean_note(req.get("note"))
                    body = base64.b64decode(req["imageBase64"])
                result = recognize_auto(_to_png(body), client, region=region, retries=config.max_retries, note=note)
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
    a = ap.parse_args()
    config = Config.from_env()
    server = ThreadingHTTPServer((a.host, a.port), make_handler(config, make_client(config)))
    print(f"cabinet_recognizer on http://{a.host}:{a.port}  ({config.provider}/{config.model})")
    server.serve_forever()


if __name__ == "__main__":
    main()
