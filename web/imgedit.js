// Tab "Sửa ảnh theo lớp": chọn chi tiết trên ảnh (instance mask phía máy chủ), tạo job, so sánh trước/sau, duyệt.
// Không phụ thuộc three.js: vẫn chạy khi CDN three.js lỗi. Mọi chữ hiển thị qua textContent.
import { partIndex, shiftGroupId, ctrlIds, toggleIds, layerIdFor, partitionByType, targetFor, partsOf, targetLabel, roleName } from './selection.js';
import { $, el } from './dom.js';
import { api, createStatus } from './api-client.js';
import { styleFromOptions, styleFromValue } from './assist-logic.js';
import { modelChoices } from './menu-logic.js';
import './boot.js';
import { PALETTES } from './palette-client.js';
import { applianceName } from './i18n.js';
const S = { id: null, view: null, data: null, layer: null, job: null, jobs: [], poll: null, maskImg: null, tasks: [], maskCache: {}, sel: [], key: '' };
const PALETTE = (PALETTES.zone || []).map((z) => z.rgb).concat(PALETTES.zone?.length ? [] : [[255, 0, 0]]);   // numbered edit zones (catalog palette "zone")
const MAX_TASKS = 8;

const { setStatus: status, run } = createStatus($('status'));
const bust = (u) => u && `${u}${u.includes('?') ? '&' : '?'}t=${Date.now()}`;

// ---------------- tab
function showTab(img, skipLoad = false) {
  $('tab3d').classList.toggle('on', !img); $('tabImg').classList.toggle('on', img);
  $('tab3d').setAttribute('aria-selected', String(!img)); $('tabImg').setAttribute('aria-selected', String(img));
  $('pane3d').hidden = img; $('paneImg').hidden = !img; $('bar3d').hidden = img; $('barImg').hidden = !img;
  if (img && !skipLoad) run('mở ảnh', load);
}
$('tab3d').addEventListener('click', () => showTab(false));
$('tabImg').addEventListener('click', () => showTab(true));
const active = () => !$('paneImg').hidden;

// ---------------- tải layer + ảnh gốc
async function load() {
  S.id = $('designSelect').value; S.view = $('viewSelect').value;
  if (!S.id || !S.view) return;
  if (S.key !== `${S.id}|${S.view}`) { S.key = `${S.id}|${S.view}`; S.sel = []; S.tasks = []; S.layer = null; renderTasks(); }  // chọn/việc chỉ có nghĩa trong đúng thiết kế + góc
  const d = await api(`/api/designs/${S.id}/layers?view=${encodeURIComponent(S.view)}`);
  S.data = d;
  geometryForm(); fillStyleFrom();
  const bt = d.baseImage.type;
  const lineBad = bt === 'imported' && d.baseImage.lineMatch && d.baseImage.lineMatch.khop === false;
  $('imgInfo').textContent = `rev ${d.rev} · ${d.width}×${d.height} · renderKey ${d.renderKey} · ảnh gốc: ${bt === 'job' ? d.baseImage.jobId : bt === 'imported' ? 'ảnh nhập từ AI' : bt}` +
    (lineBad ? ' · ⚠ nét ảnh lệch so với thiết kế (ảnh AI có thể đã vẽ lại hình, mask sửa sẽ không khớp)' : '');
  $('baseClear').hidden = bt !== 'imported';
  $('imgBase').src = bust(d.baseImage.url);
  $('imgAfter').hidden = true; $('cmpWrap').hidden = true;
  const sel = $('layerSelect'); const prev = S.layer; sel.replaceChildren();
  const groups = d.layers.filter((x) => x.variant === 'group'), parts = d.layers.filter((x) => x.variant === 'part');
  for (const [label, xs] of [['Nhóm', groups], ['Chi tiết', parts]]) {
    const og = el('optgroup', { label });
    for (const x of xs) og.append(el('option', { value: x.id, textContent: `${x.name} · ${x.id}` }));
    sel.append(og);
  }
  if (prev && d.layers.some((x) => x.id === prev)) sel.value = prev;
  if (S.sel.length && S.layer?.startsWith('parts:') && S.sel.every((i) => d.layers.some((x) => x.id === i))) await setSel(S.sel, []);
  else await selectLayer(sel.value, []);
  await loadJobs();
}
async function selectLayer(id, alts) {
  S.layer = id; if ([...$('layerSelect').options].some((o) => o.value === id)) $('layerSelect').value = id;
  const x = S.data?.layers.find((l) => l.id === id);
  S.sel = x ? [...(x.component || [x.id])] : partsOf(id, S.data?.layers || []);
  if (x?.module && [...$('hId').options].some((o) => o.value === x.module)) $('hId').value = x.module;  // bấm vào tủ -> chọn sẵn cho sửa hình
  $('layerInfo').textContent = x ? `${x.semanticClass} · vật liệu: ${x.material || '—'} · ${x.pixels} px` +
    (x.designEdit ? ` · sửa thiết kế áp cho ${x.designEdit}` : x.designEditNote ? ` · thử nhanh (không ghi được vào thiết kế): ${x.designEditNote}` : ' · chỉ sửa được ảnh (thử nhanh)') : '';
  const box = $('layerAlt'); box.replaceChildren();
  for (const a of alts) box.append(el('button', { type: 'button', class: a === id ? 'on' : '', textContent: a, onclick: () => selectLayer(a, alts) }));
  renderSel();
  renderSwap(x).catch((e) => status(e.message, "warn"));
  await drawMask();
}

// An appliance layer (TB4-cooktop-1): another model can be picked here; once applied, the job form is filled with the model's description.
const APPLIANCE_TYPES = ['cooktop', 'sink', 'faucet', 'hood', 'fridge', 'oven'];
function swapBox() {
  let box = document.getElementById('applSwap');
  if (!box) { box = el('div', { id: 'applSwap', class: 'appl-swap' }); $('layerAlt').after(box); }
  return box;
}
async function renderSwap(layer) {
  const box = swapBox(); box.replaceChildren();
  const id = layer?.module; if (!layer || !APPLIANCE_TYPES.includes(layer.type) || !/^TB\d+$/.test(id || '')) return;
  const r = await api(`/api/designs/${S.id}/template`, 'POST', { template: { kind: 'replace-appliance', id, prompt: '' } });
  const choices = modelChoices(r.models);
  const pick = el('select', {}, ...choices.map((c) => el('option', { value: c.id, disabled: !c.pickable }, c.label)));
  const widen = el('input', { type: 'checkbox' });
  const out = el('ul', { class: 'small' });
  const apply = el('button', { type: 'button' }, 'Áp dụng mẫu này + điền job'); apply.hidden = true;
  let preview = null;
  for (const input of [pick, widen]) input.addEventListener('change', () => { apply.hidden = true; out.replaceChildren(); });   // another choice: preview again
  const show = () => run('xem trước mẫu', async () => {
    preview = await api(`/api/designs/${S.id}/template`, 'POST', { template: { kind: 'replace-appliance', id, model: pick.value, resizeHost: widen.checked } });
    out.replaceChildren(...(preview.summary || []).map((t) => el('li', { textContent: t })));
    apply.hidden = !preview.proposal?.applicable;
  });
  apply.addEventListener('click', () => run('đổi mẫu thiết bị', async () => {
    const p = preview.proposal;
    await api(`/api/designs/${p.id}/ops`, 'POST', { op: p.operation, baseRev: p.baseRev, expect: p.opHash });
    window.dispatchEvent(new CustomEvent('design-reload-request', { detail: { id: S.id } }));
    $('jItem').value = ''; $('jInstr').value = preview.aiFacts?.prompt || ''; $('jMode').value = 'quick';      // the model is described in the request itself
    status(`Đã đổi ${id} sang ${preview.aiFacts?.name || pick.value}. Ảnh nền sẽ được render lại; bấm "Tạo job sửa" để AI vẽ mẫu mới`, 'ok');
    out.replaceChildren(); apply.hidden = true;
  }));
  box.append(el('b', { textContent: `Đổi mẫu ${applianceName(layer.type)} ${id}` }),
    el('label', {}, 'Mẫu', pick), el('label', { class: 'inline' }, widen, ' Nới tủ đỡ nếu không vừa'),
    el('button', { type: 'button', class: 'ghost', onclick: show }, 'Xem trước'), apply, out);
}
// Chọn nhiều: S.sel là danh sách id chi tiết; S.layer là tên layer tương ứng (layer có sẵn nếu khớp đúng, không thì `parts:a,b,c`).
async function setSel(ids, alts) {
  if (!ids.length) { S.sel = []; S.layer = null; $('layerInfo').textContent = 'Chưa chọn chi tiết nào'; $('layerAlt').replaceChildren(); renderSel(); return drawMask(); }
  const id = layerIdFor(ids, S.data.layers);
  if (id) return selectLayer(id, alts);
  S.sel = [...ids]; S.layer = targetFor(ids);
  const idx = partIndex(S.data.layers); const types = new Set(ids.map((i) => idx.get(i)?.type));
  $('layerInfo').textContent = `${ids.length} chi tiết${types.size === 1 ? ' · ' + roleName([...types][0]) : ' · nhiều loại (sẽ tách thành từng việc theo loại)'} · ` +
    'Thử nhanh sửa đúng các chi tiết này; Sửa thiết kế chỉ ghi được khi diễn đạt chính xác trong thiết kế, nếu không máy chủ sẽ báo lý do';
  $('layerAlt').replaceChildren();
  renderSel(); await drawMask();
}
function renderSel() {
  const box = $('selList'); if (!box) return; box.replaceChildren();
  const idx = partIndex(S.data?.layers || []);
  if (S.sel.length < 2) { box.hidden = true; return; }
  box.hidden = false;
  box.append(el('span', { class: 'muted small', textContent: `Đã chọn ${S.sel.length}: ` }));
  for (const i of S.sel.slice(0, 40)) box.append(el('button', { type: 'button', title: 'Bỏ chi tiết này', textContent: `${i} ✕`, onclick: () => run('bỏ chọn', () => setSel(S.sel.filter((x) => x !== i), [])) }));
  if (S.sel.length > 40) box.append(el('span', { class: 'muted small', textContent: ` …và ${S.sel.length - 40} chi tiết nữa` }));
  box.append(el('button', { type: 'button', class: 'clr', textContent: 'Xóa chọn', onclick: () => run('xóa chọn', () => setSel([], [])) }));
}
async function maskData(layer) {
  const key = `${S.id}|${S.view}|${S.data.rev}|${layer}`;
  if (S.maskCache[key]) return S.maskCache[key];
  const img = new Image();
  img.src = `/api/designs/${S.id}/mask?view=${encodeURIComponent(S.view)}&layer=${encodeURIComponent(layer)}&t=${Date.now()}`;
  await img.decode();
  const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
  const g = c.getContext('2d'); g.drawImage(img, 0, 0);
  return (S.maskCache[key] = g.getImageData(0, 0, c.width, c.height));
}
async function drawMask() {
  // layer đang chọn: xanh dương nhạt; các việc trong danh sách: mỗi việc một màu (khớp mask màu gửi model)
  const cv = $('maskOverlay'); const g = cv.getContext('2d');
  if (!S.data) { g.clearRect(0, 0, cv.width, cv.height); return; }
  cv.width = S.data.width; cv.height = S.data.height;
  const out = g.createImageData(cv.width, cv.height); const o = out.data;
  const paint = (md, rgb, alpha) => { const a = md.data; for (let i = 0; i < a.length; i += 4) if (a[i] > 127) { o[i] = rgb[0]; o[i + 1] = rgb[1]; o[i + 2] = rgb[2]; o[i + 3] = alpha; } };
  for (const [k, t] of S.tasks.entries()) paint(await maskData(t.targetLayer), PALETTE[k % PALETTE.length], 120);
  if (S.layer) paint(await maskData(S.layer), [47, 107, 255], 110);
  g.putImageData(out, 0, 0);
  cv.hidden = !$('showMask').checked;
}
function renderTasks() {
  const ol = $('taskList'); ol.replaceChildren();
  S.tasks.forEach((t, k) => {
    const c = PALETTE[k % PALETTE.length];
    ol.append(el('li', {}, el('span', { class: 'sw', style: `background:rgb(${c.join(',')})` }),
      `${targetLabel(t.targetLayer, S.data?.layers || [])}${t.material ? ' → ' + t.material : ''}${t.instruction ? ' · ' + t.instruction : ''}`,
      el('button', { type: 'button', textContent: 'xóa', onclick: () => { S.tasks.splice(k, 1); renderTasks(); drawMask().catch(console.error); } })));
  });
  $('tClear').hidden = !S.tasks.length;
  $('jCreate').textContent = S.tasks.length ? `Tạo job sửa (${S.tasks.length} việc)` : 'Tạo job sửa';
}
$('tAdd').addEventListener('click', () => run('thêm việc', async () => {
  if (!S.layer) throw new Error('Hãy chọn chi tiết trước');
  const vat = $('jItem').value.trim(), instr = $('jInstr').value.trim();
  if (!vat && !instr) throw new Error('Nhập vật liệu mới hoặc yêu cầu cho việc này');
  // Một việc chỉ có một vai trò (để lời nhắc đúng): lựa chọn nhiều loại được tách thành mỗi loại một việc.
  const idx = partIndex(S.data.layers);
  const targets = S.layer.startsWith('parts:') ? partitionByType(S.sel, idx).map(targetFor) : [S.layer];
  if (S.tasks.length + targets.length > MAX_TASKS) throw new Error(`Tối đa ${MAX_TASKS} việc mỗi job (lựa chọn này cần thêm ${targets.length} việc, đang có ${S.tasks.length})`);
  const used = new Set(S.tasks.flatMap((t) => partsOf(t.targetLayer, S.data.layers)));
  const clash = targets.flatMap((t) => partsOf(t, S.data.layers)).filter((i) => used.has(i));
  if (clash.length) throw new Error(`${clash.length} chi tiết (vd ${clash[0]}) đã nằm trong một việc khác; bỏ việc cũ hoặc bỏ chọn chúng`);
  for (const t of targets) S.tasks.push({ targetLayer: t, material: vat || null, instruction: instr });
  $('jItem').value = ''; $('jInstr').value = '';
  renderTasks(); await drawMask();
}));
$('tClear').addEventListener('click', () => { S.tasks = []; renderTasks(); drawMask().catch(console.error); });
$('layerSelect').addEventListener('change', (e) => run('chọn layer', () => selectLayer(e.target.value, [])));
$('showMask').addEventListener('change', () => { $('maskOverlay').hidden = !$('showMask').checked; });
$('imgBase').addEventListener('click', (ev) => {
  if (!S.data) return;
  const im = ev.currentTarget; const r = im.getBoundingClientRect();
  const x = Math.floor(((ev.clientX - r.left) / r.width) * S.data.width), y = Math.floor(((ev.clientY - r.top) / r.height) * S.data.height);
  const ctrl = ev.ctrlKey || ev.metaKey, shift = ev.shiftKey;
  run('chọn chi tiết', async () => {
    // radius: tay nắm chỉ rộng 23–86 px, cho phép bấm lệch vài điểm ảnh
    const p = await api(`/api/designs/${S.id}/pick?view=${encodeURIComponent(S.view)}&x=${x}&y=${y}&radius=4`);
    if (!p.part) return status('Không có chi tiết ở điểm này');
    const idx = partIndex(S.data.layers); const part = idx.get(p.part.id);
    if (!part) return selectLayer(p.layers[0], p.layers);
    if (shift) {  // cả nhóm cùng vai trò, cùng tầng, cùng hệ tủ
      const gid = shiftGroupId(part, S.data.layers); const g = gid && S.data.layers.find((l) => l.id === gid);
      if (!g) throw new Error('Không có nhóm cùng loại để chọn');
      return setSel([...(g.component || [])], []);
    }
    if (ctrl) {  // thêm/bớt một chi tiết cùng loại
      const selType = S.sel.length ? idx.get(S.sel[0])?.type : null;
      const c = ctrlIds(selType, part, S.data.layers);
      if (c.error) throw new Error(c.error);
      return setSel(toggleIds(S.sel, c.ids), []);
    }
    await selectLayer(p.layers[0], p.layers);
  });
});

// các bản JSON của một job, chuyển ngay trong ô xem
function jobVariants(id, notSent) {
  const t = notSent ? ' (chưa gửi)' : '';
  return [
    { label: 'Rút gọn', hint: 'Bản gửi AI: chỉ dẫn + ảnh đính kèm', url: `/api/image-jobs/${id}/request`, name: `${id}-request.json`, title: `Request gửi AI (rút gọn) · ${id}${t}` },
    { label: 'Đầy đủ', hint: 'Bản kiểm tra, không gửi AI', url: `/api/image-jobs/${id}/request?format=day-du`, name: `${id}-request.full.json`, title: `Bản đầy đủ (không gửi AI) · ${id}${t}` },
    { label: 'Gemini API', hint: 'Thân request Gemini API (ảnh ở inline_data)', url: `/api/image-jobs/${id}/request?format=gemini`, name: `${id}-gemini-request.json`, title: `Thân request Gemini API · ${id}${t}` },
  ];
}

// ---------------- so sánh trước / sau
function compare(job) {
  const after = job?.files?.['composite.png'];
  if (!after) { $('imgAfter').hidden = true; $('cmpWrap').hidden = true; return; }
  const before = job.files['reference.png'] || $('imgBase').src;
  $('imgBase').src = bust(before); $('imgAfter').src = bust(after); $('imgAfter').hidden = false; $('cmpWrap').hidden = false;
  clip();
}
function clip() { const v = Number($('cmpSlider').value); $('imgAfter').style.clipPath = `inset(0 0 0 ${v}%)`; }
$('cmpSlider').addEventListener('input', clip);

// ---------------- job
async function loadBackends() {
  const b = await api('/api/image-backends');
  $('jBackend').replaceChildren(...Object.entries(b.backends).map(([k, v]) => el('option', { value: k, textContent: `${k} — ${v.name}` })));
  if (b.default && b.backends[b.default]) $('jBackend').value = b.default;
  S.operation = b.operation || {};
  $('jOperation').replaceChildren(el('option', { value: '', textContent: 'tự động' }),
    ...Object.entries(S.operation).map(([k, v]) => el('option', { value: k, textContent: `${v.name} (${v.kind})`, title: v.description })));
}
function operationFor(kind) {  // chỉ gửi cấu hình chọn sẵn khi khớp loại job
  const t = $('jOperation').value;
  return t && S.operation?.[t]?.kind === kind ? t : null;
}

// ------------------------------------------------------------------ sửa hình (xóa / thêm / thay vật)
const KIEU = {
  'door-style': [['flat', 'Cánh phẳng'], ['frame', 'Cánh khung (shaker)'], ['glass', 'Cánh kính']],
  'handle': [['bar', 'Tay thanh'], ['knob', 'Núm tròn'], ['concealed', 'Tay âm (khoét)'], ['none', 'Không tay (nhấn mở)']],
};
S.geometry_edit = [];
function geometryForm() {
  const k = $('hType').value;
  $('hIdWrap').hidden = !['remove-module', 'door-style'].includes(k);
  $('hStyleWrap').hidden = !KIEU[k];
  $('hCloseGapWrap').hidden = k !== 'remove-module';
  $('hJsonWrap').hidden = !['add-module', 'op'].includes(k);
  $('hJson').placeholder = k === 'op' ? '{"op": "update", "id": "TD1", "changes": {"height": 820}}' : '{"module": {"id": "TD6", "type": "base", "wall": "right", "width": 450, "height": 720, "depth": 560}, "afterModule": "TD5"}';
  if (KIEU[k]) $('hStyle').replaceChildren(...KIEU[k].map(([v, t]) => el('option', { value: v, textContent: t })));
  const mods = (S.data?.layers || []).filter((l) => l.id.startsWith('module:') && l.type === 'module').map((l) => l.module);
  const cur = $('hId').value;
  $('hId').replaceChildren(...(k === 'door-style' ? [el('option', { value: '*', textContent: '* mọi module' })] : []),
    ...mods.map((m) => el('option', { value: m, textContent: m })));
  if (cur && [...$('hId').options].some((o) => o.value === cur)) $('hId').value = cur;
}
function geometryItem() {
  const k = $('hType').value;
  if (k === 'remove-module') return { type: k, id: $('hId').value, closeGap: $('hCloseGap').checked };
  if (k === 'door-style') return { type: k, id: $('hId').value, variant: $('hStyle').value };
  if (k === 'handle') return { type: k, variant: $('hStyle').value };
  let j;
  try { j = JSON.parse($('hJson').value || '{}'); } catch (e) { throw new Error(`JSON lỗi: ${e.message}`); }
  return k === 'op' ? { type: 'op', op: j } : { type: k, ...j };
}
function geometryText(x) {
  if (x.type === 'remove-module') return `Xóa ${x.id}${x.closeGap ? ' (dồn tủ)' : ''}`;
  if (x.type === 'door-style') return `${x.id === '*' ? 'Mọi module' : x.id}: ${KIEU['door-style'].find((k) => k[0] === x.variant)[1]}`;
  if (x.type === 'handle') return `Tay nắm: ${KIEU['handle'].find((k) => k[0] === x.variant)[1]}`;
  if (x.type === 'add-module') return `Thêm ${x.module?.id || 'module'}`;
  return `Thao tác ${x.op?.op || '?'}`;
}
function renderGeometry() {
  $('hList').replaceChildren(...S.geometry_edit.map((x, i) => el('li', {}, geometryText(x), ' ',
    el('button', { type: 'button', class: 'ghost small', textContent: '✕', onclick: () => { S.geometry_edit.splice(i, 1); renderGeometry(); } }))));
  $('hCreate').textContent = S.geometry_edit.length > 1 ? `Tạo job sửa hình (${S.geometry_edit.length} thao tác)` : 'Tạo job sửa hình';
}
$('hType').addEventListener('change', geometryForm);
$('geometryBox').addEventListener('toggle', geometryForm);
$('hAdd').addEventListener('click', () => run('thêm thao tác', async () => { S.geometry_edit.push(geometryItem()); renderGeometry(); }));
$('hCreate').addEventListener('click', () => S.data && run('tạo job sửa hình', async () => {
  if (!S.geometry_edit.length) S.geometry_edit.push(geometryItem());
  await create('geometry_edit');
}));
function fillStyleFrom() {
  const sel = $('jStyleFrom'); const keep = sel.value;
  sel.replaceChildren(...styleFromOptions([...$('viewSelect').options].map((o) => o.value), S.view).map((o) => el('option', { value: o.value, textContent: o.label })));
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}
async function create(kind) {
  const body = { view: S.view, kind, backend: $('jBackend').value, mode: $('jMode').value, material: $('jItem').value.trim() || null,
    instruction: $('jInstr').value.trim(), reference: $('jRef').value, baseRev: S.data.rev,
    preview: $('jPreview').checked };
  body.operation = operationFor(kind);
  const views = [...$('viewSelect').options].map((o) => o.value);
  const sf = styleFromValue($('jStyleFrom').value, views, S.view); if (sf) body.styleFrom = sf;
  body.lighting = $('jLight').value;
  if (kind === 'geometry_edit') { body.geometry_edit = S.geometry_edit; body.material = null; body.mode = 'design'; }
  else if (kind === 'edit' && S.tasks.length) {  // nhiều việc: ô vật liệu/yêu cầu lúc này là yêu cầu chung
    body.tasks = S.tasks; body.material = null;
  } else if (kind === 'edit') body.targetLayer = S.layer;
  const j = await api(`/api/designs/${S.id}/image-jobs`, 'POST', body);
  S.job = j.id; if (kind === 'edit' && S.tasks.length) { S.tasks = []; renderTasks(); await drawMask(); }
  if (kind === 'geometry_edit') { S.geometry_edit = []; renderGeometry(); }
  await loadJobs();
  if (j.status === 'awaiting-send') {  // xem trước: mở ngay request sẽ gửi
    status('Job đang chờ gửi — kiểm tra JSON rồi bấm Gửi', 'ok');
    await window.kitchenJson?.showJsonUrl(`Xem trước request · ${j.id} (chưa gửi)`, `/api/image-jobs/${j.id}/request`, `${j.id}-request.json`, jobVariants(j.id, true));
  }
}
$('jCreate').addEventListener('click', () => S.data && run('tạo job sửa', () => create('edit')));
$('jGen0').addEventListener('click', () => S.data && run('tạo job gen-0', () => create('gen0')));

async function loadJobs() {
  S.jobs = await api(`/api/image-jobs?design=${encodeURIComponent(S.id)}&view=${encodeURIComponent(S.view)}`);
  const ul = $('jobList'); ul.replaceChildren();
  for (const j of S.jobs) {
    const st = j.status.startsWith('error') ? 'error' : j.status;
    ul.append(el('li', { class: j.id === S.job ? 'sel' : '', onclick: () => { S.job = j.id; loadJobs(); } },
      el('span', {}, `${j.kind === 'gen0' ? 'gen-0' : j.kind === 'geometry_edit' ? `✎ ${j.target.replace(/^geometry: /, '')}` : j.target} · ${j.backend}`), el('span', { class: `st ${st}` }, j.status)));
  }
  const cur = S.jobs.find((j) => j.id === S.job);
  showJob(cur);
  const running = S.jobs.some((j) => j.status === 'running');
  clearTimeout(S.poll); if (running && active()) S.poll = setTimeout(() => loadJobs().catch(console.error), 2000);
}
function showJob(j) {
  const box = $('jobDetail'); box.replaceChildren(); box.hidden = !j;
  if (!j) { compare(null); return; }
  const r = j.result || {}; const rep = r.report || {}; const req = j.request || {};
  box.append(el('p', {}, el('b', {}, j.id), ` · ${j.mode} · rev ${j.rev}`));
  if (req.scope) box.append(el('p', {}, `Phạm vi thiết kế: ${req.scope}`));
  if (req.prompt) box.append(el('p', { class: 'muted' }, `Prompt: ${req.prompt}`));
  if (j.error) box.append(el('p', { class: 'st error' }, j.error));
  if (rep.outsideMask) {
    box.append(el('p', {}, `Ngoài mask: ${rep.outsideMask.setPreserve ? 'giữ nguyên ✓' : rep.outsideMask.pixelsChanged + ' px khác ✗'} · ` +
      `trong mask đổi ${rep.insideMask.meanChange}` + (rep.bien ? ` · biên ${rep.bien.setEdge ? '✓' : '✗'} (${rep.bien.resultLineRatio}/${rep.bien.baseLineRatio})` : '') +
      ` · ảnh thô lệch ngoài vùng sửa ${rep.rawImage.changesOutsideEditZone}`));
  }
  if (rep.task?.length > 1) {
    const ol = el('ol', { class: 'tasks' });
    rep.task.forEach((v, k) => { const c = PALETTE[k % PALETTE.length]; const t = (req.tasks || [])[k] || {};
      ol.append(el('li', {}, el('span', { class: 'sw', style: `background:rgb(${c.join(',')})` }),
        `${v.targetLayer}${t.material ? ' → ' + t.material : ''}: ${v.insideMask.changed ? 'đã đổi ✓' : 'gần như không đổi ✗'}` +
        (v.bien ? ` · biên ${v.bien.setEdge ? '✓' : '✗'}` : ''))); });
    box.append(ol);
  }
  if (r.design) box.append(el('p', { class: 'st accepted' }, `Đã ghi vào thiết kế: rev ${r.design.rev} (${r.design.scope})` +
    (r.design.skip ? ` · bỏ qua: ${r.design.skip.join('; ')}` : '')));
  const row = el('div', { class: 'row' });
  const act = (label, path, body, after) => row.append(el('button', { type: 'button', textContent: label, onclick: () => run(label, async () => {
    const res = await api(`/api/image-jobs/${j.id}/${path}`, 'POST', body || {}); if (path === 'regenerate') S.job = res.id;
    await loadJobs(); if (after) await after(res);
  }) }));
  const reloadDesign = async (res) => { if (res.result?.design) window.dispatchEvent(new CustomEvent('design-reload-request', { detail: { id: S.id } })); };
  if (j.status === 'awaiting-send') {
    box.append(el('p', { class: 'st awaiting-send' }, `Chưa gửi: kiểm tra mask và chỉ dẫn (Xem JSON) rồi bấm Gửi.`));
    act(`Gửi ${j.backend}`, 'send');
  }
  if (j.status === 'needs-review') {
    act(j.mode === 'design' ? 'Chấp nhận & ghi thiết kế' : 'Chấp nhận', 'accept', {}, async (res) => { await reloadDesign(res); await load(); });
    if (j.mode === 'quick' && (req.material || (req.tasks || []).some((t) => t.material))) act('Chấp nhận & áp vào thiết kế', 'accept', { applyToDesign: true }, async (res) => { await reloadDesign(res); await load(); });
  }
  if (!['accepted', 'rejected'].includes(j.status)) act(j.status === 'awaiting-send' ? 'Hủy' : 'Từ chối', 'reject');
  if (!['running', 'awaiting-send'].includes(j.status)) act('Sinh lại', 'regenerate');
  const canImport = j.status === 'awaiting-result' || j.status.startsWith('error') || j.status === 'needs-review';
  if (canImport) {
    const inp = el('input', { type: 'file', accept: 'image/*', hidden: true });
    inp.addEventListener('change', () => run('nộp ảnh', async () => {
      const f = inp.files[0]; if (!f) return;
      const b64 = await new Promise((ok, err) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.onerror = err; fr.readAsDataURL(f); });
      await api(`/api/image-jobs/${j.id}/result`, 'POST', { imageBase64: b64 }); await loadJobs();
    }));
    const importButton = el('button', { type: 'button', textContent: 'Nhập ảnh kết quả từ AI', onclick: () => inp.click() });
    row.append(importButton, inp);
  }
  box.append(row);
  // gửi AI: bản đã lọc (xem), thân Gemini API (ảnh inline_data, Gemini tự giải mã), hoặc Gemini web (đính kèm ảnh + dán chỉ dẫn)
  const n = (req.tasks || []).length;
  const send = el('div', { class: 'sendai' }, el('b', {}, `Gửi AI${n > 1 ? ` (${n} việc)` : ''}: `),
    el('a', { href: '#', textContent: 'Xem JSON (rút gọn / đầy đủ)', onclick: (ev) => { ev.preventDefault();
      run('mở request', () => window.kitchenJson.showJsonUrl(`Request gửi AI · ${j.id}`, `/api/image-jobs/${j.id}/request`, `${j.id}-request.json`, jobVariants(j.id, j.status === 'awaiting-send'))); } }),
    ' · ', el('a', { href: `/api/image-jobs/${j.id}/request?format=gemini`, download: `${j.id}-gemini-request.json`, textContent: 'JSON cho Gemini API' }));
  const web = el('div', { class: 'sendai' }, el('b', {}, 'ChatGPT / Claude / Gemini thủ công: '),
    el('a', { href: '#', textContent: 'Chép chỉ dẫn', onclick: (ev) => { ev.preventDefault(); run('chép chỉ dẫn', async () => {
      const r = await (await fetch(`/api/image-jobs/${j.id}/request`)).json();
      await navigator.clipboard.writeText(r.instruction); status('Đã chép chỉ dẫn — đính kèm ảnh tham chiếu rồi dán vào công cụ AI', 'ok'); }); } }));
  for (const [k, u] of Object.entries(j.files || {}).filter(([k]) => /^image-\d-/.test(k)).sort()) {
    web.append(' · ', el('a', { href: u, download: `${j.id}-${k}`, textContent: `Ảnh ${k.split('-')[1]}: ${k.replace(/^image-\d-|\.png$/g, '')}` }));
  }
  web.append(el('div', { class: 'warnbox', textContent: canImport
    ? 'Đính kèm ảnh tham chiếu ở trên vào ChatGPT, Claude hoặc Gemini, dán chỉ dẫn đã chép và tạo ảnh. Sau đó bấm “Nhập ảnh kết quả từ AI” để đưa ảnh về đây; ảnh sẽ được kiểm tra và chờ bạn duyệt.'
    : j.status === 'awaiting-send'
      ? `Nút “Nhập ảnh kết quả từ AI” chỉ hiện khi job ở trạng thái chờ kết quả. Job này đang chờ gửi (backend ${j.backend}): để làm thủ công với ChatGPT, Claude hoặc Gemini, hãy dùng job backend job-package rồi bấm Gửi — job chuyển sang “chờ kết quả” và nút sẽ hiện.`
      : 'Nút “Nhập ảnh kết quả từ AI” không hiện ở trạng thái này của job.' }));
  const kt = el('div', { class: 'sendai kiemtra', textContent: 'Kiểm tra request: đang kiểm tra…' });
  {
    fetch(`/api/image-jobs/${j.id}/request`).then((r) => r.json()).then((r) => showCheck(kt, r.validation, 'Kiểm tra request'))
      .catch((e) => { kt.textContent = `Kiểm tra request: lỗi ${e.message}`; });
  }
  const chk = el('input', { type: 'file', accept: '.json,application/json,text/plain' });
  chk.addEventListener('change', () => run('kiểm tra file', async () => {
    const f = chk.files[0]; if (!f) return;
    const r = await api('/api/check-request', 'POST', { text: await f.text() });
    showCheck(kt, r, `Kiểm tra file ${f.name}`, true); chk.value = '';
  }));
  web.append(el('label', { class: 'file', textContent: 'Kiểm tra một file request…', title: 'Nạp file request.json / gemini-request.json để phát hiện file bị cắt, thiếu ảnh, base64 hỏng' }, chk));
  box.append(send, web, kt);
  if (j.files) {
    const links = el('p', { class: 'muted' }, 'File: ');
    for (const [k, u] of Object.entries(j.files)) links.append(el('a', { href: u, target: '_blank', textContent: k }), ' ');
    box.append(links);
  }
  compare(j);
}

function showCheck(box, kt, title, file = false) {
  // kết quả kiểm tra request: đạt / lỗi (chặn gửi) / cảnh báo
  if (!kt) { box.textContent = `${title}: không có dữ liệu`; return; }
  box.replaceChildren(el('b', { class: kt.ok ? 'ok' : 'bad', textContent: `${title}: ${kt.ok ? '✓ đạt' : (file ? '✗ file lỗi — đừng gửi file này' : '✗ CHƯA ĐẠT — chưa gửi được')}` }));
  const imgs = (kt.image || []).map((a) => `ảnh ${a.order}${a.role ? ` (${a.role})` : ''} ${a.ok ? `✓${a.dimensions ? ` ${a.dimensions.join('×')}` : ''}` : '✗'}`);
  if (imgs.length) box.append(el('div', { class: 'muted', textContent: imgs.join(' · ') }));
  const ul = el('ul');
  for (const x of kt.errors || []) ul.append(el('li', { class: 'bad', textContent: x }));
  for (const x of kt.warning || []) ul.append(el('li', { class: 'warn', textContent: x }));
  if (ul.childElementCount) box.append(ul);
}

// "Sửa ảnh của module này" from the 3D context menu: open this tab on the layer, in the view where it shows most pixels.
const MIN_VISIBLE_PX = 400;   // below this the model tends to skip the region (kitchen/request_check.py MIN_PIXELS)
async function bestView(id, layer, alts = []) {
  const views = [...$('viewSelect').options].map((o) => o.value);
  const cur = $('viewSelect').value; const order = [cur, ...views.filter((v) => v !== cur)];
  let best = { view: cur, px: -1 };
  for (const v of order) {
    const d = await api(`/api/designs/${id}/layers?view=${encodeURIComponent(v)}`);
    const px = [layer, ...alts].map((l) => d.layers.find((x) => x.id === l)).find(Boolean)?.pixels ?? 0;
    if (px > best.px) best = { view: v, px };
    if (px >= MIN_VISIBLE_PX && v === cur) break;      // the view already on screen is good enough: keep it
    if (px >= MIN_VISIBLE_PX * 4) break;
  }
  return best;
}
window.addEventListener('image-edit-request', async (ev) => { try {
  // detail: { layer, alts?, module?, material?, instruction?, mode? ('quick'|'design'), preview? (bool) } — prefilled, never submitted from here
  const { module, material, instruction, mode, preview, alts } = ev.detail || {}; let { layer } = ev.detail || {}; const id = $('designSelect').value;
  if (!id || !layer) return;
  status('Tìm góc nhìn thấy rõ module…');
  const best = await bestView(id, layer, alts || []);
  $('viewSelect').value = best.view;
  showTab(true, true);
  await load();
  layer = [layer, ...(alts || [])].find((l) => S.data?.layers.some((x) => x.id === l)) || layer;   // the first of the candidates the catalogue has
  if (S.data?.layers.some((x) => x.id === layer)) await selectLayer(layer, []);
  if (typeof material === 'string') $('jItem').value = material;
  if (typeof instruction === 'string') $('jInstr').value = instruction;
  if (mode === 'quick' || mode === 'design') $('jMode').value = mode;
  if (typeof preview === 'boolean') $('jPreview').checked = preview;
  if (best.px < MIN_VISIBLE_PX) status(`${module || layer} gần như không thấy ở góc nhìn nào (${Math.max(best.px, 0)} px): job có thể bị từ chối vì vùng quá nhỏ`, 'warn');
  else status(`${module || layer}: góc nhìn ${best.view} (${best.px} px). Chọn chế độ, backend rồi tạo job ở khung bên phải`, 'ok');
} catch (e) { console.error(e); status(e.message, 'warn'); } });
window.addEventListener('design-opened', () => { if (active()) run('mở ảnh', load); });
window.addEventListener('view-changed', () => { if (active()) run('mở ảnh', load); });
$('designSelect').addEventListener('change', () => { S.layer = null; S.sel = []; S.job = null; S.tasks = []; renderTasks(); });
loadBackends().catch((e) => status(e.message, 'warn'));

// ---------------- import an AI-generated image as the base image for the selected view
$('baseImport').addEventListener('click', () => {
  if (!S.id || !S.view) { status('Chọn thiết kế và góc nhìn trước', 'warn'); return; }
  $('baseFile').click();
});
$('baseFile').addEventListener('change', () => run('nhập ảnh nền', async () => {
  const f = $('baseFile').files[0]; $('baseFile').value = ''; if (!f) return;
  const b64 = await new Promise((ok, err) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.onerror = err; fr.readAsDataURL(f); });
  await api(`/api/designs/${S.id}/base-image`, 'POST', { view: S.view, rev: S.data?.rev, imageBase64: b64, fit: $('baseFit').value });
  await load();
}));
$('baseClear').addEventListener('click', () => run('dùng lại ảnh mặc định', async () => {
  await api(`/api/designs/${S.id}/base-image`, 'POST', { view: S.view, rev: S.data?.rev, remove: true });
  await load();
}));
