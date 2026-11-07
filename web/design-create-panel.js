// Create / import / export panel: free-text prompt, kitchen template, spec import, spec and three.js export.
import { $, el } from './dom.js';

export function createDesignCreatePanel({ state, api, run, setStatus, loadDesigns, clearSelection }) {
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
      const r = await api('/api/designs', 'POST', { prompt: p }); clearSelection(); await loadDesigns(r.id);
      showInterpretation(r.analysis?.interpretation || []);
    });
  });
  $('fromTemplate').addEventListener('click', () => {
    const color = { country: state.qg || null, geometry_edit: $('mShape').value, backWallLength: Number($('mBack').value), cabinetTop: Number($('mTop').value), backsplashHeight: $('mBacksplash').value, fridge: $('mFridge').checked, loft: $('mLoft').checked, island: $('mIsland').checked, peninsula: $('mPeninsula').checked, openShelf: $('mOpenShelf').checked, style: $('mStyle').value };
    if (color.geometry_edit !== 'I') color.rightWallLength = Number($('mRight').value);
    if (color.geometry_edit === 'U') color.leftWallLength = Number($('mLeft').value);
    run('tạo từ mẫu', async () => { const r = await api('/api/designs', 'POST', { color, name: `Bếp chữ ${color.geometry_edit}` }); clearSelection(); await loadDesigns(r.id); });
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
}
