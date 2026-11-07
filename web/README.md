# Web editor

Chạy `run.bat` (hoặc `python web_server.py`) rồi mở http://localhost:8080/web/.
Cần Internet để tải three.js 0.161.0 từ CDN. Xem README.md ở thư mục gốc.

## Free command, photo/drawing recognition, styleFrom
- `assist.js` (+ pure `assist-logic.js`): the "Lệnh tự do & nhận diện ảnh" panel. `/interpret` and `/recognize` only preview; **Áp dụng** sends `/ops` with `expect=opHash`.
- Recognition uses `kitchen/recognizers.py` `GeminiRecognizer` (Gemini vision, model `GEMINI_VISION_MODEL`, default `gemini-2.5-flash`); wired automatically when `GEMINI_API_KEY`/`GEMINI_ENV_FILE` is set, otherwise the answer is `unavailable`.
- Image tab: the "Phong cách theo góc khác" select sends `styleFrom` (default / `auto` / `none` / a view name).

## Tests of the web app
- `tests/js/*.test.mjs` (run by `test_web_logic`): pure logic (`menu-logic`, `assist-logic`, `design-logic`) and `web-architecture` (no module imports `app.js`, no import cycles, `window.kitchen` only assigned by `app.js`).
- `tests/browser/smoke_web.py`: real-Chromium smoke test of the main flows (open, select, edit, undo, add/remove, right-click menu, free command, render, AI JSON, image tab). Needs `pip install playwright` and a launchable Chromium; prints SKIP and exits 0 without Playwright. Run it before and after every step of splitting `app.js` (plan: `claude/ke-hoach-tach-app-js.md` in the project docs).
