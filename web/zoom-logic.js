// Zoom and pan of a picture inside a fixed frame (the "Sửa ảnh theo lớp" picture): pure arithmetic, no page.
// A view is { scale, x, y }: the picture drawn `scale` times its fitted size, its top-left corner at (x, y) px in the frame
// (CSS: transform: translate(x, y) scale(scale), origin top-left). The picture always covers the frame: never smaller, never pulled off.

export const ZOOM_MIN = 1;
export const ZOOM_MAX = 8;
export const ZOOM_STEP = 1.25;        // one button press or one wheel notch
export const DRAG_PX = 4;             // a press that moves less than this is a click (pick a part), not a drag

export const fitted = () => ({ scale: 1, x: 0, y: 0 });

/** The view kept inside the frame (w x h px): scale within [ZOOM_MIN, ZOOM_MAX], the picture covering the frame. */
export function clampView(v, w, h) {
  const scale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.scale));
  const x = Math.min(0, Math.max(w - w * scale, v.x));
  const y = Math.min(0, Math.max(h - h * scale, v.y));
  return { scale, x, y };
}

/** The view zoomed by `factor` about the frame point (px, py), which stays under the pointer. */
export function zoomAt(v, factor, px, py, w, h) {
  const scale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.scale * factor));
  const k = scale / v.scale;
  return clampView({ scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k }, w, h);
}

/** The view moved by (dx, dy) px. */
export const panBy = (v, dx, dy, w, h) => clampView({ scale: v.scale, x: v.x + dx, y: v.y + dy }, w, h);

/** The zoom factor of a wheel event's vertical delta (up: in, down: out). */
export const wheelFactor = (deltaY) => (deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);

/** The CSS transform of a view. */
export const transformOf = (v) => `translate(${v.x}px, ${v.y}px) scale(${v.scale})`;
