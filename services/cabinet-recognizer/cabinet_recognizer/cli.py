"""Dòng lệnh (adapter).

  python -m cabinet_recognizer.cli anh.png -o tu.json [--debug-dir out/] [--replay answers.json] [--frontal-only]

--replay: dùng câu trả lời AI đã ghi (file answers.json do --debug-dir sinh ra) thay vì gọi API.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Config
from .errors import RecognizerError
from .pipeline import recognize, recognize_auto
from .vision import InboxClient, ReplayClient, VisionClient, make_client


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ảnh tủ bếp -> JSON module")
    ap.add_argument("image")
    ap.add_argument("-o", "--out", default="-")
    ap.add_argument("--debug-dir")
    ap.add_argument("--replay")
    ap.add_argument("--inbox", help="không gọi API: ghi câu hỏi ra thư mục này, chờ câu trả lời, chạy lại để đi tiếp")
    ap.add_argument("--region")
    ap.add_argument("--frontal-only", action="store_true", help="bỏ bước hỏi bố cục, dùng nhánh v0.1 (dãy thẳng chính diện)")
    a = ap.parse_args(argv)

    config = Config.from_env()
    try:
        client: VisionClient
        if a.inbox:
            client = InboxClient(a.inbox)
        elif a.replay:
            client = ReplayClient(json.loads(Path(a.replay).read_text(encoding="utf-8")))
        else:
            client = make_client(config)
        debug: dict[str, Any] = {}
        run = recognize if a.frontal_only else recognize_auto
        result = run(Path(a.image).read_bytes(), client, region=a.region or config.region,
                     retries=config.max_retries, debug=debug)
    except RecognizerError as e:
        if e.code.endswith("awaiting-answer"):
            print(e.message, file=sys.stderr)
            return 3
        print(json.dumps({"error": e.to_data()}, ensure_ascii=False), file=sys.stderr)
        return 2

    text = json.dumps(result["spec"], ensure_ascii=False, indent=2)
    if a.out == "-":
        print(text)
    else:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    if a.debug_dir:
        d = Path(a.debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        if "annotated_png" in debug:
            (d / "annotated.png").write_bytes(debug["annotated_png"])
        for wall, png in debug.get("annotated_runs", {}).items():
            (d / f"annotated-{wall}.png").write_bytes(png)
        (d / "measure.json").write_text(json.dumps(debug["measure"], indent=1), encoding="utf-8")
        (d / "answers.json").write_text(json.dumps(
            {k: _maybe_json(v) for k, v in result["answers"].items()}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    return 0


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


if __name__ == "__main__":
    raise SystemExit(main())
