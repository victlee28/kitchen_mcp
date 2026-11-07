// Trang render ảnh: chọn thiết kế (lấy JSON three.js mới nhất) hoặc mở file JSON, render mọi góc camera, tải PNG.
// Khi nguồn là thiết kế: lưu ảnh vào renders/<id>/rev<N>/<góc>/beauty.png để dùng làm ảnh gốc cho tab "Sửa ảnh theo lớp".
import { renderDoc } from './photo-render.js';
import { $, el } from './dom.js';
import { api } from './api-client.js';

const S = { doc: null, designId: null, rev: null, results: [] };
function status(msg, kind = '') { const s = $('status'); s.textContent = msg; s.className = 'status ' + kind; }

function useDoc(doc, label) {
  if (!doc || !Array.isArray(doc.cameras) || !doc.cameras.length) throw new Error('JSON không có cameras — cần file theo Complete Kitchen Three.js Scene Schema');
  S.doc = doc;
  $('src').textContent = `${label} · ${doc.modules?.length ?? 0} module · ${doc.cameras.length} góc`;
  const box = $('views'); box.replaceChildren();
  for (const c of doc.cameras) {
    box.append(el('label', {}, el('input', { type: 'checkbox', checked: true, value: c.id.replace(/^CAM-/, '') }), ' ', c.name || c.id));
  }
  if (doc.cameras[0]?.aspect) $('h').value = Math.round(Number($('w').value) / doc.cameras[0].aspect / 16) * 16;
  $('go').disabled = false;
}

$('design').addEventListener('change', async (e) => {
  const id = e.target.value; if (!id) return;
  try {
    status('tải JSON…');
    const doc = await api(`/api/designs/${id}/threejs`);
    S.designId = id; S.rev = doc.metadata?.revision ?? null; $('save').disabled = false;
    useDoc(doc, `Thiết kế ${id} · rev ${S.rev}`); status('sẵn sàng', 'ok');
  } catch (err) { status(err.message, 'warn'); }
});
$('file').addEventListener('change', async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const doc = JSON.parse(await f.text());
    S.designId = null; S.rev = null; $('save').checked = false; $('save').disabled = true; $('design').value = '';
    useDoc(doc, `File ${f.name}`); status('sẵn sàng', 'ok');
  } catch (err) { status('File không đọc được: ' + err.message, 'warn'); }
});

async function go() {
  const views = [...$('views').querySelectorAll('input:checked')].map((i) => i.value);
  if (!views.length) throw new Error('Chọn ít nhất một góc');
  const out = $('out'); out.replaceChildren(); S.results = [];
  const opts = { width: Number($('w').value), height: Number($('h').value), exposure: Number($('exp').value), views,
    onProgress: async (r, n) => {
      status(`render ${n}/${views.length}: ${r.name}`);
      const cap = el('figcaption', {}, el('span', {}, `${r.name} · ${r.width}×${r.height}`),
        el('a', { href: r.dataUrl, download: `${S.designId || 'kitchen'}-${r.view}.png`, textContent: 'Tải PNG' }));
      out.append(el('figure', {}, el('img', { src: r.dataUrl, alt: r.name }), cap));
      S.results.push(r);
      if (S.designId && $('save').checked) {
        try {
          const res = await api(`/api/designs/${S.designId}/beauty`, 'POST', { view: r.view, rev: S.rev, imageBase64: r.dataUrl });
          const k = res.lineMatch || {};
          cap.append(el('span', { class: k.khop === false ? 'bad' : 'ok', textContent: k.khop === false ? 'đã lưu · lệch nét?' : 'đã lưu ✓' }));
        } catch (err) { cap.append(el('span', { class: 'bad', textContent: err.message })); }
      }
    } };
  await renderDoc(S.doc, opts);
  $('dlAll').hidden = false;
  status(`Xong ${S.results.length} ảnh`, 'ok');
}
$('go').addEventListener('click', () => { $('go').disabled = true; go().catch((e) => status(e.message, 'warn')).finally(() => { $('go').disabled = false; }); });
$('dlAll').addEventListener('click', async () => {
  for (const r of S.results) {
    el('a', { href: r.dataUrl, download: `${S.designId || 'kitchen'}-${r.view}.png` }).click();
    await new Promise((ok) => setTimeout(ok, 250));
  }
});

// Cho script tự động (render_browser.py): window.__render(doc, opts) -> [{view, dataUrl}]
window.__render = (doc, opts) => renderDoc(doc, opts);

(async () => {
  try {
    const list = await api('/api/designs');
    for (const d of list) $('design').append(el('option', { value: d.id, textContent: `${d.name} · rev ${d.rev}` }));
    const q = new URLSearchParams(location.search).get('design');
    if (q) { $('design').value = q; $('design').dispatchEvent(new Event('change')); }
  } catch { $('src').textContent = 'Không có máy chủ thiết kế: vẫn mở được file JSON.'; $('save').disabled = true; }
  window.__ready = true;
})();
