# Web editor

Chạy `run.bat` (hoặc `python web_server.py`) rồi mở http://localhost:8080/web/.
Cần Internet để tải three.js 0.161.0 từ CDN. Xem README.md ở thư mục gốc.

## Free command, photo/drawing recognition, styleFrom
- `assist.js` (+ pure `assist-logic.js`): the "Lệnh tự do & nhận diện ảnh" panel. `/interpret` and `/recognize` only preview; **Áp dụng** sends `/ops` with `expect=opHash`.
- Recognition uses `kitchen/recognizers.py` `GeminiRecognizer` (Gemini vision, model `GEMINI_VISION_MODEL`, default `gemini-2.5-flash`); wired automatically when `GEMINI_API_KEY`/`GEMINI_ENV_FILE` is set, otherwise the answer is `unavailable`.
- Image tab: the "Phong cách theo góc khác" select sends `styleFrom` (default / `auto` / `none` / a view name).

## Cabinet systems and Shift-selection

A cabinet system is the set of runs that belong together: the runs made against one floorplan element carry its id (`Run.system`, e.g.
`furniture_003`); other runs are grouped with the runs they touch (`auto-<run>`); see `kitchen/runs.py` (`systems`). `GET /api/designs/<id>`
returns `systems: {module: {system, tier, storey}}`; the page never works them out itself.

- **3D view:** Shift+click a door, a drawer front, a handle or a cabinet body: every module of the same system and tier (base, upper with
  loft, tall, corner) showing that role is selected, and only those parts light up. Right click one of them: change the front material, the
  door style or the handles of the whole group (one previewed change), or "Sửa ảnh của vùng chọn này" to open the image tab on the same
  group. Plain click or Esc drops the group.
- **Image tab:** Shift+click picks `sys:<system>:tier:<tier>:<role>` when the design has several systems, `tier:<tier>:<role>` otherwise.
- Changing a material for part of the modules that share one (one system of several) gives those modules a material of their own, so the
  other systems keep theirs.
- **Replace a whole system:** type a sentence that names the system and asks for a change in the command box of a cabinet's right-click
  menu: "thay cả hệ tủ …", "đổi hệ tủ …", "làm lại hệ tủ …", "sửa lại, thêm tủ nóc cho hệ, cho tủ lạnh sang phải", "bỏ tủ trên của hệ này"
  (`assist-logic.systemIntent`; no menu entry of its own). The system phrase and the lead-in verbs are taken out; the rest is the description.
  A loft row / wall cabinets the sentence asks for are laid even where the system had none; "bỏ / không tủ trên / tủ nóc" leaves them out;
  "tủ lạnh sang phải / bên trái" puts the fridge at that end (seen from the front). Sink, hob, hood and fridge go in the main run only. With a description after it ("thay cả hệ tủ bằng: có chậu rửa, bếp, cánh
  khung"), the system's runs keep their place, angle and length and are laid out again with what it describes (the longest run gets all of
  it, the others the same kind without a fridge; no wall cabinets where the system had none; fronts it does not name come from the old
  cabinets). With nothing after it, "phong cách khác", or a preset's name ("đổi cả hệ sang Gỗ sồi ấm"), the cabinets stay and take a style
  preset (front, door style, handle; `kitchen/system_replace.STYLES`). Server: template `{"kind": "replace-system", "system", "prompt"?, "style"?}`.

## Tests of the web app
- `tests/js/*.test.mjs` (run by `test_web_logic`): pure logic (`menu-logic`, `assist-logic`, `design-logic`) and `web-architecture` (no module imports `app.js`, no import cycles, `window.kitchen` only assigned by `app.js`).
- `tests/browser/smoke_web.py`: real-Chromium smoke test of the main flows (open, select, edit, undo, add/remove, right-click menu, free command, render, AI JSON, image tab). Needs `pip install playwright` and a launchable Chromium; prints SKIP and exits 0 without Playwright. Run it before and after every step of splitting `app.js` (plan: `claude/ke-hoach-tach-app-js.md` in the project docs).
