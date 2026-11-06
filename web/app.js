// Kitchen Editor — viewer three.js + panel sửa module. Mọi dữ liệu hiển thị qua textContent (không innerHTML).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { buildKitchen } from './scene-loader.js';
import { createStructureSelector } from './structure-select.js';

const $ = (id) => document.getElementById(id);
const state = { id: null, rev: null, spec: null, scene: null, selected: null, views: {}, qg: '' };

// ---------------- API
async function api(path, method = 'GET', body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = data.part ? ' — ' + data.part.map((x) => `${x.position}: ${x.errors}`).join('; ') : '';
    throw new Error((data.error || `HTTP ${r.status}`) + detail);
  }
  return data;
}
function setStatus(msg, kind = '') { const s = $('status'); s.textContent = msg; s.className = 'status ' + kind; }
async function run(label, fn) {
  setStatus(label + '…');
  try { await fn(); setStatus('Xong: ' + label, 'ok'); } catch (e) { console.error(e); setStatus(e.message, 'warn'); }
}
function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n[k] = v;
  }
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}

// ---------------- 3D
const viewport = $('viewport');
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(devicePixelRatio);
viewport.append(renderer.domElement);
const scene3 = new THREE.Scene();
scene3.background = new THREE.Color(0xf4f1eb);
// môi trường phòng cho phản xạ: vật liệu kim loại (inox tủ lạnh, tay nắm) không bị đen
scene3.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
if ('environmentIntensity' in scene3) scene3.environmentIntensity = 0.5;
// đèn lấy từ tài liệu three.js (doc.lighting)
renderer.shadowMap.enabled = true;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 100);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
const root = new THREE.Group(); scene3.add(root);
const edgeMat = new THREE.LineBasicMaterial({ color: 0x3a3630 });
const raycaster = new THREE.Raycaster(); const pointer = new THREE.Vector2();
let meshes = [];
const structSel = createStructureSelector({ THREE, els: { section: $('fpElements'), kinds: $('fpKinds'), list: $('fpList'), detail: $('fpDetail'), actions: $('fpActions'),
  hide: $('fpHide'), isolate: $('fpIsolate'), showAll: $('fpShowAll') },
  onSelect: () => { if (state.selected) { state.selected = null; highlight(); renderModuleList(); } $('moduleForm').hidden = true; } });

function resize() {
  const w = viewport.clientWidth, h = viewport.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewport);
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene3, camera); })();

function buildScene(doc) {
  // dựng từ tài liệu theo "Complete Kitchen Three.js Scene Schema" (/api/designs/<id>/threejs)
  root.clear();
  const k = buildKitchen(doc, THREE, { RectAreaLightUniformsLib });
  root.add(k.root);
  meshes = k.pickables;
  structSel.setScene(k.structures, k.structurePickables);
  highlight();
}
const selMats = new WeakMap();
function highlight() {
  for (const m of meshes) {
    const sel = state.selected && m.userData.module === state.selected;
    if (!m.userData.baseMat) m.userData.baseMat = m.material;
    if (sel) {
      if (!selMats.has(m.userData.baseMat)) {
        const c = m.userData.baseMat.clone(); c.emissive = new THREE.Color(0x2f6bff); c.emissiveIntensity = 0.35; selMats.set(m.userData.baseMat, c);
      }
      m.material = selMats.get(m.userData.baseMat);
    } else m.material = m.userData.baseMat;
  }
}
function applyView(key) {
  const v = state.views[key]; if (!v) return;
  camera.position.set(...v.position); camera.fov = v.verticalFov; camera.updateProjectionMatrix();
  controls.target.set(...v.lookAt); controls.update();
}
renderer.domElement.addEventListener('click', (ev) => {
  const r = renderer.domElement.getBoundingClientRect();
  pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  // nearest thing under the pointer wins: a cabinet module or a visible floorplan element
  const hit = raycaster.intersectObjects([...meshes, ...structSel.pickables()], false)
    .find((h) => h.object.userData.structureId || (h.object.userData.module && state.spec.module.some((m) => m.id === h.object.userData.module)));
  if (hit?.object.userData.structureId) structSel.select(hit.object.userData.structureId);
  else if (hit) { structSel.clear(); selectModule(hit.object.userData.module); }
  else structSel.clear();
});
window.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || '')) structSel.clear(); });

// ---------------- dữ liệu thiết kế
async function loadDesigns(selectId) {
  const list = await api('/api/designs');
  const sel = $('designSelect'); sel.replaceChildren();
  for (const d of list) sel.append(el('option', { value: d.id, textContent: `${d.name} · rev ${d.rev}` }));
  if (!list.length) sel.append(el('option', { value: '', textContent: '(chưa có thiết kế)' }));
  const id = selectId || (list[0] && list[0].id);
  if (id) { sel.value = id; await openDesign(id); }
}
async function openDesign(id, keepView = false) {
  const [d, sc, v, doc] = await Promise.all([api(`/api/designs/${id}`), api(`/api/designs/${id}/scene`), api(`/api/designs/${id}/validate${state.qg ? `?country=${state.qg}` : ''}`),
    api(`/api/designs/${id}/threejs${state.qg ? `?country=${state.qg}` : ''}`)]);
  Object.assign(state, { id, rev: d.rev, spec: d.spec, scene: sc, views: sc.views });
  $('revInfo').textContent = `rev ${d.rev}`;
  buildScene(doc); state.doc = doc;
  const vs = $('viewSelect'); const prev = vs.value; vs.replaceChildren();
  for (const [k, g] of Object.entries(sc.views)) vs.append(el('option', { value: k, textContent: g.name || k }));
  if (keepView && sc.views[prev]) vs.value = prev; else applyView(vs.value);
  renderIssues(v); renderModuleList(); syncMoldingPanel();
  if (state.selected && !d.spec.module.some((m) => m.id === state.selected)) state.selected = null;
  if (state.selected) selectModule(state.selected); else $('moduleForm').hidden = true;
  $('openRender').href = `render.html?design=${encodeURIComponent(id)}`;
  refreshViewSync().catch((e) => console.warn('view-status', e));
  syncAiExport().catch((e) => setStatus('Xuất JSON cho AI lỗi: ' + e.message, 'warn'));
  window.dispatchEvent(new CustomEvent('design-opened', { detail: { id, rev: d.rev } }));
}
const SYNC_TEXT = { current: 'approved image up to date', 'stale-appearance': 'approved image out of date (material changed)', 'stale-geometry': 'approved image belongs to older geometry', unknown: 'approved image: cannot tell (no snapshot)' };
async function refreshViewSync() {
  const id = state.id; const ul = $('viewSync'); ul.replaceChildren(); $('regenStale').hidden = true;
  const { views } = await api(`/api/designs/${id}/view-status`);
  if (id !== state.id) return;
  let stale = 0;
  for (const [k, v] of Object.entries(views)) {
    if (v.status === 'none') continue;
    if (v.status === 'stale-appearance') stale++;
    const changed = (v.changed || []).slice(0, 3).map((c) => `${c.layer}: ${c.was ?? '?'} → ${c.now ?? '?'}`).join('; ');
    ul.appendChild(el('li', {}, `${state.views[k]?.name || k}: ${SYNC_TEXT[v.status] || v.status}${changed ? ' — ' + changed : ''}`));
  }
  $('regenStale').hidden = !stale;
}
$('regenStale').addEventListener('click', () => state.id && run('prepare images for stale views', async () => {
  const r = await api(`/api/designs/${state.id}/regenerate-stale`, 'POST', {});
  setStatus(`${r.jobs.length} review job(s) prepared (not sent)${r.skipped.length ? `, ${r.skipped.length} skipped` : ''}`);
  await refreshViewSync();
}));
async function afterChange(res) {
  await loadDesigns(res.id);
  await openDesign(res.id, true);
}
function renderIssues(v) {
  const ul = $('issues'); ul.replaceChildren();
  ul.append(el('li', { class: 'muted' }, `Áp tiêu chuẩn: ${v.country || v.region || 'toàn cầu (chưa chọn quốc gia)'}`));
  ul.append(el('li', { class: v.valid ? 'ok' : 'warn' }, v.valid ? `Hợp lệ · ${v.dem.warning} cảnh báo · ${v.dem.info} ghi chú` : `${v.dem.error} lỗi · ${v.dem.warning} cảnh báo`));
  for (const i of v.issues) {
    const li = el('li', { class: 'issue ' + i.severity }, el('b', {}, `[${i.severity}] ${i.rule}`), ' ', i.content,
      i.theo ? el('small', { class: 'muted' }, ` — ${i.theo}`) : '');
    if (i.module.length) li.addEventListener('click', () => { if (state.spec.module.some((m) => m.id === i.module[0])) selectModule(i.module[0]); });
    if (i.action?.length) {  // nút chọn cách xử lý (vd phào vượt trần: hạ đỉnh tủ / để nguyên)
      const row = el('div', { class: 'actions' });
      for (const a of i.action) {
        row.append(el('button', { type: 'button', textContent: a.label, onclick: (ev) => { ev.stopPropagation();
          run(a.label, async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST', { baseRev: state.rev, op: a.op }))); } }));
      }
      li.append(row);
    }
    ul.append(li);
  }
}
function renderModuleList() {
  const ul = $('moduleList'); ul.replaceChildren();
  const order = { back: 0, corner: 1, right: 2, left: 3, island: 4 };
  const mods = [...state.spec.module].sort((a, b) => (order[a.wall] - order[b.wall]) || (a.y - b.y) || ((a.fromCorner || 0) - (b.fromCorner || 0)));
  for (const m of mods) {
    const li = el('li', { class: m.id === state.selected ? 'sel' : '', onclick: () => selectModule(m.id) },
      el('b', {}, m.id), ` ${m.type} · ${m.wall} · ${m.fromCorner ?? 0}+${m.width ?? m.backLength}`);
    ul.append(li);
  }
}
const FIELDS = [['type', 'text'], ['wall', 'text'], ['fromCorner', 'number'], ['width', 'number'], ['y', 'number'], ['tall', 'number'], ['back', 'number'], ['blindCorner', 'number'], ['endPanel', 'number']];
function selectModule(id) {
  state.selected = id; highlight(); renderModuleList();
  const m = state.spec.module.find((x) => x.id === id); if (!m) return;
  const f = $('moduleForm'); f.hidden = false;
  $('formTitle').textContent = `${m.id} — ${m.name || m.type}`;
  const box = $('formFields'); box.replaceChildren();
  for (const [k, type] of FIELDS) {
    box.append(el('label', {}, k, el('input', { name: k, type, value: m[k] ?? '', step: type === 'number' ? '10' : undefined })));
  }
  f.elements.doors.value = (m.doors || []).join(', ');
}
$('moduleForm').addEventListener('submit', (ev) => {
  ev.preventDefault();
  const f = ev.target; const m = state.spec.module.find((x) => x.id === state.selected);
  const changes = {};
  for (const [k, type] of FIELDS) {
    const raw = f.elements[k].value;
    const val = type === 'number' ? (raw === '' ? undefined : Number(raw)) : raw;
    if (val !== undefined && val !== (m[k] ?? (type === 'number' ? 0 : ''))) changes[k] = val;
  }
  const doors = f.elements.doors.value.split(',').map((s) => s.trim()).filter(Boolean).map(Number);
  if (doors.join() !== (m.doors || []).join()) changes.doors = doors;
  if (!Object.keys(changes).length) return setStatus('Không có thay đổi');
  run(`sửa ${m.id}`, async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
    { baseRev: state.rev, op: { op: 'update', id: m.id, changes, closeGap: f.elements.closeGap.checked } })));
});
$('addAfter').addEventListener('click', () => {
  const m = state.spec.module.find((x) => x.id === state.selected); if (!m) return;
  const width = Number(prompt('Bề rộng tủ mới (mm)', '600')); if (!width) return;
  run('thêm tủ', async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
    { baseRev: state.rev, op: { op: 'add', afterModule: m.id, module: { width, doors: width >= 600 ? [width / 2, width / 2] : [width] }, closeGap: true } })));
});
$('removeModule').addEventListener('click', () => {
  const id = state.selected; if (!id) return;
  run(`xóa ${id}`, async () => { state.selected = null; await afterChange(await api(`/api/designs/${state.id}/ops`, 'POST', { baseRev: state.rev, op: { op: 'remove', id, closeGap: true } })); });
});
$('undo').addEventListener('click', () => {
  if (!state.id || state.rev <= 1) return setStatus('Không còn bản trước');
  run('hoàn tác', async () => afterChange(await api(`/api/designs/${state.id}/revert`, 'POST', { baseRev: state.rev, rev: state.rev - 1 })));
});

// ---------------- tạo / nhập / xuất
// Bảng "đã hiểu gì từ mô tả": mỗi thuật ngữ kèm vùng áp, trường đích và trạng thái hỗ trợ (chữ qua textContent)
const STATUS_VI = { built: 'đã dựng', exported: 'ghi vào thiết kế/file 3D', 'ai-only': 'chỉ cho ảnh AI', unsupported: 'chưa hỗ trợ', ambiguous: 'chưa rõ' };
const SCOPE_VI = { base: 'tủ dưới', upper: 'tủ trên', tall: 'tủ cao', countertop: 'mặt bàn', wallTile: 'ốp tường', handle: 'tay nắm', floor: 'sàn', wall: 'tường', whole: 'toàn bếp', '?': 'chưa rõ' };
function showInterpretation(items) {
  const box = $('promptResult'); box.replaceChildren();
  box.hidden = !items.length; if (!items.length) return;
  const rows = items.map((i) => {
    const tr = document.createElement('tr'); tr.className = 'st-' + i.status;
    for (const text of [i.term || '—', i.canonical || '', (i.scope || []).map((s) => SCOPE_VI[s] || s).join(', '), STATUS_VI[i.status] || i.status, i.message || '']) {
      const td = document.createElement('td'); td.textContent = text; tr.append(td);
    }
    return tr;
  });
  const table = document.createElement('table');
  const head = document.createElement('tr');
  for (const h of ['Từ trong mô tả', 'Hiểu là', 'Áp cho', 'Trạng thái', 'Ghi chú']) { const th = document.createElement('th'); th.textContent = h; head.append(th); }
  table.append(head, ...rows);
  const title = document.createElement('p'); title.className = 'muted small'; title.textContent = 'Hệ thống đã hiểu mô tả như sau:';
  box.append(title, table);
}
$('fromPrompt').addEventListener('click', () => {
  const p = $('prompt').value.trim(); if (!p) return setStatus('Hãy nhập mô tả', 'warn');
  run('tạo từ mô tả', async () => {
    const r = await api('/api/designs', 'POST', { prompt: p }); state.selected = null; await loadDesigns(r.id);
    showInterpretation(r.analysis?.interpretation || []);
  });
});
$('fromTemplate').addEventListener('click', () => {
  const color = { country: state.qg || null, geometry_edit: $('mShape').value, backWallLength: Number($('mBack').value), cabinetTop: Number($('mTop').value), backsplashHeight: $('mBacksplash').value, fridge: $('mFridge').checked, loft: $('mLoft').checked, island: $('mIsland').checked, peninsula: $('mPeninsula').checked, openShelf: $('mOpenShelf').checked, style: $('mStyle').value };
  if (color.geometry_edit !== 'I') color.rightWallLength = Number($('mRight').value);
  if (color.geometry_edit === 'U') color.leftWallLength = Number($('mLeft').value);
  run('tạo từ mẫu', async () => { const r = await api('/api/designs', 'POST', { color, name: `Bếp chữ ${color.geometry_edit}` }); state.selected = null; await loadDesigns(r.id); });
});
$('importFile').addEventListener('change', (e) => {
  const file = e.target.files[0]; if (!file) return;
  run('nhập spec', async () => { const spec = JSON.parse(await file.text()); const r = await api('/api/designs', 'POST', { spec }); await loadDesigns(r.id); });
});
let pendingFloorplan = null;
function showFloorplanInfo(r) {
  const ul = $('fpInfo'); ul.replaceChildren();
  const add = (t) => ul.appendChild(el('li', {}, t));
  if (r.floorplan) {
    const f = r.floorplan;
    add(`${f.roomLabel || f.roomId}: ${f.width} x ${f.depth} mm, ${f.areaM2} m2, ${f.wallCount} walls`);
    if (f.outsideElements?.length) add(`Outside the room (ignored): ${f.outsideElements.join(', ')}`);
    if (f.unattachedOpenings?.length) add(`Doors/windows not attached to a wall: ${f.unattachedOpenings.join(', ')}`);
    for (const w of f.warnings || []) add(typeof w === 'string' ? w : `${w.code}: ${w.message}`);
  }
  if (r.binding) {
    add(`Kitchen back wall = room edge ${r.binding.back} (${r.binding.source}, score ${r.binding.score})`);
    for (const w of r.binding.warnings || []) add(w);
  }
}
async function importFloorplan(roomId) {
  const result = await api('/api/floorplans/import', 'POST', { floorplan: pendingFloorplan, roomId: roomId || undefined });
  showFloorplanInfo(result);
  await loadDesigns(result.id);
}
$('floorplanFile').addEventListener('change', (e) => {
  const file = e.target.files[0]; if (!file) return;
  run('import floorplan', async () => {
    pendingFloorplan = JSON.parse(await file.text());
    const { rooms } = await api('/api/floorplans/rooms', 'POST', { floorplan: pendingFloorplan });
    if (rooms.length > 1 || rooms.some((r) => r.kind === 'region')) {
      const sel = $('fpRoom'); sel.replaceChildren(...rooms.map((r) => el('option', { value: r.id }, `${r.kind === 'region' ? '[area] ' : ''}${r.label || r.id} (${r.id})`)));
      $('fpRoomRow').hidden = false; $('fpImport').hidden = false;
      setStatus(`The plan offers ${rooms.length} places to import (rooms and wall-bounded areas): choose one and import`);
      return;
    }
    $('fpRoomRow').hidden = true; $('fpImport').hidden = true;
    await importFloorplan(rooms[0]?.id);
  });
});
$('fpImport').addEventListener('click', () => run('import floorplan', () => importFloorplan($('fpRoom').value)));
$('fpBind').addEventListener('click', () => {
  if (!state.id) return;
  run('place kitchen', async () => { const r = await api(`/api/designs/${state.id}/floorplan-bind`, 'POST', { rev: state.rev }); showFloorplanInfo(r); await openDesign(state.id, true); });
});
$('exportSpec').addEventListener('click', () => {
  if (!state.spec) return;
  const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(state.spec, null, 2)], { type: 'application/json' })), download: `${state.id}-rev${state.rev}.json` });
  a.click();
});
$('exportThree').addEventListener('click', () => {
  if (!state.doc) return;
  const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(state.doc, null, 2)], { type: 'application/json' })), download: `${state.id}-rev${state.rev}.threejs.json` });
  a.click();
});
$('designSelect').addEventListener('change', (e) => e.target.value && run('mở thiết kế', () => { state.selected = null; return openDesign(e.target.value); }));
$('viewSelect').addEventListener('change', (e) => applyView(e.target.value));

// ---------------- render ảnh điều khiển
async function runRender(views) {
  const res = await api(`/api/designs/${state.id}/render`, 'POST', { rev: state.rev, views });
  const box = $('renders'); box.replaceChildren();
  for (const [k, v] of Object.entries(res.views)) {
    const fig = el('figure', {}, el('figcaption', {}, `${state.views[k]?.name || k} · rev ${res.rev}`));
    for (const f of ['lines', 'depth', 'normal', 'seg_module']) {
      const url = `${v.url}${f}.png?t=${Date.now()}`;
      fig.append(el('a', { href: url, target: '_blank', title: f }, el('img', { src: url, alt: f, loading: 'lazy' })));
    }
    box.append(fig);
  }
}
$('renderOne').addEventListener('click', () => state.id && run('render', () => runRender([$('viewSelect').value])));
$('renderAll').addEventListener('click', () => state.id && run('render tất cả góc', () => runRender(null)));

$('qgSelect').addEventListener('change', (e) => { state.qg = e.target.value; if (state.id) run('kiểm tra theo tiêu chuẩn', () => openDesign(state.id, true)); });
async function loadRegions() {
  const r = await api('/api/regions'); const sel = $('qgSelect');
  for (const [code, q] of Object.entries(r.country)) sel.append(el('option', { value: code, textContent: `${q.name} (${code})` }));
}
// ---------------- phong cách & phào
let profiles = {};
async function loadProfiles() {
  profiles = await api('/api/molding-profiles');
  for (const [sel, variant] of [['pCrownProf', 'crown'], ['pBaseProf', 'base']]) {
    $(sel).replaceChildren(...Object.values(profiles).filter((p) => p.variant === variant).map((p) => el('option', { value: p.id, textContent: `${p.name} (${p.height}×${p.overhang})` })));
  }
  $('pCrownProf').value = 'classic-crown-layered'; $('pBaseProf').value = 'classic-base';
  $('pCrownProf').addEventListener('change', drawProfile); drawProfile();
}
function drawProfile() {
  const p = profiles[$('pCrownProf').value]; const cv = $('pPreview'); const g = cv.getContext('2d');
  g.clearRect(0, 0, cv.width, cv.height); if (!p) return;
  const us = p.points.map((q) => q[0]), vs = p.points.map((q) => q[1]);
  const k = Math.min((cv.width - 10) / (Math.max(...us) - Math.min(...us)), (cv.height - 10) / (Math.max(...vs) - Math.min(...vs)));
  g.beginPath();
  p.points.forEach(([u, v], i) => { const x = 5 + (u - Math.min(...us)) * k, y = cv.height - 5 - (v - Math.min(...vs)) * k; i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.closePath(); g.fillStyle = '#c8a273'; g.fill(); g.strokeStyle = '#3a3630'; g.stroke();
}
function syncMoldingPanel() {
  const ms = state.spec.moldings || [];
  const crown = ms.find((m) => m.variant === 'crown'), base = ms.find((m) => m.variant === 'base');
  $('pStyle').value = state.spec.style || 'Modern';
  $('pCrown').checked = !!crown?.enabled; $('pBase').checked = !!base?.enabled;
  if (crown) $('pCrownProf').value = crown.profile; if (base) $('pBaseProf').value = base.profile;
  if (crown || base) $('pEnd').value = (crown || base).openEnd; drawProfile();
}
$('pStyle').addEventListener('change', () => { const c = ['Classic', 'Neoclassical', 'Transitional'].includes($('pStyle').value); $('pCrown').checked = c; $('pBase').checked = c; });
$('pApply').addEventListener('click', () => {
  if (!state.id) return;
  const old = Object.fromEntries((state.spec.moldings || []).map((m) => [m.id, m]));
  const moldings = [];
  if ($('pCrown').checked) moldings.push({ ...(old['crown-molding'] || {}), id: 'crown-molding', variant: 'crown', profile: $('pCrownProf').value, openEnd: $('pEnd').value, enabled: true });
  if ($('pBase').checked) moldings.push({ ...(old['base-molding'] || {}), id: 'base-molding', variant: 'base', profile: $('pBaseProf').value, openEnd: $('pEnd').value, enabled: true });
  run('áp dụng phào', async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
    { baseRev: state.rev, op: { op: 'set-moldings', moldings, style: $('pStyle').value } })));
});

// ---------------- xuất JSON cuối cùng cho AI tạo ảnh
const aiDone = {};  // id -> rev đã tự xuất trong phiên này
try { const v = localStorage.getItem('aiAuto'); if (v !== null) $('aiAuto').checked = v === '1'; } catch { /* không có storage */ }
$('aiAuto').addEventListener('change', (e) => { try { localStorage.setItem('aiAuto', e.target.checked ? '1' : '0'); } catch { /* bỏ qua */ } if (e.target.checked) syncAiExport(true).catch(console.error); });
function aiInfo(res) {
  const t = new Date(res.taoLuc).toLocaleTimeString();
  $('aiInfo').textContent = `Bản cuối: rev ${res.rev} · ${res.views.length} góc · xuất lúc ${t}${res.withImage ? ' · kèm ảnh' : ''}`;
  const box = $('aiLinks'); box.replaceChildren();
  for (const [k, u] of Object.entries(res.url || {})) if (u) box.append(el('a', { href: u, target: '_blank', textContent: k === 'zip' ? 'ai-package.zip' : 'ai-request.json' }));
}
async function syncAiExport(force = false) {
  if (!state.id) return;
  const light = $('aiLight').value;
  $('aiJson').href = `/api/designs/${state.id}/ai-export?embedImages=1&lighting=${light}`;  // một file: nhúng sẵn ảnh nên gửi của từng góc
  $('aiJson').setAttribute('download', `${state.id}-rev${state.rev}-ai-request-short.json`);
  if (!$('aiAuto').checked || (!force && aiDone[state.id] === state.rev)) {
    if (aiDone[state.id] !== state.rev) $('aiInfo').textContent = `Thiết kế đang ở rev ${state.rev} — chưa xuất bản này`;
    return;
  }
  const res = await api(`/api/designs/${state.id}/ai-export`, 'POST', { rev: state.rev, lighting: light });
  aiDone[state.id] = res.rev; aiInfo(res);
}
$('aiLight').addEventListener('change', () => run('xuất lại cho AI', () => syncAiExport(true)));
$('aiZip').addEventListener('click', () => state.id && run('xuất gói kèm ảnh cho AI', async () => {
  const res = await api(`/api/designs/${state.id}/ai-export`, 'POST', { rev: state.rev, withImage: true, lighting: $('aiLight').value });
  aiDone[state.id] = res.rev; aiInfo(res);
  if (res.url?.zip) el('a', { href: res.url.zip, download: `${state.id}-rev${res.rev}-ai-package.zip` }).click();
}));

$('aiView').addEventListener('click', () => {
  if (!state.id) return;
  const base = `/api/designs/${state.id}/ai-export`, tag = `${state.id} · rev ${state.rev}`, L = `anhSang=${$('aiLight').value}`;
  const variants = [
    { label: 'Rút gọn', hint: 'Bản gửi AI: chỉ dẫn + ảnh đính kèm', url: `${base}?embedImages=1&${L}`, name: `${state.id}-rev${state.rev}-ai-request-short.json`, title: `JSON gửi AI (rút gọn, kèm ảnh) · ${tag}` },
    { label: 'Đầy đủ', hint: 'Bản kiểm tra, không gửi AI', url: `${base}?format=day-du&${L}`, name: `${state.id}-rev${state.rev}-ai-request.json`, title: `JSON đầy đủ (cảnh three.js, vật liệu, camera) · ${tag}` },
  ];
  run('mở JSON cuối cùng', () => window.kitchenJson.showJsonUrl(variants[0].title, variants[0].url, variants[0].name, variants));
});

// cầu nối cho imgedit.js (tab "Sửa ảnh theo lớp")
window.kitchen = { state, api, run, el, setStatus, reload: (id) => afterChange({ id }) };
$('viewSelect').addEventListener('change', (e) => window.dispatchEvent(new CustomEvent('view-changed', { detail: e.target.value })));

run('tải', async () => { await loadRegions(); await loadProfiles(); await loadDesigns(); });
