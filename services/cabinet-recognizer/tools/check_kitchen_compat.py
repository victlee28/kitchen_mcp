"""Kiểm tra JSON của recognizer với chính code kitchen service (chạy từ thư mục gốc mcp-imagev2).

  python services/cabinet-recognizer/tools/check_kitchen_compat.py ket-qua.json [--out kitchen-spec.json]

Chuyển sang KitchenSpec, rồi: load_spec -> compile_spec (hình học) -> threejs_export.export -> rules.validate.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # cabinet_recognizer
sys.path.insert(0, str(Path.cwd()))                             # kitchen (chạy từ gốc mcp-imagev2)

from cabinet_recognizer.to_kitchen import to_kitchen_spec  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--out")
    ap.add_argument("--country", default="VN")
    a = ap.parse_args()
    conv = to_kitchen_spec(json.loads(Path(a.result).read_text(encoding="utf-8")))
    for i in conv["issues"]:
        print("chuyển đổi:", i["code"], i.get("module", ""), "-", i["message"])
    if a.out:
        Path(a.out).write_text(json.dumps(conv["spec"], ensure_ascii=False, indent=2), encoding="utf-8")
    from kitchen import rules, threejs_export
    from kitchen.geometry import compile_spec
    from kitchen.spec import load_spec
    spec = load_spec(conv["spec"])
    print(f"load_spec: {len(spec.module)} module")
    print(f"compile_spec: {len(compile_spec(spec).parts)} khối")
    threejs_export.export(spec, created_at="1970-01-01T00:00:00Z")
    print("threejs_export: ok")
    worst = 0
    for i in rules.validate(spec, country=a.country)["issues"]:
        if i["severity"] != "info":
            print(f"rules {i['severity']}: {i['rule']} {i.get('module')} {i.get('content', '')}")
        worst = max(worst, {"info": 0, "warning": 1, "error": 2}.get(i["severity"], 0))
    return 2 if worst == 2 else 0


if __name__ == "__main__":
    raise SystemExit(main())
