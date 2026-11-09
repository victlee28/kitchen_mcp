// Context menu on a cabinet module in the 3D view: pick an action, fill a small form, preview what it would change, confirm.
// The server decides what a change means (POST .../propose previews, POST .../ops saves); nothing here edits data directly.
import { el } from './dom.js';
import { request } from './api-client.js';
import { interpretBody, describeInterpret, templateIntent, checkUpload, recognizeBody, describeRecognition, recognitionLines } from './assist-logic.js';
import { actionsFor, buildOp, describeProposal, layerFor, menuPosition, DOOR_STYLES, HANDLE_VARIANTS, MATERIAL_PRESETS } from './menu-logic.js';

const call = (path, body) => request(path, 'POST', body);

/**
 * ctx: { box, getState() -> {id, rev, spec}, afterChange(result), reload(), imageEdit({layer, material}), structure: {hide, isolate, showAll}, setStatus }
 */
export function createModuleMenu(ctx) {
  const box = ctx.box;
  let target = null; let step = null; let busy = false; let picking = false;   // picking: the native file dialog is open (the window blurs, the menu must stay)
  box.setAttribute('role', 'dialog'); box.hidden = true;

  const close = () => { box.hidden = true; box.replaceChildren(); target = null; step = null; busy = false; picking = false; };
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
    box.onkeydown = null;
    const cmd = commandBox();
    box.replaceChildren(header(title), ...(cmd ? [cmd] : []), el('ul', { class: 'ctx-list' }, ...actionsFor(target, spec).map((a) =>
      el('li', {}, el('button', { type: 'button', onclick: () => choose(a.id) }, a.label)))));
  }

  // A free sentence about THIS module (a floorplan object has no module: the sentence then covers the whole design) ("đổi sang màu trắng", "rộng 800"): the server reads it, the preview shows the result, nothing is saved before Áp dụng.
  function commandBox(text = '', message = '', choices = []) {
    const input = el('input', { type: 'text', value: text, placeholder: target.kind === 'structure' ? 'Ra lệnh cho cả thiết kế… (Enter)' : `Ra lệnh cho ${target.id}… (Enter)`, autocomplete: 'off', 'aria-label': 'Câu lệnh cho module này' });
    const run = () => command(input.value);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); run(); } });
    const kind = el('select', { 'aria-label': 'Loại ảnh tham chiếu', title: 'Loại ảnh tham chiếu' }, el('option', { value: 'photo' }, 'Ảnh chụp'), el('option', { value: 'drawing' }, 'Bản vẽ'));
    const file = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true });
    file.addEventListener('change', () => { picking = false; if (file.files[0]) recognizeImage(file.files[0], kind.value, input.value); });
    const attach = el('button', { type: 'button', class: 'ghost', title: 'Nhập ảnh chụp bếp hoặc bản vẽ làm tham chiếu: nhận diện ra các tủ rồi xem trước (thay cả thiết kế khi áp dụng)', onclick: () => { picking = true; file.click(); } }, '📎 Ảnh tham chiếu');
    return el('div', { class: 'ctx-cmd' }, input, el('button', { type: 'button', class: 'primary', onclick: run }, 'Xem trước'), attach, kind, file,
      ...(message ? [el('p', { class: 'ctx-msg warn' }, message)] : []),
      ...(choices.length ? [el('div', { class: 'chips' }, ...choices.map((c) => el('button', { type: 'button', class: 'ghost small', onclick: () => command(`${input.value.trim()} ${c}`) }, c)))] : []));
  }

  async function command(text) {
    if (busy) return; const { id, rev } = ctx.getState();
    const intent = templateIntent(text);
    if (intent?.kind === 'shape') return redraw(text, `Chưa tạo được tủ chữ ${intent.shape} bằng lệnh. Hãy dùng "Tạo từ mẫu" ở cột trái, hoặc nói "tủ chữ I" để tạo một dãy dọc cạnh vật thể.`);
    if (intent?.kind === 'run-i') {
      if (target.kind === 'structure') return runI();
      return redraw(text, 'Muốn tạo dãy tủ dọc một cạnh: bấm chuột phải vào vật thể của mặt bằng (tường, cột, đồ) rồi ra lệnh.');
    }
    let body;
    try { body = interpretBody(text, rev, { scope: target.kind === 'structure' ? undefined : [target.id] }); } catch (e) { return ctx.setStatus(e.message, 'warn'); }
    busy = true; ctx.setStatus('Đọc câu lệnh…');
    try {
      const { status, data } = await call(`/api/designs/${id}/interpret`, body);
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error) return redraw(text, data?.error || `Lỗi ${status}`);
      const d = describeInterpret(data);
      if (d.kind === 'preview') return showPreview('cmd', d.proposal, null, d.summary);
      redraw(text, d.kind === 'clarify' ? d.question : d.message, d.kind === 'clarify' ? d.choices : []);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  function fileBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(',')[1] || '');
      r.onerror = () => reject(new Error('Không đọc được tệp'));
      r.readAsDataURL(file);
    });
  }

  async function recognizeImage(file, kind, text) {
    if (busy) return; const { id, rev } = ctx.getState();
    const bad = checkUpload(file); if (bad) return redraw(text, bad);
    busy = true; ctx.setStatus('Nhận diện ảnh tham chiếu…');
    try {
      const { status, data } = await call(`/api/designs/${id}/recognize`, recognizeBody(kind, file.name, file.type, await fileBase64(file), rev, text));
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error) return redraw(text, data?.error || `Lỗi ${status}`);
      const d = describeRecognition(data);
      if (d.kind !== 'preview') return redraw(text, d.text);
      showPreview('cmd', d.proposal, null, [{ kind: 'warn', text: 'Kết quả nhận diện sẽ thay toàn bộ tủ của thiết kế hiện tại (phòng và mặt bằng giữ nguyên; có thể hoàn tác).' }, ...recognitionLines(data)]);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  function redraw(text, message, choices = []) {
    const old = box.querySelector('.ctx-cmd');
    const fresh = commandBox(text, message, choices);
    if (old) old.replaceWith(fresh); else list();
    fresh.querySelector('input')?.focus();
  }

  function choose(action) {
    if (action === 'run-i') return runI();
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

  // A cabinet run against the clicked edge of a floorplan object: the server picks the edge and the facing, the preview shows the result.
  async function runI() {
    if (busy) return; const { id, rev } = ctx.getState();
    busy = true; ctx.setStatus('Tính dãy tủ dọc cạnh vật thể…');
    try {
      const { status, data } = await call(`/api/designs/${id}/template`, { template: { kind: 'run-i', structureId: target.id, point: target.point }, baseRev: rev });
      busy = false;
      if (status === 409) return stale('run-i');
      if (!data || data.error || !data.proposal) {
        box.replaceChildren(header(`Dãy tủ · ${target.id.replace(/^STRUCT-/, '')}`), err(data?.error || `Lỗi ${status}`),
          el('div', { class: 'row' }, el('button', { type: 'button', class: 'ghost', onclick: list }, 'Quay lại')));
        return;
      }
      showPreview('run-i', data.proposal, null, data.summary || []);
    } catch (e) { busy = false; ctx.setStatus(e.message, 'warn'); }
  }

  function showPreview(action, p, read, extra = []) {
    const lines = [...extra.map((x) => (typeof x === 'string' ? { kind: 'info', text: x } : x)), ...describeProposal(p)];
    const confirm = el('button', { type: 'button', class: p.validation?.introducesErrors ? 'danger' : 'primary', disabled: !p.applicable || p.unchanged,
      onclick: () => apply(action, p) }, p.validation?.introducesErrors ? 'Vẫn áp dụng' : 'Áp dụng');
    box.replaceChildren(header(`Xem trước · ${target.id}`), el('ul', { class: 'ctx-preview' }, ...lines.map((l) => el('li', { class: l.kind }, l.text))),
      el('div', { class: 'row' }, confirm, el('button', { type: 'button', class: 'ghost', onclick: () => (action === 'run-i' || action === 'cmd' ? list() : form(action)) }, action === 'run-i' || action === 'cmd' ? 'Quay lại' : 'Sửa lại'), el('button', { type: 'button', class: 'ghost', onclick: close }, 'Hủy')));
    confirm.focus();
  }

  async function apply(action, p) {
    if (busy) return; busy = true; ctx.setStatus('Áp dụng…');
    try {
      const { status, data } = await call(`/api/designs/${p.id}/ops`, { op: p.operation, baseRev: p.baseRev, expect: p.opHash });
      busy = false;
      if (status === 409) return stale(action);
      if (!data || data.error) { ctx.setStatus(data?.error || `Lỗi ${status}`, 'warn'); return action === 'cmd' ? list() : form(action, data?.error || `Lỗi ${status}`); }
      close(); await ctx.afterChange(data); ctx.setStatus(`Đã áp dụng: rev ${data.rev}`, 'ok');
    } catch (e) { busy = false; if (action === 'cmd') ctx.setStatus(e.message, 'warn'); else form(action, e.message); }
  }

  function stale(action) {
    box.replaceChildren(header('Thiết kế đã thay đổi'), el('p', { class: 'ctx-msg warn' }, 'Có bản sửa mới hơn (ở tab khác hoặc do job ảnh). Tải lại rồi xem trước lại để không ghi đè.'),
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'primary', onclick: async () => { const id = target.id; await ctx.reload(); if (action === 'cmd' && target.kind === 'structure') list(); else if (ctx.getState().spec.module.some((x) => x.id === id)) (action === 'cmd' ? list() : form(action)); else close(); } }, 'Tải lại'),
        el('button', { type: 'button', class: 'ghost', onclick: close }, 'Hủy')));
  }

  document.addEventListener('pointerdown', (e) => { if (!box.hidden && !box.contains(e.target)) close(); }, true);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !box.hidden) { e.stopPropagation(); close(); } }, true);
  window.addEventListener('blur', () => { if (!busy && !picking) close(); });
  window.addEventListener('focus', () => setTimeout(() => { picking = false; }, 400));
  window.addEventListener('design-opened', () => { if (!busy) close(); });

  return {
    open(t, x, y) { target = t; list(); place(x, y); box.querySelector('button:not(.ctx-x)')?.focus(); },
    close, get isOpen() { return !box.hidden; },
  };
}
