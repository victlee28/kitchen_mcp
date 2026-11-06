// Context menu on a cabinet module in the 3D view: pick an action, fill a small form, preview what it would change, confirm.
// The server decides what a change means (POST .../propose previews, POST .../ops saves); nothing here edits data directly.
import { actionsFor, buildOp, describeProposal, layerFor, menuPosition, DOOR_STYLES, HANDLE_VARIANTS, MATERIAL_PRESETS } from './menu-logic.js';

const el = (tag, props = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) { if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else if (v !== undefined) n[k] = v; }
  for (const c of kids) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
};

async function call(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  return { status: r.status, ok: r.ok, data };
}

/**
 * ctx: { box, getState() -> {id, rev, spec}, afterChange(result), reload(), imageEdit({layer, material}), structure: {hide, isolate, showAll}, setStatus }
 */
export function createModuleMenu(ctx) {
  const box = ctx.box;
  let target = null; let step = null; let busy = false;
  box.setAttribute('role', 'dialog'); box.hidden = true;

  const close = () => { box.hidden = true; box.replaceChildren(); target = null; step = null; busy = false; };
  const header = (text) => el('div', { class: 'ctx-head' }, text, el('button', { type: 'button', class: 'ctx-x', title: 'Đóng (Esc)', onclick: close }, '×'));
  const err = (text) => el('p', { class: 'ctx-msg bad', role: 'alert' }, text);

  function place(x, y) {
    box.hidden = false;
    const { left, top } = menuPosition(x, y, box.offsetWidth || 300, box.offsetHeight || 220, window.innerWidth, window.innerHeight);
    box.style.left = `${left}px`; box.style.top = `${top}px`;
  }

  function list() {
    const { spec } = ctx.getState();
    const partName = { door: 'Cánh', drawer: 'Mặt ngăn kéo', handle: 'Tay nắm', countertop: 'Mặt bàn' }[target.part];
    const title = target.kind === 'part' ? (target.part === 'countertop' ? 'Mặt bàn' : `${partName} · ${target.id}`)
      : target.kind === 'module' ? `Module ${target.id}` : `Thành phần mặt bằng ${target.id.replace(/^STRUCT-/, '')}`;
    box.replaceChildren(header(title), el('ul', { class: 'ctx-list' }, ...actionsFor(target, spec).map((a) =>
      el('li', {}, el('button', { type: 'button', onclick: () => choose(a.id) }, a.label)))));
  }

  function choose(action) {
    if (action === 'struct-hide') { ctx.structure.hide(); return close(); }
    if (action === 'struct-isolate') { ctx.structure.isolate(); return close(); }
    if (action === 'struct-all') { ctx.structure.showAll(); return close(); }
    if (action === 'image') { const id = target.id; close(); return ctx.imageEdit({ layer: layerFor('image', id), module: id }); }
    form(action);
  }

  function form(action, message) {
    const { spec } = ctx.getState();
    const m = spec.module.find((x) => x.id === target.id);
    const f = {}; const fields = [];
    if (action === 'countertopMaterial' || action === 'handleMaterial') {
      f.material = el('input', { type: 'text', value: action === 'handleMaterial' ? (m?.handle?.material || spec.common?.handle?.material || '') : (spec.common?.material?.countertop || ''),
        placeholder: action === 'handleMaterial' ? 'vd Nhôm đen mờ' : 'vd Đá granite tối', autocomplete: 'off' });
      fields.push(el('label', {}, action === 'handleMaterial' ? 'Vật liệu tay nắm' : 'Vật liệu mặt bàn', f.material));
    } else if (action === 'countertopOverhang') {
      f.overhang = el('input', { type: 'number', min: 0, max: 100, step: 5, value: spec.common?.countertopOverhang ?? 20 });
      fields.push(el('label', {}, 'Độ nhô phía trước (mm)', f.overhang));
    } else if (action === 'handleVariant') {
      const current = m?.handle?.variant || spec.common?.handleByStorey?.[m?.storey]?.variant || spec.common?.handle?.variant;
      f.variant = el('select', {}, ...HANDLE_VARIANTS.map(([v, t]) => el('option', { value: v, selected: v === current }, t)));
      fields.push(el('label', {}, 'Kiểu tay nắm', f.variant));
    } else if (action === 'material') {
      const used = [...new Set([...Object.values(spec.common?.material || {}), ...spec.module.map((x) => x.material)].filter((v) => typeof v === 'string' && v))];
      const dl = el('datalist', { id: 'ctxMats' }, ...[...used, ...MATERIAL_PRESETS.filter((p) => !used.includes(p))].map((v) => el('option', { value: v })));
      f.material = el('input', { type: 'text', value: m?.material || '', placeholder: 'vd Laminate xanh rêu mờ', autocomplete: 'off' }); f.material.setAttribute('list', 'ctxMats');
      fields.push(el('label', {}, 'Vật liệu mặt trước', f.material, dl));
    } else if (action === 'doorStyle') {
      f.style = el('select', {}, ...DOOR_STYLES.map(([v, t]) => el('option', { value: v, selected: v === m?.doorStyle }, t)));
      fields.push(el('label', {}, 'Kiểu cánh', f.style));
    } else if (action === 'remove') {
      f.closeGap = el('input', { type: 'checkbox', checked: true });
      const owned = spec.appliances.filter((a) => a.module === target.id).map((a) => a.name || a.id);
      fields.push(el('label', { class: 'inline' }, f.closeGap, ' Dồn các tủ còn lại lấp chỗ trống'));
      if (owned.length) fields.push(el('p', { class: 'ctx-msg warn' }, `Thiết bị gắn theo module này cũng bị xóa: ${owned.join(', ')}`));
    } else if (action === 'add') {
      f.side = el('select', {}, el('option', { value: 'after' }, 'Phía sau (xa góc hơn)'), el('option', { value: 'before' }, 'Phía trước (gần góc hơn)'));
      f.width = el('input', { type: 'number', min: 200, max: 1200, step: 10, value: m?.width || 600 });
      f.closeGap = el('input', { type: 'checkbox', checked: true });
      fields.push(el('label', {}, 'Vị trí', f.side), el('label', {}, 'Chiều rộng (mm)', f.width), el('label', { class: 'inline' }, f.closeGap, ' Đẩy các tủ phía sau ra'));
    }
    const out = el('div', { class: 'ctx-msg' });
    if (message) out.append(err(message));
    const read = () => Object.fromEntries(Object.entries(f).map(([k, n]) => [k, n.type === 'checkbox' ? n.checked : n.value]));
    const go = el('button', { type: 'button', class: 'primary', onclick: () => preview(action, read) }, 'Xem trước');
    const extra = [];
    if (action === 'material') {   // same material, but as a picture first: opens the image tab with the job form filled (quick mode, preview on)
      extra.push(el('button', { type: 'button', class: 'ghost', title: 'Mở tab sửa ảnh với vật liệu này; chưa đổi thiết kế',
        onclick: () => { const material = read().material.trim(); if (!material) return form(action, 'Nhập tên vật liệu'); const id = target.id; close(); ctx.imageEdit({ layer: layerFor('material', id), module: id, material, mode: 'quick', preview: true }); } }, 'Tạo ảnh với vật liệu này'));
    }
    box.replaceChildren(header(`${target.part === 'countertop' ? 'Mặt bàn' : target.id}: ${actionsFor(target, spec).find((a) => a.id === action)?.label}`), ...fields, out,
      el('div', { class: 'row' }, go, ...extra, el('button', { type: 'button', class: 'ghost', onclick: list }, 'Quay lại')));
    (f.material || f.style || f.width || go).focus?.();
    box.onkeydown = (e) => { if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); go.click(); } };
  }

  async function preview(action, read) {
    if (busy) return; const { id, rev, spec } = ctx.getState();
    let op;
    try { op = buildOp(action, target.id, read(), spec); } catch (e) { return form(action, e.message); }
    busy = true; ctx.setStatus('Xem trước thay đổi…');
    try {
      const { status, data } = await call(`/api/designs/${id}/propose`, { op, baseRev: rev, ...(target.part === 'countertop' ? {} : { scope: [target.id] }) });
      busy = false;
      if (status === 409) return stale(action);
      if (!data || data.error) return form(action, data?.error || `Lỗi ${status}`);
      showPreview(action, data, read);
    } catch (e) { busy = false; form(action, e.message); }
  }

  function showPreview(action, p, read) {
    const lines = describeProposal(p);
    const confirm = el('button', { type: 'button', class: p.validation?.introducesErrors ? 'danger' : 'primary', disabled: !p.applicable || p.unchanged,
      onclick: () => apply(action, p) }, p.validation?.introducesErrors ? 'Vẫn áp dụng' : 'Áp dụng');
    box.replaceChildren(header(`Xem trước · ${target.id}`), el('ul', { class: 'ctx-preview' }, ...lines.map((l) => el('li', { class: l.kind }, l.text))),
      el('div', { class: 'row' }, confirm, el('button', { type: 'button', class: 'ghost', onclick: () => form(action) }, 'Sửa lại'), el('button', { type: 'button', class: 'ghost', onclick: close }, 'Hủy')));
    confirm.focus();
  }

  async function apply(action, p) {
    if (busy) return; busy = true; ctx.setStatus('Áp dụng…');
    try {
      const { status, data } = await call(`/api/designs/${p.id}/ops`, { op: p.operation, baseRev: p.baseRev, expect: p.opHash });
      busy = false;
      if (status === 409) return stale(action);
      if (!data || data.error) { ctx.setStatus(data?.error || `Lỗi ${status}`, 'warn'); return form(action, data?.error || `Lỗi ${status}`); }
      close(); await ctx.afterChange(data); ctx.setStatus(`Đã áp dụng: rev ${data.rev}`, 'ok');
    } catch (e) { busy = false; form(action, e.message); }
  }

  function stale(action) {
    box.replaceChildren(header('Thiết kế đã thay đổi'), el('p', { class: 'ctx-msg warn' }, 'Có bản sửa mới hơn (ở tab khác hoặc do job ảnh). Tải lại rồi xem trước lại để không ghi đè.'),
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'primary', onclick: async () => { const id = target.id; await ctx.reload(); if (ctx.getState().spec.module.some((x) => x.id === id)) form(action); else close(); } }, 'Tải lại'),
        el('button', { type: 'button', class: 'ghost', onclick: close }, 'Hủy')));
  }

  document.addEventListener('pointerdown', (e) => { if (!box.hidden && !box.contains(e.target)) close(); }, true);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !box.hidden) { e.stopPropagation(); close(); } }, true);
  window.addEventListener('blur', () => { if (!busy) close(); });
  window.addEventListener('design-opened', () => { if (!busy) close(); });

  return {
    open(t, x, y) { target = t; list(); place(x, y); box.querySelector('button:not(.ctx-x)')?.focus(); },
    close, get isOpen() { return !box.hidden; },
  };
}
