// Header controls: design picker, view picker and the country/standard picker.
import { $, el } from './dom.js';
import { languagePicker, tx } from './i18n.js';

export function createHeaderControls({ state, api, run, openDesign, clearSelection, setView, onViewChanged }) {
  $('langSlot')?.append(languagePicker(() => location.reload()));   // labels built when the modules load follow the language: reload
  $('designSelect').addEventListener('change', (e) => e.target.value && run(tx('ui.mo-thiet-ke'), () => { clearSelection(); return openDesign(e.target.value); }));
  $('viewSelect').addEventListener('change', (e) => { setView(e.target.value); onViewChanged(e.target.value); });
  $('qgSelect').addEventListener('change', (e) => { state.qg = e.target.value; if (state.id) run(tx('ui.kiem-tra-theo-tieu-chuan'), () => openDesign(state.id, true)); });
  async function loadRegions() {
    const r = await api('/api/regions'); const sel = $('qgSelect');
    for (const [code, q] of Object.entries(r.country)) sel.append(el('option', { value: code, textContent: `${q.name} (${code})` }));
  }
  return { loadRegions };
}
