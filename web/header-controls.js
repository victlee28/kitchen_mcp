// Header controls: design picker, view picker and the country/standard picker.
import { $, el } from './dom.js';

export function createHeaderControls({ state, api, run, openDesign, clearSelection, setView, onViewChanged }) {
  $('designSelect').addEventListener('change', (e) => e.target.value && run('mở thiết kế', () => { clearSelection(); return openDesign(e.target.value); }));
  $('viewSelect').addEventListener('change', (e) => { setView(e.target.value); onViewChanged(e.target.value); });
  $('qgSelect').addEventListener('change', (e) => { state.qg = e.target.value; if (state.id) run('kiểm tra theo tiêu chuẩn', () => openDesign(state.id, true)); });
  async function loadRegions() {
    const r = await api('/api/regions'); const sel = $('qgSelect');
    for (const [code, q] of Object.entries(r.country)) sel.append(el('option', { value: code, textContent: `${q.name} (${code})` }));
  }
  return { loadRegions };
}
