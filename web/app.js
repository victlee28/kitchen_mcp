// Kitchen Editor — viewer three.js + panel sửa module. Mọi dữ liệu hiển thị qua textContent (không innerHTML).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { buildKitchen } from './scene-loader.js';

const $ = (id) => document.getElementById(id);
const state = { id: null, rev: null, spec: null, scene: null, selected: null, views: {}, qg: '' };

// ---------------- API
async function api(path, method = 'GET', body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = data.chiTiet ? ' — ' + data.chiTiet.map((x) => `${x.viTri}: ${x.loi}`).join('; ') : '';
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
  camera.position.set(...v.viTri); camera.fov = v.fovDoc; camera.updateProjectionMatrix();
  controls.target.set(...v.nhinVao); controls.update();
}
renderer.domElement.addEventListener('click', (ev) => {
  const r = renderer.domElement.getBoundingClientRect();
  pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(meshes, false).find((h) => h.object.userData.module && state.spec.module.some((m) => m.ma === h.object.userData.module));
  if (hit) selectModule(hit.object.userData.module);
});

// ---------------- dữ liệu thiết kế
async function loadDesigns(selectId) {
  const list = await api('/api/designs');
  const sel = $('designSelect'); sel.replaceChildren();
  for (const d of list) sel.append(el('option', { value: d.id, textContent: `${d.ten} · rev ${d.rev}` }));
  if (!list.length) sel.append(el('option', { value: '', textContent: '(chưa có thiết kế)' }));
  const id = selectId || (list[0] && list[0].id);
  if (id) { sel.value = id; await openDesign(id); }
}
async function openDesign(id, keepView = false) {
  const [d, sc, v, doc] = await Promise.all([api(`/api/designs/${id}`), api(`/api/designs/${id}/scene`), api(`/api/designs/${id}/validate${state.qg ? `?quocGia=${state.qg}` : ''}`),
    api(`/api/designs/${id}/threejs${state.qg ? `?quocGia=${state.qg}` : ''}`)]);
  Object.assign(state, { id, rev: d.rev, spec: d.spec, scene: sc, views: sc.views });
  $('revInfo').textContent = `rev ${d.rev}`;
  buildScene(doc); state.doc = doc;
  const vs = $('viewSelect'); const prev = vs.value; vs.replaceChildren();
  for (const [k, g] of Object.entries(sc.views)) vs.append(el('option', { value: k, textContent: g.ten || k }));
  if (keepView && sc.views[prev]) vs.value = prev; else applyView(vs.value);
  renderIssues(v); renderModuleList(); syncMoldingPanel();
  if (state.selected && !d.spec.module.some((m) => m.ma === state.selected)) state.selected = null;
  if (state.selected) selectModule(state.selected); else $('moduleForm').hidden = true;
  $('openRender').href = `render.html?design=${encodeURIComponent(id)}`;
  syncAiExport().catch((e) => setStatus('Xuất JSON cho AI lỗi: ' + e.message, 'warn'));
  window.dispatchEvent(new CustomEvent('design-opened', { detail: { id, rev: d.rev } }));
}
async function afterChange(res) {
  await loadDesigns(res.id);
  await openDesign(res.id, true);
}
function renderIssues(v) {
  const ul = $('issues'); ul.replaceChildren();
  ul.append(el('li', { class: 'muted' }, `Áp tiêu chuẩn: ${v.quocGia || v.khuVuc || 'toàn cầu (chưa chọn quốc gia)'}`));
  ul.append(el('li', { class: v.hopLe ? 'ok' : 'warn' }, v.hopLe ? `Hợp lệ · ${v.dem.warning} cảnh báo · ${v.dem.info} ghi chú` : `${v.dem.error} lỗi · ${v.dem.warning} cảnh báo`));
  for (const i of v.issues) {
    const li = el('li', { class: 'issue ' + i.mucDo }, el('b', {}, `[${i.mucDo}] ${i.quyTac}`), ' ', i.noiDung,
      i.theo ? el('small', { class: 'muted' }, ` — ${i.theo}`) : '');
    if (i.module.length) li.addEventListener('click', () => { if (state.spec.module.some((m) => m.ma === i.module[0])) selectModule(i.module[0]); });
    if (i.hanhDong?.length) {  // nút chọn cách xử lý (vd phào vượt trần: hạ đỉnh tủ / để nguyên)
      const row = el('div', { class: 'actions' });
      for (const a of i.hanhDong) {
        row.append(el('button', { type: 'button', textContent: a.nhan, onclick: (ev) => { ev.stopPropagation();
          run(a.nhan, async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST', { baseRev: state.rev, op: a.op }))); } }));
      }
      li.append(row);
    }
    ul.append(li);
  }
}
function renderModuleList() {
  const ul = $('moduleList'); ul.replaceChildren();
  const order = { sau: 0, goc: 1, phai: 2, trai: 3 };
  const mods = [...state.spec.module].sort((a, b) => (order[a.tuong] - order[b.tuong]) || (a.y - b.y) || ((a.tu || 0) - (b.tu || 0)));
  for (const m of mods) {
    const li = el('li', { class: m.ma === state.selected ? 'sel' : '', onclick: () => selectModule(m.ma) },
      el('b', {}, m.ma), ` ${m.loai} · ${m.tuong} · ${m.tu ?? 0}+${m.rong ?? m.canhSau}`);
    ul.append(li);
  }
}
const FIELDS = [['loai', 'text'], ['tuong', 'text'], ['tu', 'number'], ['rong', 'number'], ['y', 'number'], ['cao', 'number'], ['sau', 'number'], ['gocKhuat', 'number'], ['tamHong', 'number']];
function selectModule(ma) {
  state.selected = ma; highlight(); renderModuleList();
  const m = state.spec.module.find((x) => x.ma === ma); if (!m) return;
  const f = $('moduleForm'); f.hidden = false;
  $('formTitle').textContent = `${m.ma} — ${m.ten || m.loai}`;
  const box = $('formFields'); box.replaceChildren();
  for (const [k, type] of FIELDS) {
    box.append(el('label', {}, k, el('input', { name: k, type, value: m[k] ?? '', step: type === 'number' ? '10' : undefined })));
  }
  f.elements.canh.value = (m.canh || []).join(', ');
}
$('moduleForm').addEventListener('submit', (ev) => {
  ev.preventDefault();
  const f = ev.target; const m = state.spec.module.find((x) => x.ma === state.selected);
  const thayDoi = {};
  for (const [k, type] of FIELDS) {
    const raw = f.elements[k].value;
    const val = type === 'number' ? (raw === '' ? undefined : Number(raw)) : raw;
    if (val !== undefined && val !== (m[k] ?? (type === 'number' ? 0 : ''))) thayDoi[k] = val;
  }
  const canh = f.elements.canh.value.split(',').map((s) => s.trim()).filter(Boolean).map(Number);
  if (canh.join() !== (m.canh || []).join()) thayDoi.canh = canh;
  if (!Object.keys(thayDoi).length) return setStatus('Không có thay đổi');
  run(`sửa ${m.ma}`, async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
    { baseRev: state.rev, op: { op: 'update', ma: m.ma, thayDoi, donDay: f.elements.donDay.checked } })));
});
$('addAfter').addEventListener('click', () => {
  const m = state.spec.module.find((x) => x.ma === state.selected); if (!m) return;
  const rong = Number(prompt('Bề rộng tủ mới (mm)', '600')); if (!rong) return;
  run('thêm tủ', async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
    { baseRev: state.rev, op: { op: 'add', sauModule: m.ma, module: { rong, canh: rong >= 600 ? [rong / 2, rong / 2] : [rong] }, donDay: true } })));
});
$('removeModule').addEventListener('click', () => {
  const ma = state.selected; if (!ma) return;
  run(`xóa ${ma}`, async () => { state.selected = null; await afterChange(await api(`/api/designs/${state.id}/ops`, 'POST', { baseRev: state.rev, op: { op: 'remove', ma, donDay: true } })); });
});
$('undo').addEventListener('click', () => {
  if (!state.id || state.rev <= 1) return setStatus('Không còn bản trước');
  run('hoàn tác', async () => afterChange(await api(`/api/designs/${state.id}/revert`, 'POST', { baseRev: state.rev, rev: state.rev - 1 })));
});

// ---------------- tạo / nhập / xuất
$('fromPrompt').addEventListener('click', () => {
  const p = $('prompt').value.trim(); if (!p) return setStatus('Hãy nhập mô tả', 'warn');
  run('tạo từ mô tả', async () => { const r = await api('/api/designs', 'POST', { prompt: p }); state.selected = null; await loadDesigns(r.id); });
});
$('fromTemplate').addEventListener('click', () => {
  const mau = { quocGia: state.qg || null, hinh: $('mHinh').value, daiTuongSau: Number($('mSau').value), dinhTu: Number($('mDinh').value), tuLanh: $('mTuLanh').checked, tuNoc: $('mNoc').checked, phongCach: $('mStyle').value };
  if (mau.hinh === 'L') mau.daiTuongPhai = Number($('mPhai').value);
  run('tạo từ mẫu', async () => { const r = await api('/api/designs', 'POST', { mau, ten: `Bếp chữ ${mau.hinh}` }); state.selected = null; await loadDesigns(r.id); });
});
$('importFile').addEventListener('change', (e) => {
  const file = e.target.files[0]; if (!file) return;
  run('nhập spec', async () => { const spec = JSON.parse(await file.text()); const r = await api('/api/designs', 'POST', { spec }); await loadDesigns(r.id); });
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
async function doRender(views) {
  const res = await api(`/api/designs/${state.id}/render`, 'POST', { rev: state.rev, views });
  const box = $('renders'); box.replaceChildren();
  for (const [k, v] of Object.entries(res.views)) {
    const fig = el('figure', {}, el('figcaption', {}, `${state.views[k]?.ten || k} · rev ${res.rev}`));
    for (const f of ['lines', 'depth', 'normal', 'seg_module']) {
      const url = `${v.url}${f}.png?t=${Date.now()}`;
      fig.append(el('a', { href: url, target: '_blank', title: f }, el('img', { src: url, alt: f, loading: 'lazy' })));
    }
    box.append(fig);
  }
}
$('renderOne').addEventListener('click', () => state.id && run('render', () => doRender([$('viewSelect').value])));
$('renderAll').addEventListener('click', () => state.id && run('render tất cả góc', () => doRender(null)));

$('qgSelect').addEventListener('change', (e) => { state.qg = e.target.value; if (state.id) run('kiểm tra theo tiêu chuẩn', () => openDesign(state.id, true)); });
async function loadRegions() {
  const r = await api('/api/regions'); const sel = $('qgSelect');
  for (const [code, q] of Object.entries(r.quocGia)) sel.append(el('option', { value: code, textContent: `${q.ten} (${code})` }));
}
// ---------------- phong cách & phào
let profiles = {};
async function loadProfiles() {
  profiles = await api('/api/molding-profiles');
  for (const [sel, kieu] of [['pCrownProf', 'crown'], ['pBaseProf', 'base']]) {
    $(sel).replaceChildren(...Object.values(profiles).filter((p) => p.kieu === kieu).map((p) => el('option', { value: p.ma, textContent: `${p.ten} (${p.cao}×${p.nho})` })));
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
  const crown = ms.find((m) => m.kieu === 'crown'), base = ms.find((m) => m.kieu === 'base');
  $('pStyle').value = state.spec.phongCach || 'Modern';
  $('pCrown').checked = !!crown?.bat; $('pBase').checked = !!base?.bat;
  if (crown) $('pCrownProf').value = crown.profile; if (base) $('pBaseProf').value = base.profile;
  if (crown || base) $('pEnd').value = (crown || base).dauHo; drawProfile();
}
$('pStyle').addEventListener('change', () => { const c = ['Classic', 'Neoclassical', 'Transitional'].includes($('pStyle').value); $('pCrown').checked = c; $('pBase').checked = c; });
$('pApply').addEventListener('click', () => {
  if (!state.id) return;
  const old = Object.fromEntries((state.spec.moldings || []).map((m) => [m.ma, m]));
  const moldings = [];
  if ($('pCrown').checked) moldings.push({ ...(old['phao-noc'] || {}), ma: 'phao-noc', kieu: 'crown', profile: $('pCrownProf').value, dauHo: $('pEnd').value, bat: true });
  if ($('pBase').checked) moldings.push({ ...(old['phao-chan'] || {}), ma: 'phao-chan', kieu: 'base', profile: $('pBaseProf').value, dauHo: $('pEnd').value, bat: true });
  run('áp dụng phào', async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
    { baseRev: state.rev, op: { op: 'phao-dat', moldings, phongCach: $('pStyle').value } })));
});

// ---------------- xuất JSON cuối cùng cho AI tạo ảnh
const aiDone = {};  // id -> rev đã tự xuất trong phiên này
try { const v = localStorage.getItem('aiAuto'); if (v !== null) $('aiAuto').checked = v === '1'; } catch { /* không có storage */ }
$('aiAuto').addEventListener('change', (e) => { try { localStorage.setItem('aiAuto', e.target.checked ? '1' : '0'); } catch { /* bỏ qua */ } if (e.target.checked) syncAiExport(true).catch(console.error); });
function aiInfo(res) {
  const t = new Date(res.taoLuc).toLocaleTimeString();
  $('aiInfo').textContent = `Bản cuối: rev ${res.rev} · ${res.views.length} góc · xuất lúc ${t}${res.kemAnh ? ' · kèm ảnh' : ''}`;
  const box = $('aiLinks'); box.replaceChildren();
  for (const [k, u] of Object.entries(res.url || {})) if (u) box.append(el('a', { href: u, target: '_blank', textContent: k === 'zip' ? 'ai-package.zip' : 'ai-request.json' }));
}
async function syncAiExport(force = false) {
  if (!state.id) return;
  const light = $('aiLight').value;
  $('aiJson').href = `/api/designs/${state.id}/ai-export?nhungAnh=1&anhSang=${light}`;  // một file: nhúng sẵn ảnh nên gửi của từng góc
  $('aiJson').setAttribute('download', `${state.id}-rev${state.rev}-gui-ai.json`);
  if (!$('aiAuto').checked || (!force && aiDone[state.id] === state.rev)) {
    if (aiDone[state.id] !== state.rev) $('aiInfo').textContent = `Thiết kế đang ở rev ${state.rev} — chưa xuất bản này`;
    return;
  }
  const res = await api(`/api/designs/${state.id}/ai-export`, 'POST', { rev: state.rev, anhSang: light });
  aiDone[state.id] = res.rev; aiInfo(res);
}
$('aiLight').addEventListener('change', () => run('xuất lại cho AI', () => syncAiExport(true)));
$('aiZip').addEventListener('click', () => state.id && run('xuất gói kèm ảnh cho AI', async () => {
  const res = await api(`/api/designs/${state.id}/ai-export`, 'POST', { rev: state.rev, kemAnh: true, anhSang: $('aiLight').value });
  aiDone[state.id] = res.rev; aiInfo(res);
  if (res.url?.zip) el('a', { href: res.url.zip, download: `${state.id}-rev${res.rev}-ai-package.zip` }).click();
}));

$('aiView').addEventListener('click', () => {
  if (!state.id) return;
  const base = `/api/designs/${state.id}/ai-export`, tag = `${state.id} · rev ${state.rev}`, L = `anhSang=${$('aiLight').value}`;
  const variants = [
    { label: 'Rút gọn', hint: 'Bản gửi AI: chỉ dẫn + ảnh đính kèm', url: `${base}?nhungAnh=1&${L}`, name: `${state.id}-rev${state.rev}-gui-ai.json`, title: `JSON gửi AI (rút gọn, kèm ảnh) · ${tag}` },
    { label: 'Đầy đủ', hint: 'Bản kiểm tra, không gửi AI', url: `${base}?dang=day-du&${L}`, name: `${state.id}-rev${state.rev}-ai-request.json`, title: `JSON đầy đủ (cảnh three.js, vật liệu, camera) · ${tag}` },
  ];
  run('mở JSON cuối cùng', () => window.kitchenJson.showJsonUrl(variants[0].title, variants[0].url, variants[0].name, variants));
});

// cầu nối cho imgedit.js (tab "Sửa ảnh theo lớp")
window.kitchen = { state, api, run, el, setStatus, reload: (id) => afterChange({ id }) };
$('viewSelect').addEventListener('change', (e) => window.dispatchEvent(new CustomEvent('view-changed', { detail: e.target.value })));

run('tải', async () => { await loadRegions(); await loadProfiles(); await loadDesigns(); });
