"""Khởi chạy web editor, thay cho launcher run.bat."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
URL = "http://localhost:8080/web/"
REQUIRED_MODULES = ("numpy", "PIL", "pydantic", "mcp")


def main() -> int:
    os.chdir(ROOT)
    if not VENV_PYTHON.is_file():
        print("Khong thay .venv. Tao moi bang: python -m venv .venv")
        return 1

    python = str(VENV_PYTHON)
    check = subprocess.run(
        [python, "-c", "import " + ", ".join(REQUIRED_MODULES)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode:
        print("Dang cai/cap nhat dependencies...")
        result = subprocess.run([python, "-m", "pip", "install", "-e", str(ROOT)])
        if result.returncode:
            return result.returncode

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "web.log"
    os.environ["PYTHONUTF8"] = "1"
    print(f"Mo {URL}")
    webbrowser.open(URL)
    print(f"Log: {log_path} (Ctrl+C de dung)")

    try:
        with log_path.open("a", encoding="utf-8") as log:
            return subprocess.call([python, str(ROOT / "web_server.py")], stdout=log, stderr=subprocess.STDOUT)
    except KeyboardInterrupt:
        return 0
    finally:
        # Giữ hành vi pause của run.bat khi script được chạy bằng cửa sổ riêng.
        if sys.stdin.isatty():
            try:
                input("Nhan Enter de dong...")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
