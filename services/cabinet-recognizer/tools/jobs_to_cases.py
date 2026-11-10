"""Biến các job hộp thư đã xong thành ca kiểm chạy lại (chạy từ thư mục service):

  python tools/jobs_to_cases.py [--jobs jobs] [--out tests/data/jobs]

Mỗi ảnh khác nhau giữ job MỚI NHẤT. Ghi <mã>.png, <mã>.answers.json ({"note", "region", "answers": {bước: câu trả lời}})
và tests/golden/jobs/<mã>.spec.json = kết quả của CODE HIỆN TẠI khi chạy lại các câu trả lời đó. So với result.json lúc job chạy,
chỗ khác nhau được in ra để người đọc duyệt (giá trị vàng chỉ đổi khi chạy lại script này một cách có chủ ý).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.replay import replay_case  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="jobs")
    ap.add_argument("--out", default="tests/data/jobs")
    a = ap.parse_args()
    out, gold = Path(a.out), Path("tests/golden/jobs")
    out.mkdir(parents=True, exist_ok=True)
    gold.mkdir(parents=True, exist_ok=True)
    latest: dict[str, Path] = {}
    for job in sorted(Path(a.jobs).iterdir()):
        status = job / "status.json"
        if not status.exists() or json.loads(status.read_text(encoding="utf-8")).get("state") != "done":
            continue
        latest[hashlib.sha256((job / "image.png").read_bytes()).hexdigest()] = job      # sorted by id = by time: the last one wins
    for job in sorted(latest.values()):
        meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
        answers = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((job / "inbox" / "answers").glob("*.json"))}
        case = {"note": meta.get("note", ""), "region": meta.get("region", "VN"), "answers": answers}
        (out / f"{job.name}.png").write_bytes((job / "image.png").read_bytes())
        (out / f"{job.name}.answers.json").write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
        spec = replay_case(out / f"{job.name}.png", case)
        (gold / f"{job.name}.spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        was = json.loads((job / "result.json").read_text(encoding="utf-8"))
        same = was == spec
        print(f"{job.name}: {spec.get('layout')} {len(spec['modules'])} module" + ("" if same else "  (KHÁC result.json lúc job chạy)"))
        if not same:
            a_m, b_m = {m["id"]: m for m in was["modules"]}, {m["id"]: m for m in spec["modules"]}
            for k in sorted(set(a_m) | set(b_m)):
                if a_m.get(k) != b_m.get(k):
                    print("   ", k, {f: (a_m.get(k, {}).get(f), b_m.get(k, {}).get(f)) for f in ("x", "width", "y", "height", "type")
                                     if a_m.get(k, {}).get(f) != b_m.get(k, {}).get(f)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
