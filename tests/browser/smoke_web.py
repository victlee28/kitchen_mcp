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
        design2 = post(base, "/api/designs", {"prompt": "Bếp chữ I dài 3m"})["id"]
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
            check("edit refreshes the revision label in the design list", page.eval_on_selector("#designSelect", "s => s.options[s.selectedIndex].textContent").endswith(f"rev {rev0 + 1}"))
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

            # switching design twice in a row: the page ends on the LAST one (a slow earlier load must not win)
            page.select_option("#designSelect", design)
            page.select_option("#designSelect", design2)
            page.wait_for_function(f"document.getElementById('openRender').href.includes('{design2}')", timeout=20000)
            page.wait_for_timeout(1500)
            check("quick design switch ends on the last design", design2 in (page.get_attribute("#openRender", "href") or "") and page.input_value("#designSelect") == design2)
            page.select_option("#designSelect", design)
            page.wait_for_function(f"document.getElementById('openRender').href.includes('{design}')", timeout=20000)
            page.wait_for_function("document.querySelectorAll('#moduleList li').length > 0", timeout=20000)
            page.locator("#moduleList li").first.click()

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
                check("context menu inputs carry their aria-label attribute", bool(page.get_attribute("#ctxMenu .ctx-cmd input[type=text]", "aria-label")))
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

            # create from a description: the table "what was understood" appears and a new design is opened
            n_designs = page.locator("#designSelect option").count()
            page.fill("#prompt", "Bếp chữ I dài 2,4m, mặt đá trắng")
            page.click("#fromPrompt")
            page.wait_for_function(f"document.querySelectorAll('#designSelect option').length === {n_designs + 1}", timeout=30000)
            page.wait_for_function("!document.getElementById('promptResult').hidden", timeout=30000)
            page.wait_for_function("document.querySelectorAll('#moduleList li').length > 0", timeout=20000)
            check("create from a description: new design opened, selection cleared", page.locator("#moduleList li.sel").count() == 0 and not page.is_visible("#moduleForm"))
            check("create from a description: interpretation table shown", page.locator("#promptResult table tr").count() >= 2 and page.is_visible("#promptResult"))

            # create from the template form
            n_designs += 1
            page.click("summary:has-text('Tạo từ mẫu')")
            page.select_option("#mShape", "L")
            page.click("#fromTemplate")
            page.wait_for_function(f"document.querySelectorAll('#designSelect option').length === {n_designs + 1}", timeout=30000)
            page.wait_for_function("document.querySelectorAll('#moduleList li').length > 0", timeout=20000)
            check("create from the template: new L design opened", "L" in page.eval_on_selector("#designSelect", "s => s.options[s.selectedIndex].textContent"))

            # floor-plan import (+ choose a room when the plan offers several) and place the kitchen on a wall
            n_designs += 1
            page.set_input_files("#floorplanFile", str(ROOT / "input-floorplan" / "floorplan.json"))
            page.wait_for_function("document.getElementById('fpImport') && (!document.getElementById('fpImport').hidden || document.querySelectorAll('#fpInfo li').length > 0)", timeout=30000)
            if page.is_visible("#fpImport"):
                check("floor plan offers several rooms: room picker filled", page.locator("#fpRoom option").count() >= 2)
                page.click("#fpImport")
            page.wait_for_function(f"document.querySelectorAll('#designSelect option').length === {n_designs + 1}", timeout=30000)
            page.wait_for_function("document.querySelectorAll('#fpInfo li').length > 0", timeout=20000)
            check("floor plan import: new design opened and info listed", page.locator("#fpInfo li").count() >= 1)
            rev_fp = int(page.inner_text("#revInfo").split()[-1])
            errors_before = len(errors)
            page.click("#fpBind")
            # an imported room has no cabinets yet, so the server refuses and the page reports it in the status line
            page.wait_for_function("document.getElementById('status').textContent.includes('no cabinets')", timeout=30000)
            check("place the kitchen on a wall: the server's refusal is reported in the status line", True)
            del errors[errors_before:]      # the 400 and its ApiError log are the expected refusal, not a page fault
            check("place the kitchen on a wall: design still open", int(page.inner_text("#revInfo").split()[-1]) == rev_fp)

            # packaged export for the AI image generator (renders what is missing, then offers a zip)
            with page.expect_download(timeout=180000) as dl:
                page.click("#aiZip")
            check("AI package: a .zip is downloaded", dl.value.suggested_filename.endswith(".zip"))
            check("AI package: info line says images are included", "kèm ảnh" in page.inner_text("#aiInfo"))

            check("no page errors or console errors", not errors, "; ".join(errors[:3]))

            # the stand-alone render page shares dom.js / api-client.js
            page2 = browser.new_page(viewport={"width": 1200, "height": 800})
            errors2: list[str] = []
            page2.on("pageerror", lambda e: errors2.append(str(e)))
            page2.on("console", lambda m: errors2.append(m.text) if m.type == "error" else None)
            page2.goto(base + "/web/render.html?design=" + design)
            page2.wait_for_timeout(2500)
            check("render page loads without errors", not errors2, "; ".join(errors2[:3]))
            check("render page lists the designs", page2.locator("select option").count() >= 1)
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
