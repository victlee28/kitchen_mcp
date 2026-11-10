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

- **3D view:** Shift+click a door or a drawer front (both are picked together: doors and drawer fronts), a handle or a cabinet body: every
  module of the same system and tier (base, upper with loft, tall, corner) showing that role is selected, and only those parts light up. Right click one of them: change the front material, the
  door style or the handles of the whole group (one previewed change), or "Sửa ảnh của vùng chọn này" to open the image tab on the same
  group. Plain click or Esc drops the group.
- **Image tab:** Shift+click picks `sys:<system>:tier:<tier>:<role>` when the design has several systems, `tier:<tier>:<role>` otherwise; a door
  or a drawer front picks the `front` group (doors + drawer fronts; `door` when the tier has no drawers).
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

## Replacing furniture, backs to the wall (plan `claude/ke-hoach-thay-vat-bang-he-tu.md`)
- Right click a **furniture** element of the floorplan: "Thay vật này bằng dãy tủ" (the old "Tạo dãy tủ chữ I" entry), or a sentence in the
  command box ("thay vật này bằng tủ bếp có chậu rửa…"). The object is **replaced**: one run per edge lying against a wall (an L or an
  object in a corner gives two runs of one system meeting in the corner), the backs on that edge, the doors into the object, base and tall
  cabinets as deep as the object (wall cabinets too when it is 350 mm deep or less). The object is listed in `floorplan.replaced` and no
  longer drawn, rendered or used by the cameras; going back a revision brings it back. Cabinets made against it before are removed.
- An object with **no edge against a wall** opens a popup listing its edges (hover draws the edge in the 3D view): the one picked is the back.
- Walls and columns keep "standing beside": the backs lean on them.
- **Drawn runs:** a line along a wall turns the backs to the wall whichever side was asked; away from walls the side asked is kept.
- A recognised kitchen anchored on furniture also replaces it.

## Appliance models (plan `claude/ke-hoach-thay-mau-thiet-bi.md`)
- Catalogue: `kitchen/appliance_catalog.py` (a DRAFT list: hobs, sinks, taps, hoods, fridges, ovens; size, cut-out / niche, mount, energy,
  `box` for the 3D stand-in, `visual` + `prompt` for the image AI, `asset3d` for a real GLB model). Logic: `kitchen/appliance_models.py`.
- **3D:** appliances are clickable (target `appliance`). Right click one: its title and the command box only (no menu entries of their own):
  "đổi sang bếp gas", "thay chậu đôi", or Enter on an empty box ⇒ a popup lists the models of that type with ok / cần kiểm tra / không vừa
  / chưa hỗ trợ; a model that does not fit offers "Nới tủ đỡ" (widen the cabinet, the next ones move along) or "Giữ tủ". After Áp dụng the
  image tab opens on that appliance with the model's description filled in. Without a real model the box draws its model (glass top with
  zones / burners, sink bowls, fridge doors); with `asset3d` the GLB is loaded instead (GLTFLoader must be in `vendor/three/examples/jsm/loaders/`).
- **Image tab:** selecting an appliance layer (`TBx-…`) shows "Đổi mẫu": preview, apply, and the job form filled with the model.
- **AI requests:** every appliance is described in the JSON sent to the image AI (`appliances` in `ai-request.json`, per view the visible
  ones with their place in the picture, a sentence in each view's prompt / Gemini text, and in layer jobs whose region covers one): for a
  stand-in box everything about the model; for a real model what a picture cannot show.
- Template `{"kind": "replace-appliance", "id", "model"?, "prompt"?, "resizeHost"?}`; op `update-appliance`; rules `APPLIANCE-MODEL-FIT`,
  `HOOD-WIDTH` (only for appliances that carry a model, so old designs show nothing new).

## TV wall units (hệ tủ tivi, 10/11/2026)
- Right-click a piece of furniture (e.g. "Vách TV") and type "tạo hệ tủ tivi" (also "kệ tivi", "tủ TV") in the command box, or give that
  sentence for a drawn line: the object is replaced by a TV unit along its wall edge — a low console with drawers (450 mm) between two tall
  columns at the ends (lines from 2.4 m), the open TV niche with a wall-mounted TV (65" / 55" / 43" by the niche width) and a floating shelf
  above it. Base and tall cabinets take the object's depth, as for kitchen cabinets.
- The run carries `purpose: "tv"` (`kitchen/tv_system.py`): no worktop or wall tile, kitchen rules skip it, the TV is an appliance of type
  `tv` (catalog `tv-65/55/43`, exported as `Television`, `wall_mounted`), and the image prompt describes a TV wall unit (a living room when
  the design holds nothing else). Swapping the TV size goes through the appliance popup ("đổi sang tivi 55").

## Tests of the web app
- `tests/js/*.test.mjs` (run by `test_web_logic`): pure logic (`menu-logic`, `assist-logic`, `design-logic`) and `web-architecture` (no module imports `app.js`, no import cycles, `window.kitchen` only assigned by `app.js`).
- `tests/browser/smoke_web.py`: real-Chromium smoke test of the main flows (open, select, edit, undo, add/remove, right-click menu, free command, render, AI JSON, image tab). Needs `pip install playwright` and a launchable Chromium; prints SKIP and exits 0 without Playwright. Run it before and after every step of splitting `app.js` (plan: `claude/ke-hoach-tach-app-js.md` in the project docs).
