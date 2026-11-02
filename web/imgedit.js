// Tab "Sửa ảnh theo lớp": chọn chi tiết trên ảnh (instance mask phía máy chủ), tạo job, so sánh trước/sau, duyệt.
// Không phụ thuộc three.js: vẫn chạy khi CDN three.js lỗi. Mọi chữ hiển thị qua textContent.
const $ = (id) => document.getElementById(id);
const S = { id: null, view: null, data: null, layer: null, job: null, jobs: [], poll: null, maskImg: null, tasks: [], maskCache: {} };
const PALETTE = [[255, 0, 0], [0, 200, 0], [0, 80, 255], [255, 220, 0], [255, 0, 255], [0, 230, 230], [255, 140, 0], [140, 60, 200]];
const MAX_TASKS = 8;

async function api(path, method = 'GET', body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else if (v !== undefined) n[k] = v;
  }
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
function status(msg, kind = '') { const s = $('status'); s.textContent = msg; s.className = 'status ' + kind; }
async function run(label, fn) {
  status(label + '…');
  try { await fn(); status('Xong: ' + label, 'ok'); } catch (e) { console.error(e); status(e.message, 'warn'); }
}
const bust = (u) => u && `${u}${u.includes('?') ? '&' : '?'}t=${Date.now()}`;

// ---------------- tab
function showTab(img) {
  $('tab3d').classList.toggle('on', !img); $('tabImg').classList.toggle('on', img);
  $('tab3d').setAttribute('aria-selected', String(!img)); $('tabImg').setAttribute('aria-selected', String(img));
  $('pane3d').hidden = img; $('paneImg').hidden = !img; $('bar3d').hidden = img; $('barImg').hidden = !img;
  if (img) run('mở ảnh', load);
}
$('tab3d').addEventListener('click', () => showTab(false));
$('tabImg').addEventListener('click', () => showTab(true));
const active = () => !$('paneImg').hidden;

// ---------------- tải layer + ảnh gốc
async function load() {
  S.id = $('designSelect').value; S.view = $('viewSelect').value;
  if (!S.id || !S.view) return;
  const d = await api(`/api/designs/${S.id}/layers?view=${encodeURIComponent(S.view)}`);
  S.data = d;
  hinhForm();
  $('imgInfo').textContent = `rev ${d.rev} · ${d.width}×${d.height} · renderKey ${d.renderKey} · ảnh gốc: ${d.anhGoc.loai === 'job' ? d.anhGoc.jobId : d.anhGoc.loai}`;
  $('imgBase').src = bust(d.anhGoc.url);
  $('imgAfter').hidden = true; $('cmpWrap').hidden = true;
  const sel = $('layerSelect'); const prev = S.layer; sel.replaceChildren();
  const groups = d.layers.filter((x) => x.kieu === 'nhom'), parts = d.layers.filter((x) => x.kieu === 'chi-tiet');
  for (const [label, xs] of [['Nhóm', groups], ['Chi tiết', parts]]) {
    const og = el('optgroup', { label });
    for (const x of xs) og.append(el('option', { value: x.id, textContent: `${x.ten} · ${x.id}` }));
    sel.append(og);
  }
  if (prev && d.layers.some((x) => x.id === prev)) sel.value = prev;
  await selectLayer(sel.value, []);
  await loadJobs();
}
async function selectLayer(id, alts) {
  S.layer = id; $('layerSelect').value = id;
  const x = S.data?.layers.find((l) => l.id === id);
  if (x?.module && [...$('hMa').options].some((o) => o.value === x.module)) $('hMa').value = x.module;  // bấm vào tủ -> chọn sẵn cho sửa hình
  $('layerInfo').textContent = x ? `${x.semanticClass} · vật liệu: ${x.vatLieu || '—'} · ${x.pixels} px` +
    (x.suaThietKe ? ` · sửa thiết kế áp cho ${x.suaThietKe}` : ' · chỉ sửa được ảnh (thử nhanh)') : '';
  const box = $('layerAlt'); box.replaceChildren();
  for (const a of alts) box.append(el('button', { type: 'button', class: a === id ? 'on' : '', textContent: a, onclick: () => selectLayer(a, alts) }));
  await drawMask();
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
      `${t.targetLayer}${t.vatLieu ? ' → ' + t.vatLieu : ''}${t.instruction ? ' · ' + t.instruction : ''}`,
      el('button', { type: 'button', textContent: 'xóa', onclick: () => { S.tasks.splice(k, 1); renderTasks(); drawMask().catch(console.error); } })));
  });
  $('tClear').hidden = !S.tasks.length;
  $('jCreate').textContent = S.tasks.length ? `Tạo job sửa (${S.tasks.length} việc)` : 'Tạo job sửa';
}
$('tAdd').addEventListener('click', () => run('thêm việc', async () => {
  if (!S.layer) throw new Error('Hãy chọn layer trước');
  if (S.tasks.length >= MAX_TASKS) throw new Error(`Tối đa ${MAX_TASKS} việc mỗi job`);
  if (S.tasks.some((t) => t.targetLayer === S.layer)) throw new Error('Layer này đã có trong danh sách');
  const vat = $('jVat').value.trim(), instr = $('jInstr').value.trim();
  if (!vat && !instr) throw new Error('Nhập vật liệu mới hoặc yêu cầu cho việc này');
  S.tasks.push({ targetLayer: S.layer, vatLieu: vat || null, instruction: instr });
  $('jVat').value = ''; $('jInstr').value = '';
  renderTasks(); await drawMask();
}));
$('tClear').addEventListener('click', () => { S.tasks = []; renderTasks(); drawMask().catch(console.error); });
$('layerSelect').addEventListener('change', (e) => run('chọn layer', () => selectLayer(e.target.value, [])));
$('showMask').addEventListener('change', () => { $('maskOverlay').hidden = !$('showMask').checked; });
$('imgBase').addEventListener('click', (ev) => {
  if (!S.data) return;
  const im = ev.currentTarget; const r = im.getBoundingClientRect();
  const x = Math.floor(((ev.clientX - r.left) / r.width) * S.data.width), y = Math.floor(((ev.clientY - r.top) / r.height) * S.data.height);
  run('chọn chi tiết', async () => {
    const p = await api(`/api/designs/${S.id}/pick?view=${encodeURIComponent(S.view)}&x=${x}&y=${y}`);
    if (!p.chiTiet) return status('Không có chi tiết ở điểm này');
    await selectLayer(p.layers[0], p.layers);
  });
});

// các bản JSON của một job, chuyển ngay trong ô xem
function jobVariants(id, chuaGui) {
  const t = chuaGui ? ' (chưa gửi)' : '';
  return [
    { label: 'Rút gọn', hint: 'Bản gửi AI: chỉ dẫn + ảnh đính kèm', url: `/api/image-jobs/${id}/request`, name: `${id}-request.json`, title: `Request gửi AI (rút gọn) · ${id}${t}` },
    { label: 'Đầy đủ', hint: 'Bản kiểm tra, không gửi AI', url: `/api/image-jobs/${id}/request?dang=day-du`, name: `${id}-request.full.json`, title: `Bản đầy đủ (không gửi AI) · ${id}${t}` },
    { label: 'Gemini API', hint: 'Thân request Gemini API (ảnh ở inline_data)', url: `/api/image-jobs/${id}/request?dang=gemini`, name: `${id}-gemini-request.json`, title: `Thân request Gemini API · ${id}${t}` },
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
  $('jBackend').replaceChildren(...Object.entries(b.backends).map(([k, v]) => el('option', { value: k, textContent: `${k} — ${v.ten}` })));
  if (b.macDinh && b.backends[b.macDinh]) $('jBackend').value = b.macDinh;
  $('jWf').replaceChildren(el('option', { value: '', textContent: 'mặc định' }),
    ...Object.entries(b.workflows).map(([k, v]) => el('option', { value: k, textContent: `${k} (${v.kind})` })));
  S.thaoTac = b.thaoTac || {};
  $('jThao').replaceChildren(el('option', { value: '', textContent: 'tự động' }),
    ...Object.entries(S.thaoTac).map(([k, v]) => el('option', { value: k, textContent: `${v.ten} (${v.kind})`, title: v.moTa })));
}
function thaoTacFor(kind) {  // chỉ gửi cấu hình chọn sẵn khi khớp loại job
  const t = $('jThao').value;
  return t && S.thaoTac?.[t]?.kind === kind ? t : null;
}

// ------------------------------------------------------------------ sửa hình (xóa / thêm / thay vật)
const KIEU = {
  'kieu-canh': [['phang', 'Cánh phẳng'], ['khung', 'Cánh khung (shaker)'], ['kinh', 'Cánh kính']],
  'tay-nam': [['thanh', 'Tay thanh'], ['num', 'Núm tròn'], ['am', 'Tay âm (khoét)'], ['khong', 'Không tay (nhấn mở)']],
};
S.hinh = [];
function hinhForm() {
  const k = $('hLoai').value;
  $('hMaWrap').hidden = !['xoa-module', 'kieu-canh'].includes(k);
  $('hKieuWrap').hidden = !KIEU[k];
  $('hDonWrap').hidden = k !== 'xoa-module';
  $('hJsonWrap').hidden = !['them-module', 'op'].includes(k);
  $('hJson').placeholder = k === 'op' ? '{"op": "update", "ma": "TD1", "thayDoi": {"cao": 820}}' : '{"module": {"ma": "TD6", "loai": "duoi", "tuong": "phai", "rong": 450, "cao": 720, "sau": 560}, "sauModule": "TD5"}';
  if (KIEU[k]) $('hKieu').replaceChildren(...KIEU[k].map(([v, t]) => el('option', { value: v, textContent: t })));
  const mods = (S.data?.layers || []).filter((l) => l.id.startsWith('module:') && l.loai === 'module').map((l) => l.module);
  const cur = $('hMa').value;
  $('hMa').replaceChildren(...(k === 'kieu-canh' ? [el('option', { value: '*', textContent: '* mọi module' })] : []),
    ...mods.map((m) => el('option', { value: m, textContent: m })));
  if (cur && [...$('hMa').options].some((o) => o.value === cur)) $('hMa').value = cur;
}
function hinhItem() {
  const k = $('hLoai').value;
  if (k === 'xoa-module') return { loai: k, ma: $('hMa').value, donDay: $('hDonDay').checked };
  if (k === 'kieu-canh') return { loai: k, ma: $('hMa').value, kieu: $('hKieu').value };
  if (k === 'tay-nam') return { loai: k, kieu: $('hKieu').value };
  let j;
  try { j = JSON.parse($('hJson').value || '{}'); } catch (e) { throw new Error(`JSON lỗi: ${e.message}`); }
  return k === 'op' ? { loai: 'op', op: j } : { loai: k, ...j };
}
function hinhText(x) {
  if (x.loai === 'xoa-module') return `Xóa ${x.ma}${x.donDay ? ' (dồn tủ)' : ''}`;
  if (x.loai === 'kieu-canh') return `${x.ma === '*' ? 'Mọi module' : x.ma}: ${KIEU['kieu-canh'].find((k) => k[0] === x.kieu)[1]}`;
  if (x.loai === 'tay-nam') return `Tay nắm: ${KIEU['tay-nam'].find((k) => k[0] === x.kieu)[1]}`;
  if (x.loai === 'them-module') return `Thêm ${x.module?.ma || 'module'}`;
  return `Thao tác ${x.op?.op || '?'}`;
}
function renderHinh() {
  $('hList').replaceChildren(...S.hinh.map((x, i) => el('li', {}, hinhText(x), ' ',
    el('button', { type: 'button', class: 'ghost small', textContent: '✕', onclick: () => { S.hinh.splice(i, 1); renderHinh(); } }))));
  $('hCreate').textContent = S.hinh.length > 1 ? `Tạo job sửa hình (${S.hinh.length} thao tác)` : 'Tạo job sửa hình';
}
$('hLoai').addEventListener('change', hinhForm);
$('hinhBox').addEventListener('toggle', hinhForm);
$('hAdd').addEventListener('click', () => run('thêm thao tác', async () => { S.hinh.push(hinhItem()); renderHinh(); }));
$('hCreate').addEventListener('click', () => S.data && run('tạo job sửa hình', async () => {
  if (!S.hinh.length) S.hinh.push(hinhItem());
  await create('hinh');
}));
async function create(kind) {
  const body = { view: S.view, kind, backend: $('jBackend').value, mode: $('jMode').value, vatLieu: $('jVat').value.trim() || null,
    instruction: $('jInstr').value.trim(), reference: $('jRef').value, baseRev: S.data.rev, workflow: $('jWf').value || null,
    xemTruoc: $('jPreview').checked };
  body.thaoTac = thaoTacFor(kind);
  body.anhSang = $('jLight').value;
  if (kind === 'hinh') { body.hinh = S.hinh; body.vatLieu = null; body.mode = 'thiet-ke'; }
  else if (kind === 'edit' && S.tasks.length) {  // nhiều việc: ô vật liệu/yêu cầu lúc này là yêu cầu chung
    body.tasks = S.tasks; body.vatLieu = null;
  } else if (kind === 'edit') body.targetLayer = S.layer;
  const j = await api(`/api/designs/${S.id}/image-jobs`, 'POST', body);
  S.job = j.id; if (kind === 'edit' && S.tasks.length) { S.tasks = []; renderTasks(); await drawMask(); }
  if (kind === 'hinh') { S.hinh = []; renderHinh(); }
  await loadJobs();
  if (j.status === 'cho-gui') {  // xem trước: mở ngay request sẽ gửi
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
    const st = j.status.startsWith('loi') ? 'loi' : j.status;
    ul.append(el('li', { class: j.id === S.job ? 'sel' : '', onclick: () => { S.job = j.id; loadJobs(); } },
      el('span', {}, `${j.kind === 'gen0' ? 'gen-0' : j.kind === 'hinh' ? `✎ ${j.target.replace(/^hinh: /, '')}` : j.target} · ${j.backend}`), el('span', { class: `st ${st}` }, j.status)));
  }
  const cur = S.jobs.find((j) => j.id === S.job);
  showJob(cur);
  const running = S.jobs.some((j) => j.status === 'dang-chay');
  clearTimeout(S.poll); if (running && active()) S.poll = setTimeout(() => loadJobs().catch(console.error), 2000);
}
function showJob(j) {
  const box = $('jobDetail'); box.replaceChildren(); box.hidden = !j;
  if (!j) { compare(null); return; }
  const r = j.result || {}; const rep = r.report || {}; const req = j.request || {};
  box.append(el('p', {}, el('b', {}, j.id), ` · ${j.mode} · rev ${j.rev}`));
  if (req.phamVi) box.append(el('p', {}, `Phạm vi thiết kế: ${req.phamVi}`));
  if (req.prompt) box.append(el('p', { class: 'muted' }, `Prompt: ${req.prompt}`));
  if (j.error) box.append(el('p', { class: 'st loi' }, j.error));
  if (rep.ngoaiMask) {
    box.append(el('p', {}, `Ngoài mask: ${rep.ngoaiMask.datBaoToan ? 'giữ nguyên ✓' : rep.ngoaiMask.pixelKhacGoc + ' px khác ✗'} · ` +
      `trong mask đổi ${rep.trongMask.thayDoiTrungBinh}` + (rep.bien ? ` · biên ${rep.bien.datBien ? '✓' : '✗'} (${rep.bien.tyLeNetKetQua}/${rep.bien.tyLeNetGoc})` : '') +
      ` · ảnh thô lệch ngoài vùng sửa ${rep.anhTho.thayDoiNgoaiVungSua}`));
  }
  if (rep.viec?.length > 1) {
    const ol = el('ol', { class: 'tasks' });
    rep.viec.forEach((v, k) => { const c = PALETTE[k % PALETTE.length]; const t = (req.tasks || [])[k] || {};
      ol.append(el('li', {}, el('span', { class: 'sw', style: `background:rgb(${c.join(',')})` }),
        `${v.targetLayer}${t.vatLieu ? ' → ' + t.vatLieu : ''}: ${v.trongMask.coThayDoi ? 'đã đổi ✓' : 'gần như không đổi ✗'}` +
        (v.bien ? ` · biên ${v.bien.datBien ? '✓' : '✗'}` : ''))); });
    box.append(ol);
  }
  if (r.thietKe) box.append(el('p', { class: 'st da-chap-nhan' }, `Đã ghi vào thiết kế: rev ${r.thietKe.rev} (${r.thietKe.phamVi})` +
    (r.thietKe.boQua ? ` · bỏ qua: ${r.thietKe.boQua.join('; ')}` : '')));
  const row = el('div', { class: 'row' });
  const act = (label, path, body, after) => row.append(el('button', { type: 'button', textContent: label, onclick: () => run(label, async () => {
    const res = await api(`/api/image-jobs/${j.id}/${path}`, 'POST', body || {}); if (path === 'regenerate') S.job = res.id;
    await loadJobs(); if (after) await after(res);
  }) }));
  const reloadDesign = async (res) => { if (res.result?.thietKe && window.kitchen) await window.kitchen.reload(S.id); };
  if (j.status === 'cho-gui') {
    box.append(el('p', { class: 'st cho-gui' }, `Chưa gửi: kiểm tra mask và chỉ dẫn (Xem JSON) rồi bấm Gửi.`));
    act(`Gửi ${j.backend}`, 'send');
  }
  if (j.status === 'can-duyet') {
    act(j.mode === 'thiet-ke' ? 'Chấp nhận & ghi thiết kế' : 'Chấp nhận', 'accept', {}, async (res) => { await reloadDesign(res); await load(); });
    if (j.mode === 'thu-nhanh' && (req.vatLieu || (req.tasks || []).some((t) => t.vatLieu))) act('Chấp nhận & áp vào thiết kế', 'accept', { apVaoThietKe: true }, async (res) => { await reloadDesign(res); await load(); });
  }
  if (!['da-chap-nhan', 'tu-choi'].includes(j.status)) act(j.status === 'cho-gui' ? 'Hủy' : 'Từ chối', 'reject');
  if (!['dang-chay', 'cho-gui'].includes(j.status)) act('Sinh lại', 'regenerate');
  if (j.status === 'cho-ket-qua' || j.status.startsWith('loi') || j.status === 'can-duyet') {
    const inp = el('input', { type: 'file', accept: 'image/png,image/jpeg' });
    inp.addEventListener('change', () => run('nộp ảnh', async () => {
      const f = inp.files[0]; if (!f) return;
      const b64 = await new Promise((ok, err) => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.onerror = err; fr.readAsDataURL(f); });
      await api(`/api/image-jobs/${j.id}/result`, 'POST', { imageBase64: b64 }); await loadJobs();
    }));
    row.append(el('label', { class: 'file', textContent: 'Nộp ảnh' }, inp));
  }
  box.append(row);
  // gửi AI: bản đã lọc (xem), thân Gemini API (ảnh inline_data, Gemini tự giải mã), hoặc Gemini web (đính kèm ảnh + dán chỉ dẫn)
  const n = (req.tasks || []).length;
  const send = el('div', { class: 'sendai' }, el('b', {}, `Gửi AI${n > 1 ? ` (${n} việc)` : ''}: `),
    el('a', { href: '#', textContent: 'Xem JSON (rút gọn / đầy đủ)', onclick: (ev) => { ev.preventDefault();
      run('mở request', () => window.kitchenJson.showJsonUrl(`Request gửi AI · ${j.id}`, `/api/image-jobs/${j.id}/request`, `${j.id}-request.json`, jobVariants(j.id, j.status === 'cho-gui'))); } }),
    ' · ', el('a', { href: `/api/image-jobs/${j.id}/request?dang=gemini`, download: `${j.id}-gemini-request.json`, textContent: 'JSON cho Gemini API' }));
  const web = el('div', { class: 'sendai' }, el('b', {}, 'Gemini web: '),
    el('a', { href: '#', textContent: 'Chép chỉ dẫn', onclick: (ev) => { ev.preventDefault(); run('chép chỉ dẫn', async () => {
      const r = await (await fetch(`/api/image-jobs/${j.id}/request`)).json();
      await navigator.clipboard.writeText(r.chiDan); status('Đã chép chỉ dẫn — dán vào Gemini sau khi đính kèm ảnh', 'ok'); }); } }));
  for (const [k, u] of Object.entries(j.files || {}).filter(([k]) => /^anh-\d-/.test(k)).sort()) {
    web.append(' · ', el('a', { href: u, download: `${j.id}-${k}`, textContent: `Ảnh ${k.split('-')[1]}: ${k.replace(/^anh-\d-|\.png$/g, '')}` }));
  }
  web.append(el('div', { class: 'warnbox', textContent: '⚠ Không dán file JSON vào khung chat Gemini (chat đọc base64 như chữ, file thường bị cắt, AI không thấy ảnh). '
    + 'Đính kèm Ảnh 1 (có viền màu + số quanh vùng sửa) và Ảnh 2 (mask) dạng file, rồi dán chỉ dẫn.' }));
  const kt = el('div', { class: 'sendai kiemtra', textContent: 'Kiểm tra request: đang kiểm tra…' });
  {
    fetch(`/api/image-jobs/${j.id}/request`).then((r) => r.json()).then((r) => showCheck(kt, r.kiemTra, 'Kiểm tra request'))
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
  const imgs = (kt.anh || []).map((a) => `ảnh ${a.thuTu}${a.vaiTro ? ` (${a.vaiTro})` : ''} ${a.ok ? `✓${a.kichThuoc ? ` ${a.kichThuoc.join('×')}` : ''}` : '✗'}`);
  if (imgs.length) box.append(el('div', { class: 'muted', textContent: imgs.join(' · ') }));
  const ul = el('ul');
  for (const x of kt.loi || []) ul.append(el('li', { class: 'bad', textContent: x }));
  for (const x of kt.canhBao || []) ul.append(el('li', { class: 'warn', textContent: x }));
  if (ul.childElementCount) box.append(ul);
}

window.addEventListener('design-opened', () => { if (active()) run('mở ảnh', load); });
window.addEventListener('view-changed', () => { if (active()) run('mở ảnh', load); });
$('designSelect').addEventListener('change', () => { S.layer = null; S.job = null; S.tasks = []; renderTasks(); });
loadBackends().catch((e) => status(e.message, 'warn'));
