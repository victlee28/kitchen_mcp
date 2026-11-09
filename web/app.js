// Kitchen Editor — viewer three.js + panel sửa module. Mọi dữ liệu hiển thị qua textContent (không innerHTML).
import { createViewer } from './kitchen-viewer.js';
import { createStructureSelector } from './structure-select.js';
import { createModuleMenu } from './module-menu.js';
import { selectionEffect } from './menu-logic.js';
import { createAssist } from './assist.js';
import { $, el } from './dom.js';
import { api, createStatus } from './api-client.js';
import { createDesignController } from './design-controller.js';
import { createDesignEditor } from './design-editor.js';
import { createOutputPanel } from './output-panel.js';
import { createMoldingPanel } from './molding-panel.js';
import { createDesignCreatePanel } from './design-create-panel.js';
import { createFloorplanPanel } from './floorplan-panel.js';
import { createHeaderControls } from './header-controls.js';

const { setStatus, run } = createStatus($('status'));
const controller = createDesignController({ api, renderList: renderDesignList, onOpened: showDesign });
const { state, loadDesigns, afterChange } = controller;
const editor = createDesignEditor({ state, api, run, setStatus, afterChange, setViewerSelected: (id) => viewer.setSelected(id) });
const openDesign = (id, keepView = false) => controller.open(id, { keepView });

// ---------------- 3D + chọn
const viewer = createViewer({
  container: $('viewport'),
  moduleIds: () => (state.spec ? state.spec.module.map((m) => m.id) : null),
  extraPickables: () => structSel.pickables(),
  onSceneBuilt: (k) => structSel.setScene(k.structures, k.structurePickables),
  // a left click while the popup is open: another object -> the popup moves to it; empty space -> it closes
  onPick: (target, at, menuTarget) => {
    applyTarget(target);
    if (!moduleMenu.isOpen) return;
    if (menuTarget) moduleMenu.open(menuTarget, at.x, at.y); else moduleMenu.close();
  },
  onContext: (target, at) => {
    if (!target) { moduleMenu.close(); return; }
    applyTarget(target);
    moduleMenu.open(target, at.x, at.y);
  },
});
const structSel = createStructureSelector({ THREE: viewer.THREE, els: { section: $('fpElements'), kinds: $('fpKinds'), list: $('fpList'), detail: $('fpDetail'), actions: $('fpActions'),
  hide: $('fpHide'), isolate: $('fpIsolate'), showAll: $('fpShowAll') },
  onSelect: () => editor.clearSelection({ redraw: true }) });
// The one place that turns "something was picked" into a selection (click, right click and the structure list all end here).
function applyTarget(target) {
  const effect = selectionEffect(target);
  if (effect.selectStructure) structSel.select(effect.selectStructure);
  if (effect.clearStructure) structSel.clear();
  if (effect.selectModule) editor.selectModule(effect.selectModule);
}
window.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !moduleMenu.isOpen && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || '')) structSel.clear(); });
const moduleMenu = createModuleMenu({
  box: $('ctxMenu'), setStatus, keepOpenOn: (node) => $('viewport').contains(node),   // a press in the 3D view is decided by the click handler above
  getState: () => ({ id: state.id, rev: state.rev, spec: state.spec }),
  afterChange: (res) => afterChange(res), reload: () => openDesign(state.id, true),
  structure: { hide: () => structSel.hideSelected(), isolate: () => structSel.isolateSelected(), showAll: () => structSel.showAll() },
  imageEdit: (detail) => window.dispatchEvent(new CustomEvent('image-edit-request', { detail })),
});
createAssist({ setStatus, getState: () => ({ id: state.id, rev: state.rev, selected: state.selected }), afterChange: (res) => afterChange(res) });
$('moduleActions').addEventListener('click', (ev) => { const r = ev.currentTarget.getBoundingClientRect(); if (state.selected) moduleMenu.open({ kind: 'module', id: state.selected }, r.left - 260, r.bottom + 4); });

// ---------------- dữ liệu thiết kế
function renderDesignList(list, selectedId) {
  const sel = $('designSelect'); sel.replaceChildren();
  for (const d of list) sel.append(el('option', { value: d.id, textContent: `${d.name} · rev ${d.rev}` }));
  if (!list.length) sel.append(el('option', { value: '', textContent: '(chưa có thiết kế)' }));
  if (selectedId) sel.value = selectedId;
}
// Show a freshly loaded design (the controller has already updated `state`).
function showDesign({ id, rev, spec, scene: sc, validation: v, doc, keepView }) {
  $('revInfo').textContent = `rev ${rev}`;
  viewer.setSelected(state.selected);
  viewer.setViews(sc.views);
  viewer.setDocument(doc);
  const vs = $('viewSelect'); const prev = vs.value; vs.replaceChildren();
  for (const [k, g] of Object.entries(sc.views)) vs.append(el('option', { value: k, textContent: g.name || k }));
  if (keepView && sc.views[prev]) vs.value = prev; else viewer.setView(vs.value);
  editor.onDesignOpened(v); syncMoldingPanel();
  $('openRender').href = `render.html?design=${encodeURIComponent(id)}`;
  refreshViewSync().catch((e) => console.warn('view-status', e));
  syncAiExport().catch((e) => setStatus('Xuất JSON cho AI lỗi: ' + e.message, 'warn'));
  window.dispatchEvent(new CustomEvent('design-opened', { detail: { id, rev } }));
}

// ---------------- panels
const clearSelection = () => editor.clearSelection();
const { refreshViewSync, syncAiExport } = createOutputPanel({ state, api, run, setStatus });
const { loadProfiles, syncMoldingPanel } = createMoldingPanel({ state, api, run, afterChange });
createDesignCreatePanel({ state, api, run, setStatus, loadDesigns, clearSelection });
createFloorplanPanel({ state, api, run, setStatus, loadDesigns, openDesign });
const { loadRegions } = createHeaderControls({ state, api, run, openDesign, clearSelection, setView: (k) => viewer.setView(k),
  onViewChanged: (key) => window.dispatchEvent(new CustomEvent('view-changed', { detail: key })) });

// imgedit.js (separate script, works without three.js) asks for a reload by event instead of reaching into this app.
window.addEventListener('design-reload-request', (ev) => run('tải lại', () => afterChange({ id: ev.detail.id })));

run('tải', async () => { await loadRegions(); await loadProfiles(); await loadDesigns(); });
