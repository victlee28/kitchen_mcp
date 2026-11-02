// Ô xem JSON dạng cây (dùng chung cho "Xuất cho AI tạo ảnh" và request của job sửa ảnh).
// Chuỗi ảnh base64 (data:image/...) hiện thành hình thu nhỏ + dung lượng thay vì hàng trăm nghìn ký tự.
// Mọi chữ hiển thị qua textContent.
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else if (v !== undefined) n[k] = v;
  }
  for (const c of kids) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}

const kb = (s) => `${Math.round((s.length * 3) / 4 / 1024)} KB`;

function leaf(v) {
  if (v === null) return el('span', { class: 'jv-null' }, 'null');
  if (typeof v === 'string') {
    if (/^data:image\//.test(v)) {
      return el('span', { class: 'jv-img' }, el('img', { src: v, alt: 'ảnh nhúng', loading: 'lazy' }),
        el('small', {}, `ảnh base64 · ${kb(v)}`));
    }
    return el('span', { class: 'jv-str' }, JSON.stringify(v));
  }
  return el('span', { class: typeof v === 'number' ? 'jv-num' : 'jv-bool' }, String(v));
}

function summary(v) {
  if (Array.isArray(v)) return `[ ${v.length} ]`;
  const keys = Object.keys(v);
  return `{ ${keys.slice(0, 4).join(', ')}${keys.length > 4 ? ', …' : ''} }`;
}

function node(key, v, depth) {
  const label = key === null ? null : el('span', { class: 'jv-key' }, `${key}: `);
  // phần ảnh của Gemini API: {mime_type: 'image/png', data: '<base64>'} -> hiện ảnh như máy chủ Gemini sẽ giải mã
  const mt = v && typeof v === 'object' && !Array.isArray(v) && (v.mime_type || v.mimeType);
  if (typeof mt === 'string' && mt.startsWith('image/') && typeof v.data === 'string') {
    const url = `data:${mt};base64,${v.data}`;
    return el('div', { class: 'jv-row' }, label || '', el('span', { class: 'jv-sum' }, `{ mime_type: "${mt}", data: … } `), leaf(url));
  }
  if (v === null || typeof v !== 'object') return el('div', { class: 'jv-row' }, label || '', leaf(v));
  const d = el('details', { open: depth < 1 });
  d.append(el('summary', {}, label || '', el('span', { class: 'jv-sum' }, summary(v))));
  let built = false;
  const build = () => {  // dựng con khi mở, để JSON lớn (cảnh three.js) không làm treo trang
    if (built) return; built = true;
    const box = el('div', { class: 'jv-kids' });
    const entries = Array.isArray(v) ? v.map((x, i) => [i, x]) : Object.entries(v);
    for (const [k, x] of entries) box.append(node(k, x, depth + 1));
    d.append(box);
  };
  if (d.open) build();
  d.addEventListener('toggle', () => d.open && build());
  return d;
}

let current = { obj: null, name: 'data.json' };

export function showJson(title, obj, downloadName = 'data.json') {
  current = { obj, name: downloadName };
  $('jvTitle').textContent = title;
  const text = JSON.stringify(obj);
  const n = (text.match(/data:image\//g) || []).length + (text.match(/"mime_?[tT]ype":"image\//g) || []).length;
  $('jvMeta').textContent = `${Math.round(text.length / 1024)} KB · ${n} ảnh nhúng`;
  $('jvTree').replaceChildren(node(null, obj, 0));
  $('jvRaw').hidden = true; $('jvTree').hidden = false; $('jvMode').textContent = 'Xem dạng chữ';
  if (!$('jsonView').open) $('jsonView').showModal();
}

$('jvClose').addEventListener('click', () => $('jsonView').close());
$('jvMode').addEventListener('click', () => {
  const raw = $('jvRaw');
  if (raw.hidden) {  // dạng chữ: rút gọn base64 để đọc được
    raw.textContent = JSON.stringify(current.obj, (k, v) => (typeof v === 'string' && (v.startsWith('data:image/') || (k === 'data' && v.length > 200))
      ? `${v.slice(0, 40)}… (${kb(v)})` : v), 2);
    raw.hidden = false; $('jvTree').hidden = true; $('jvMode').textContent = 'Xem dạng cây';
  } else { raw.hidden = true; $('jvTree').hidden = false; $('jvMode').textContent = 'Xem dạng chữ'; }
});
$('jvCopy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(JSON.stringify(current.obj, null, 1)); $('jvMeta').textContent += ' · đã chép'; }
  catch { $('jvMeta').textContent += ' · không chép được (trình duyệt chặn)'; }
});
$('jvDownload').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(current.obj, null, 1)], { type: 'application/json' }));
  el('a', { href: url, download: current.name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
});

export async function showJsonUrl(title, url, downloadName, variants = null) {
  // variants: [{label, url, name, title?}] -> nút chuyển giữa các bản (vd rút gọn gửi AI / đầy đủ) ngay trong ô xem
  const box = $('jvVariants');
  if (variants) {
    box.replaceChildren(...variants.map((v) => el('button', { type: 'button', class: v.url === url ? 'on' : '', textContent: v.label, title: v.hint || '',
      onclick: () => showJsonUrl(v.title || title, v.url, v.name || downloadName, variants).catch((e) => { $('jvMeta').textContent = e.message; }) })));
    box.hidden = false;
  } else { box.replaceChildren(); box.hidden = true; }
  $('jvMeta').textContent = 'đang tải…';
  const r = await fetch(url);
  const d = await r.json().catch(() => null);
  if (!r.ok || !d) throw new Error((d && d.error) || `HTTP ${r.status}`);
  showJson(title, d, downloadName);
}
window.kitchenJson = { showJson, showJsonUrl };
