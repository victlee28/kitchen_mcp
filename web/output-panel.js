// Output panel: view-sync status, controlled-image render, final JSON/zip export for the AI image generator.
import { $, el } from './dom.js';
import { aiExportUrls } from './design-logic.js';

export function createOutputPanel({ state, api, run, setStatus }) {
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
    const urls = aiExportUrls(state.id, state.rev, light);
    $('aiJson').href = urls.shortUrl;  // một file: nhúng sẵn ảnh nên gửi của từng góc
    $('aiJson').setAttribute('download', urls.shortName);
    if (!$('aiAuto').checked || (!force && aiDone[state.id] === state.rev)) {
      if (aiDone[state.id] !== state.rev) $('aiInfo').textContent = `Thiết kế đang ở rev ${state.rev} — chưa xuất bản này`;
      return;
    }
    const id = state.id;
    const res = await api(`/api/designs/${id}/ai-export`, 'POST', { rev: state.rev, lighting: light });
    aiDone[id] = res.rev;
    if (state.id === id) aiInfo(res);   // the user may have switched design while the export ran
  }
  $('aiLight').addEventListener('change', () => run('xuất lại cho AI', () => syncAiExport(true)));
  $('aiZip').addEventListener('click', () => state.id && run('xuất gói kèm ảnh cho AI', async () => {
    const res = await api(`/api/designs/${state.id}/ai-export`, 'POST', { rev: state.rev, withImage: true, lighting: $('aiLight').value });
    aiDone[state.id] = res.rev; aiInfo(res);
    if (res.url?.zip) el('a', { href: res.url.zip, download: aiExportUrls(state.id, state.rev, '').zipName(res.rev) }).click();
  }));

  $('aiView').addEventListener('click', () => {
    if (!state.id) return;
    const u = aiExportUrls(state.id, state.rev, $('aiLight').value);
    const variants = [
      { label: 'Rút gọn', hint: 'Bản gửi AI: chỉ dẫn + ảnh đính kèm', url: u.shortUrl, name: u.shortName, title: u.shortTitle },
      { label: 'Đầy đủ', hint: 'Bản kiểm tra, không gửi AI', url: u.fullUrl, name: u.fullName, title: u.fullTitle },
    ];
    run('mở JSON cuối cùng', () => window.kitchenJson.showJsonUrl(variants[0].title, variants[0].url, variants[0].name, variants));
  });
  return { refreshViewSync, syncAiExport };
}
