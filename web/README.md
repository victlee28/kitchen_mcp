# Web editor

Chạy `run.bat` (hoặc `python web_server.py`) rồi mở http://localhost:8080/web/.
Cần Internet để tải three.js 0.161.0 từ CDN. Xem README.md ở thư mục gốc.

## Free command, photo/drawing recognition, styleFrom
- `assist.js` (+ pure `assist-logic.js`): the "Lệnh tự do & nhận diện ảnh" panel. `/interpret` and `/recognize` only preview; **Áp dụng** sends `/ops` with `expect=opHash`.
- Recognition uses `kitchen/recognizers.py` `GeminiRecognizer` (Gemini vision, model `GEMINI_VISION_MODEL`, default `gemini-2.5-flash`); wired automatically when `GEMINI_API_KEY`/`GEMINI_ENV_FILE` is set, otherwise the answer is `unavailable`.
- Image tab: the "Phong cách theo góc khác" select sends `styleFrom` (default / `auto` / `none` / a view name).
