"""Khởi chạy bộ công cụ, thay cho launcher run.bat.

  python run.py                 web editor (http://localhost:8080/web/) + dịch vụ nhận diện cabinet-recognizer (cổng 8765)
  python run.py mcp             MCP server (stdio, do client MCP gọi) + dịch vụ nhận diện chạy nền
  python run.py recognizer      CHỈ dịch vụ nhận diện, chạy riêng để thử: trang web hộp thư http://127.0.0.1:8770 (chọn ảnh → job → Claude trả lời → Nhận kết quả → Xem 3D)
  python run.py --no-recognizer chỉ chạy web/MCP, không bật dịch vụ nhận diện
  python run.py --no-browser    không tự mở trình duyệt
  python run.py --system-python dùng python đang chạy lệnh này khi chưa có .venv (mặc định: dừng và báo)

Dịch vụ nhận diện đọc RECOG_* (và ANTHROPIC_API_KEY / OPENAI_API_KEY) từ .env hoặc môi trường; khóa chỉ nằm ở tiến trình đó. Web/MCP được
đặt CABINET_RECOGNIZER_URL trỏ tới nó khi biến này chưa có. Dịch vụ đã chạy sẵn trên cổng đó thì dùng lại, không tắt khi thoát.
Cấu hình MCP cho Claude Desktop: {"command": "<python của .venv>", "args": ["<thư mục này>/run.py", "mcp"]} (stdout của MCP chỉ dành cho giao thức,
nên nhật ký dịch vụ nhận diện ghi vào logs/recognizer.log).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RECOGNIZER_DIR = ROOT / "services" / "cabinet-recognizer"
URL = "http://localhost:8080/web/"
REQUIRED_MODULES = ("numpy", "PIL", "pydantic", "mcp")
KEY_VARS = ("RECOG_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def venv_python() -> Path:
    scripts = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    return scripts / ("python.exe" if os.name == "nt" else "python")


def read_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a .env (comments and blank lines skipped, optional quotes removed). Same convention as the app's own loader."""
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip().strip("\"'")
    return out


def recognizer_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_recognizer(python: str, port: int, dotenv: dict[str, str], log_dir: Path, say=print) -> tuple[subprocess.Popen | None, str]:
    """Start the cabinet-recognizer HTTP service in the background; returns (process or None when it was already running / failed, its URL)."""
    url = f"http://127.0.0.1:{port}"
    if recognizer_healthy(url):
        say(f"Dich vu nhan dien da chay san: {url}")
        return None, url
    env = {**dotenv, **os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(RECOGNIZER_DIR) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    if not any(env.get(k) for k in KEY_VARS) and env.get("RECOG_PROVIDER", "anthropic") != "ollama":
        say("Canh bao: chua co RECOG_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY trong .env: nhan dien bang API se bao loi khoa (che do hop thu KITCHEN_RECOGNIZER=inbox van dung duoc).")
    log_path = log_dir / "recognizer.log"
    log = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen([python, "-m", "cabinet_recognizer.http_server", "--port", str(port)], cwd=RECOGNIZER_DIR, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        if proc.poll() is not None:
            say(f"Dich vu nhan dien dung ngay khi khoi dong (xem {log_path}); tiep tuc khong co nhan dien.")
            return None, url
        if recognizer_healthy(url):
            say(f"Dich vu nhan dien: {url} (log: {log_path})")
            return proc, url
        time.sleep(0.25)
    say(f"Dich vu nhan dien chua tra loi sau 10 giay (xem {log_path}); van chay tiep.")
    return proc, url


def run_recognizer_page(python: str, port: int, dotenv: dict[str, str], no_browser: bool) -> int:
    """The recognizer on its own: the inbox web page (pick a picture, a job waits for Claude, fetch the result, view it in 3D). Jobs are kept in
    services/cabinet-recognizer/jobs, the folder the full app uses too."""
    env = {**dotenv, **os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(RECOGNIZER_DIR) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    page = f"http://127.0.0.1:{port}"
    print(f"Dich vu nhan dien (chay rieng): {page}  (Ctrl+C de dung)\nJob luu o {RECOGNIZER_DIR / 'jobs'}")
    if not no_browser:
        webbrowser.open(page)
    try:
        return subprocess.call([python, "-m", "cabinet_recognizer.web_inbox", "--port", str(port)], cwd=RECOGNIZER_DIR, env=env)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Chay web editor hoac MCP server cung dich vu nhan dien")
    ap.add_argument("mode", nargs="?", choices=("web", "mcp", "recognizer"), default="web")
    ap.add_argument("--no-recognizer", action="store_true")
    ap.add_argument("--recognizer-port", type=int, default=8765)
    ap.add_argument("--page-port", type=int, default=8770, help="cổng trang web hộp thư của chế độ recognizer")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--system-python", action="store_true")
    args = ap.parse_args(argv)

    os.chdir(ROOT)
    if venv_python().is_file():
        python = str(venv_python())
    elif args.system_python:
        python = sys.executable
    else:
        print("Khong thay .venv. Tao moi bang: python -m venv .venv")
        return 1

    check = subprocess.run(
        [python, "-c", "import " + ", ".join(REQUIRED_MODULES)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode:
        print("Dang cai/cap nhat dependencies...", file=sys.stderr)
        result = subprocess.run([python, "-m", "pip", "install", "-e", str(ROOT)])
        if result.returncode:
            return result.returncode

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    os.environ["PYTHONUTF8"] = "1"
    stdio = args.mode == "mcp"                     # stdout belongs to the MCP protocol: say nothing there
    say = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if stdio else print

    if args.mode == "recognizer":
        return run_recognizer_page(python, args.page_port, read_dotenv(ROOT / ".env"), args.no_browser)

    recognizer: subprocess.Popen | None = None
    if not args.no_recognizer and RECOGNIZER_DIR.is_dir():
        recognizer, url = start_recognizer(python, args.recognizer_port, read_dotenv(ROOT / ".env"), log_dir, say)
        os.environ.setdefault("CABINET_RECOGNIZER_URL", url)       # the app's own .env / environment still wins

    try:
        if stdio:
            return subprocess.call([python, str(ROOT / "server.py")])
        log_path = log_dir / "web.log"
        say(f"Mo {URL}")
        if not args.no_browser:
            webbrowser.open(URL)
        say(f"Log: {log_path} (Ctrl+C de dung)")
        with log_path.open("a", encoding="utf-8") as log:
            return subprocess.call([python, str(ROOT / "web_server.py")], stdout=log, stderr=subprocess.STDOUT)
    except KeyboardInterrupt:
        return 0
    finally:
        if recognizer is not None and recognizer.poll() is None:
            recognizer.terminate()
            try:
                recognizer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                recognizer.kill()
        # Giữ hành vi pause của run.bat khi script được chạy bằng cửa sổ riêng.
        if not stdio and sys.stdin.isatty():
            try:
                input("Nhan Enter de dong...")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
