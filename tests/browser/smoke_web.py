"""Browser smoke test of the web editor (real Chromium via Playwright). Characterises the main flows BEFORE web/app.js is split.

  python tests/browser/smoke_web.py            exit 0 = all flows work; prints one line per check

Needs: pip install playwright (+ a Chromium that Playwright can launch). Skipped (exit 0, a note is printed) when Playwright or a launchable Chromium is missing.
Starts web_server.py on a temporary database and port; nothing of the real database is touched.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright is not installed")
    sys.exit(0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(base, path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-"))
    port = free_port()
    env = {**os.environ, "KITCHEN_DB": str(tmp / "k.db"), "KITCHEN_RENDERS": str(tmp / "r"), "KITCHEN_PORT": str(port), "GEMINI_API_KEY": "", "PYTHONPATH": str(ROOT)}
    srv = subprocess.Popen([sys.executable, str(ROOT / "web_server.py")], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    failures: list[str] = []

    def check(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/designs", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            print("FAIL server did not start")
            return 1
        design = post(base, "/api/designs", {"prompt": "Bếp chữ L cạnh dài 2,8m và 3,2m"})["id"]
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
            except Exception as error:      # no Chromium that Playwright can start here
                print(f"SKIP: cannot launch Chromium ({str(error).splitlines()[0][:120]})")
                return 0
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(base + "/web/")
            page.wait_for_function("document.querySelectorAll('#moduleList li').length > 0", timeout=20000)
            check("opens a design: module list filled", page.locator("#moduleList li").count() > 0)
            check("design select has the design", page.locator("#designSelect option").count() >= 1)
            check("view select filled", page.locator("#viewSelect option").count() >= 1)
            check("rev info shown", page.inner_text("#revInfo").startswith("rev "))
            check("canvas present", page.locator("#viewport canvas").count() == 1)
            check("issues list rendered", page.locator("#issues li").count() >= 1)
            check("AI export link points at the short JSON with lighting", "lighting=" in (page.get_attribute("#aiJson", "href") or ""))

            first = page.locator("#moduleList li").first
            first_id = first.locator("b").inner_text()
            first.click()
            check("select a cabinet: form opens with its id", page.is_visible("#moduleForm") and first_id in page.inner_text("#formTitle"))
            check("selected row is highlighted", page.locator("#moduleList li.sel").count() == 1)

            rev0 = int(page.inner_text("#revInfo").split()[-1])
            width = page.locator("#formFields input[name=width]")
            new_width = str(int(float(width.input_value())) + 100)
            width.fill(new_width)
            page.click("#moduleForm button[type=submit]")
            page.wait_for_function(f"document.getElementById('revInfo').textContent.endsWith(' {rev0 + 1}')", timeout=20000)
            check("edit a cabinet: new revision", True)
            check("edit keeps the cabinet selected", page.locator("#moduleList li.sel").count() == 1)
            check("edit: the form shows the new width", page.locator("#formFields input[name=width]").input_value() == new_width)

            page.click("#undo")
            page.wait_for_function(f"document.getElementById('revInfo').textContent.endsWith(' {rev0 + 2}')", timeout=20000)
            check("undo: revision advances and the old width is back", page.locator("#formFields input[name=width]").input_value() != new_width)

            # add a cabinet after the selected one: the page asks for the width with prompt()
            page.once("dialog", lambda d: d.accept("500"))
            before = page.locator("#moduleList li").count()
            page.click("#addAfter")
            page.wait_for_function(f"document.querySelectorAll('#moduleList li').length === {before + 1}", timeout=20000)
            check("add a cabinet after the selected one", True)
            page.click("#removeModule")
            page.wait_for_function(f"document.querySelectorAll('#moduleList li').length === {before}", timeout=20000)
            check("remove the selected cabinet", True)

            # context menu: right click on the 3D canvas somewhere a cabinet is
            box = page.locator("#viewport canvas").bounding_box()
            opened = False
            for fy in (0.55, 0.65, 0.45, 0.75, 0.35):
                for fx in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8):
                    page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy, button="right")
                    page.wait_for_timeout(120)
                    if page.is_visible("#ctxMenu"):
                        opened = True
                        break
                if opened:
                    break
            check("right click on the 3D view opens the context menu", opened)
            if opened:
                check("context menu has the command box", page.locator("#ctxMenu .ctx-cmd input[type=text]").count() == 1)
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                check("Escape closes the context menu", not page.is_visible("#ctxMenu"))

            # free command box (left panel) -> preview only
            page.fill("#cmdText", "xóa TD1")
            page.click("#cmdGo")
            page.wait_for_function("document.querySelector('#assistResult').textContent.trim().length > 0", timeout=20000)
            check("free command shows a preview with a confirm button", page.locator("#assistResult button.primary, #assistResult button.danger").count() >= 1)

            # molding panel and validation standard
            check("molding profile select filled", page.locator("#pCrownProf option").count() > 0)
            check("standards select filled", page.locator("#qgSelect option").count() > 1)

            # render + AI export
            page.click("#renderOne")
            page.wait_for_function("document.querySelectorAll('#renders figure').length > 0", timeout=90000)
            check("render one view shows images", page.locator("#renders figure img").count() >= 1)
            page.click("#aiView")
            page.wait_for_function("document.getElementById('jsonView').open", timeout=20000)
            check("open the final AI JSON viewer", True)
            page.click("#jvClose")

            # image tab
            page.click("#tabImg")
            page.wait_for_function("document.querySelectorAll('#jStyleFrom option').length >= 3", timeout=20000)
            check("image tab: styleFrom select filled", True)
            page.click("#tab3d")

            check("no page errors or console errors", not errors, "; ".join(errors[:3]))
            browser.close()
        return 1 if failures else 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    sys.exit(main())
