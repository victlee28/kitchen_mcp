// Create / import / export panel: free-text prompt, kitchen template, spec import, spec and three.js export.
import { $, el } from './dom.js';
import { tx, pick, lang } from './i18n.js';

export function createDesignCreatePanel({ state, api, run, setStatus, loadDesigns, clearSelection }) {
  // Bảng "đã hiểu gì từ mô tả": mỗi thuật ngữ kèm vùng áp, trường đích và trạng thái hỗ trợ (chữ qua textContent)
  const STATUS_VI = { built: tx('ui.da-dung'), exported: tx('ui.ghi-vao-thiet-ke-file-3d'), 'ai-only': tx('ui.chi-cho-anh-ai'), unsupported: tx('ui.chua-ho-tro'), ambiguous: tx('ui.chua-ro') };
  const SCOPE_VI = { base: tx('ui.tu-duoi'), upper: tx('ui.tu-tren'), tall: tx('ui.tu-cao'), countertop: tx('ui.mat-ban'), wallTile: tx('ui.op-tuong'), handle: tx('ui.tay-nam'), floor: tx('ui.san'), wall: tx('ui.tuong'), whole: tx('ui.toan-bep'), '?': tx('ui.chua-ro') };
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
    for (const h of [tx('ui.tu-trong-mo-ta'), tx('ui.hieu-la'), tx('ui.ap-cho'), tx('ui.trang-thai'), tx('ui.ghi-chu')]) { const th = document.createElement('th'); th.textContent = h; head.append(th); }
    table.append(head, ...rows);
    const title = document.createElement('p'); title.className = 'muted small'; title.textContent = tx('ui.he-thong-da-hieu-mo-ta-nhu');
    box.append(title, table);
  }
  $('fromPrompt').addEventListener('click', () => {
    const p = $('prompt').value.trim(); if (!p) return setStatus(tx('ui.hay-nhap-mo-ta'), 'warn');
    run(tx('ui.tao-tu-mo-ta'), async () => {
      const r = await api('/api/designs', 'POST', { prompt: p }); clearSelection(); await loadDesigns(r.id);
      showInterpretation(r.analysis?.interpretation || []);
    });
  });
  // The layout templates of the catalog (I, L, U and those the workshop / user added): the walls each one uses decide which lengths are asked.
  let walls = { I: ['back'], L: ['back', 'right'], U: ['back', 'right', 'left'] };
  api(`/api/catalog/layout-template?lang=${lang()}`).then((d) => {
    walls = Object.fromEntries(d.items.map((it) => [it.id, it.data.walls || ['back']]));
    const keep = $('mShape').value;
    $('mShape').replaceChildren(...d.items.map((it) => el('option', { value: it.id, textContent: `${it.id} — ${pick(it.data.label)}`, selected: it.id === keep })));
  }).catch(() => { /* no server yet: the three builtin layouts of the page */ });
  $('fromTemplate').addEventListener('click', () => {
    const color = { country: state.qg || null, geometry_edit: $('mShape').value, backWallLength: Number($('mBack').value), cabinetTop: Number($('mTop').value), backsplashHeight: $('mBacksplash').value, fridge: $('mFridge').checked, loft: $('mLoft').checked, island: $('mIsland').checked, peninsula: $('mPeninsula').checked, openShelf: $('mOpenShelf').checked, style: $('mStyle').value };
    const used = walls[color.geometry_edit] || ['back'];
    if (used.includes('right')) color.rightWallLength = Number($('mRight').value);
    if (used.includes('left')) color.leftWallLength = Number($('mLeft').value);
    run(tx('ui.tao-tu-mau'), async () => { const r = await api('/api/designs', 'POST', { color, name: tx('ui.bep-chu', { 0: color.geometry_edit }) }); clearSelection(); await loadDesigns(r.id); });
  });
  $('importFile').addEventListener('change', (e) => {
    const file = e.target.files[0]; if (!file) return;
    run(tx('ui.nhap-spec'), async () => { const spec = JSON.parse(await file.text()); const r = await api('/api/designs', 'POST', { spec }); await loadDesigns(r.id); });
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
}
