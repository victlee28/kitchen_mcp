// Pure logic of the module context menu (no DOM, no three.js), so it can be tested with `node --test tests/js`.
export const CLICK_MAX_MOVE = 4;     // px between press and context-menu event: more is a camera drag, not a click
export const CLICK_MAX_MS = 600;
export const DOOR_STYLES = [['flat', 'Cánh phẳng'], ['frame', 'Cánh khung (shaker)'], ['glass', 'Cánh kính']];
export const MATERIAL_PRESETS = ['Trắng mờ', 'Laminate vân gỗ sồi sáng', 'Acrylic xám đậm', 'Laminate xanh rêu mờ', 'Melamine trắng'];
export const MIN_ADD_WIDTH = 200, MAX_ADD_WIDTH = 1200;
export const HANDLE_VARIANTS = [['bar', 'Tay thanh'], ['knob', 'Núm'], ['concealed', 'Tay âm'], ['none', 'Không tay (nhấn mở)']];
export const MAX_OVERHANG = 100;

/** Was the press-and-release a click (pointer barely moved, short)? down/up: {x, y, t}. */
export function isClick(down, up) {
  if (!down || !up) return false;
  return Math.hypot(up.x - down.x, up.y - down.y) <= CLICK_MAX_MOVE && up.t - down.t <= CLICK_MAX_MS;
}

/** First hit that is a cabinet module of the design or a visible floorplan element. hits: raycaster results, nearest first. */
export function pickTarget(hits, moduleIds) {
  for (const h of hits) {
    const u = h.object?.userData || {};
    if (u.structureId && h.object.visible !== false) return { kind: 'structure', id: u.structureId, ...(h.point ? { point: { x: h.point.x, z: h.point.z } } : {}) };   // point: where the ray hit, scene units
    const part = u.part;   // schema 1.4 partRef: a door, drawer front, handle or countertop run
    if (part?.kind === 'countertop') return { kind: 'part', part: 'countertop', id: part.wall || 'back' };
    if (part && ['door', 'drawer', 'handle'].includes(part.kind) && moduleIds.includes(part.module)) return { kind: 'part', part: part.kind, id: part.module };
    if (u.module && moduleIds.includes(u.module)) return { kind: 'module', id: u.module };
  }
  return null;
}

/** Actions the menu offers for a target. */
export function actionsFor(target, spec) {
  if (!target) return [];
  if (target.kind === 'part') {
    if (target.part === 'countertop') return [{ id: 'countertopMaterial', label: 'Đổi vật liệu mặt bàn' }, { id: 'countertopOverhang', label: 'Đổi độ nhô mặt bàn' }];
    if (target.part === 'handle') return [{ id: 'handleVariant', label: 'Đổi kiểu tay nắm' }, { id: 'handleMaterial', label: 'Đổi vật liệu tay nắm' }];
    return [...(target.part === 'door' ? [{ id: 'doorStyle', label: 'Đổi kiểu cánh' }] : []), { id: 'material', label: 'Đổi vật liệu mặt trước' },
      { id: 'handleVariant', label: 'Đổi kiểu tay nắm' }, { id: 'image', label: 'Sửa ảnh của module này' }];
  }
  if (target.kind === 'structure') return [...(target.point ? [{ id: 'run-i', label: 'Tạo dãy tủ chữ I dọc cạnh này' }] : []), { id: 'struct-hide', label: 'Ẩn thành phần này' }, { id: 'struct-isolate', label: 'Chỉ giữ thành phần này' }, { id: 'struct-all', label: 'Hiện tất cả' }];
  const m = spec?.module?.find((x) => x.id === target.id);
  const out = [{ id: 'material', label: 'Đổi vật liệu mặt trước' }, { id: 'doorStyle', label: 'Đổi kiểu cánh' }];
  if (m && m.wall !== 'corner') out.push({ id: 'add', label: 'Thêm tủ bên cạnh' });
  out.push({ id: 'remove', label: 'Xóa module' }, { id: 'image', label: 'Sửa ảnh của module này' });
  return out;
}

/** Operation for a form. Throws Error with a message the user can read. */
export function buildOp(action, id, form, spec) {
  if (action === 'countertopMaterial') {
    const material = String(form.material || '').trim();
    if (!material) throw new Error('Nhập tên vật liệu mặt bàn');
    if (material === spec?.common?.material?.countertop) throw new Error('Mặt bàn đã dùng vật liệu này');
    return { op: 'common', changes: { material: { ...(spec?.common?.material || {}), countertop: material } } };
  }
  if (action === 'countertopOverhang') {
    const mm = Number(form.overhang);
    if (!Number.isFinite(mm) || mm < 0 || mm > MAX_OVERHANG) throw new Error(`Độ nhô 0–${MAX_OVERHANG} mm`);
    if (mm === spec?.common?.countertopOverhang) throw new Error('Mặt bàn đã nhô đúng mức này');
    return { op: 'common', changes: { countertopOverhang: mm } };
  }
  const m = spec?.module?.find((x) => x.id === id);
  if (!m) throw new Error(`Không còn module ${id} trong thiết kế`);
  if (action === 'material') {
    const material = String(form.material || '').trim();
    if (!material) throw new Error('Nhập tên vật liệu');
    if (material === m.material) throw new Error('Module đã dùng vật liệu này');
    return { op: 'update', id, changes: { material }, closeGap: false };
  }
  if (action === 'doorStyle') {
    if (!DOOR_STYLES.some(([v]) => v === form.style)) throw new Error('Chọn kiểu cánh');
    return { op: 'update', id, changes: { doorStyle: form.style }, closeGap: false };
  }
  if (action === 'handleVariant') {
    if (!HANDLE_VARIANTS.some(([v]) => v === form.variant)) throw new Error('Chọn kiểu tay nắm');
    return { op: 'update', id, changes: { handle: { ...(m.handle || {}), variant: form.variant } }, closeGap: false };   // keep the module's other handle overrides
  }
  if (action === 'handleMaterial') {
    const material = String(form.material || '').trim();
    if (!material) throw new Error('Nhập vật liệu tay nắm');
    return { op: 'update', id, changes: { handle: { ...(m.handle || {}), material } }, closeGap: false };
  }
  if (action === 'remove') return { op: 'remove', id, closeGap: !!form.closeGap };
  if (action === 'add') {
    const width = Number(form.width);
    if (!Number.isFinite(width) || width < MIN_ADD_WIDTH || width > MAX_ADD_WIDTH) throw new Error(`Chiều rộng ${MIN_ADD_WIDTH}–${MAX_ADD_WIDTH} mm`);
    if (m.wall === 'corner') throw new Error('Không thêm cạnh module góc ở đây');
    if (form.side === 'after') return { op: 'add', module: { width }, afterModule: id, closeGap: !!form.closeGap };
    return { op: 'add', module: { width, type: m.type, wall: m.wall, y: m.y, height: m.height, depth: m.depth, fromCorner: m.fromCorner }, closeGap: !!form.closeGap };
  }
  throw new Error(`Hành động không hỗ trợ: ${action}`);
}

/** Layer an action targets in the image editor: whole fronts for a material/style change, the whole module otherwise. */
export function layerFor(action, id) {
  return action === 'material' || action === 'doorStyle' ? `frontSections:${id}` : `module:${id}`;
}

const show = (v) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));

/** Preview lines for the UI: [{kind: 'ok'|'info'|'warn'|'bad', text}]. */
export function describeProposal(p) {
  if (!p.applicable) return [{ kind: 'bad', text: `Không áp dụng được: ${p.error?.message || 'lỗi không rõ'}` }];
  const out = [];
  if (p.unchanged) return [{ kind: 'warn', text: 'Thao tác này không thay đổi gì.' }];
  const mod = p.diff.modules;
  for (const id of mod.added) out.push({ kind: 'info', text: `Thêm ${id}` });
  for (const id of mod.removed) out.push({ kind: 'info', text: `Xóa ${id}` });
  for (const [id, ch] of Object.entries(mod.changed)) out.push({ kind: 'info', text: `${id}: ` + ch.map((c) => `${c.field} ${show(c.old)} → ${show(c.new)}`).join('; ') });
  for (const e of p.diff.other) out.push({ kind: 'info', text: `${e.path}: ${show(e.old)} → ${show(e.new)}` });
  if (p.diff.truncated) out.push({ kind: 'warn', text: 'Danh sách thay đổi bị cắt bớt.' });
  if (p.outsideScope?.length) out.push({ kind: 'warn', text: `Cũng làm đổi module khác: ${p.outsideScope.join(', ')}` });
  for (const i of p.validation.introduced) out.push({ kind: i.severity === 'error' ? 'bad' : 'warn', text: `Mới: ${i.content}` });
  for (const i of p.validation.resolved) out.push({ kind: 'ok', text: `Hết: ${i.content}` });
  return out;
}

/** Place a w x h popup at (x, y) inside a vw x vh viewport with a margin. */
export function menuPosition(x, y, w, h, vw, vh, margin = 8) {
  return { left: Math.max(margin, Math.min(x, vw - w - margin)), top: Math.max(margin, Math.min(y, vh - h - margin)) };
}
