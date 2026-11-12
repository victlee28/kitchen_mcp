// Design editor: issue list, module list, module form and the add/remove/undo buttons.
// Owns the module selection (state.selected) and the Shift-selected group (state.multi). Receives its dependencies; never imports app.js.
import { $, el } from './dom.js';
import { FIELDS, moduleOrder, moduleLabel, formChanges, groupLabel, shiftGroup } from './design-logic.js';
import { tx } from './i18n.js';

export function createDesignEditor({ state, api, run, setStatus, afterChange, setViewerSelected }) {
  const post = (path, body) => api(`/api/designs/${state.id}/${path}`, 'POST', body);
  const findModule = (id) => state.spec?.module.find((x) => x.id === id);

  function renderIssues(v) {
    const ul = $('issues'); ul.replaceChildren();
    ul.append(el('li', { class: 'muted' }, tx('ui.ap-tieu-chuan', { 0: v.country || v.region || tx('ui.toan-cau-chua-chon-quoc-gia') })));
    ul.append(el('li', { class: v.valid ? 'ok' : 'warn' }, v.valid ? tx('ui.hop-le-canh-bao-ghi-chu', { 0: v.dem.warning, 1: v.dem.info }) : tx('ui.loi-canh-bao', { 0: v.dem.error, 1: v.dem.warning })));
    for (const i of v.issues) {
      const li = el('li', { class: 'issue ' + i.severity }, el('b', {}, `[${i.severity}] ${i.rule}`), ' ', i.content,
        i.theo ? el('small', { class: 'muted' }, ` — ${i.theo}`) : '');
      if (i.module.length) li.addEventListener('click', () => { if (findModule(i.module[0])) selectModule(i.module[0]); });
      if (i.action?.length) {  // buttons offering a fix (e.g. moulding above the ceiling: lower the cabinet top / leave as is)
        const row = el('div', { class: 'actions' });
        for (const a of i.action) {
          row.append(el('button', { type: 'button', textContent: a.label, onclick: (ev) => { ev.stopPropagation();
            run(a.label, async () => afterChange(await post('ops', { baseRev: state.rev, op: a.op }))); } }));
        }
        li.append(row);
      }
      ul.append(li);
    }
  }

  function renderModuleList() {
    const ul = $('moduleList'); ul.replaceChildren();
    const g = state.multi;
    if (g) ul.append(el('li', { class: 'muted' }, tx('ui.dang-chon-chuot-phai-vao-mot-tu', { 0: groupLabel(g) })));
    for (const m of moduleOrder(state.spec.module)) {
      ul.append(el('li', { class: m.id === state.selected || g?.modules.includes(m.id) ? 'sel' : '', onclick: () => selectModule(m.id) },
        el('b', {}, m.id), ` ${moduleLabel(m)}`));
    }
  }

  // Shift+click in the 3D view: the same role in the same tier of the same cabinet system (has: does the view show such a part on a module).
  function shiftPick(target, has) {
    const g = shiftGroup(target, state.systems, has);
    if (!g) return setStatus(tx('ui.shift-bam-vao-canh-mat-ngan-keo'), 'warn');
    state.selected = null; state.multi = g; setViewerSelected(g);
    $('moduleForm').hidden = true; renderModuleList();
    setStatus(tx('ui.da-chon', { 0: groupLabel(g) }), 'ok');
  }

  function clearGroup() {
    if (!state.multi) return;
    state.multi = null; setViewerSelected(state.selected);
    if (state.spec) renderModuleList();
  }

  /** Whether a picked target is one of the Shift-selected modules (a right click there opens the group's menu). */
  const inGroup = (t) => !!state.multi && !!t && (t.kind === 'module' || (t.kind === 'part' && t.part !== 'countertop')) && state.multi.modules.includes(t.id);

  function selectModule(id) {
    state.multi = null;
    state.selected = id; setViewerSelected(id); renderModuleList();
    const m = findModule(id); if (!m) return;
    const f = $('moduleForm'); f.hidden = false;
    $('formTitle').textContent = `${m.id} — ${m.name || m.type}`;
    const box = $('formFields'); box.replaceChildren();
    for (const [k, type] of FIELDS) {
      box.append(el('label', {}, k, el('input', { name: k, type, value: m[k] ?? '', step: type === 'number' ? '10' : undefined })));
    }
    f.elements.doors.value = (m.doors || []).join(', ');
  }

  // Drop the selection (another design opened, a structure was picked, ...).
  function clearSelection({ redraw = false } = {}) {
    const had = state.selected || state.multi;
    state.selected = null; state.multi = null; setViewerSelected(null);
    $('moduleForm').hidden = true;
    if (redraw && had && state.spec) renderModuleList();
  }

  // A design was (re)loaded: redraw the panels and keep the selection if the module still exists.
  function onDesignOpened(validation) {
    if (state.multi) { state.multi = null; setViewerSelected(null); }      // the systems may have changed with the design
    renderIssues(validation); renderModuleList();
    if (state.selected && !findModule(state.selected)) state.selected = null;
    if (state.selected) selectModule(state.selected); else $('moduleForm').hidden = true;
  }

  $('moduleForm').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = ev.target; const m = findModule(state.selected);
    const changes = formChanges(m, Object.fromEntries(FIELDS.map(([k]) => [k, f.elements[k].value])), f.elements.doors.value);
    if (!Object.keys(changes).length) return setStatus(tx('ui.khong-co-thay-doi'));
    run(tx('ui.sua', { 0: m.id }), async () => afterChange(await post('ops',
      { baseRev: state.rev, op: { op: 'update', id: m.id, changes, closeGap: f.elements.closeGap.checked } })));
  });
  $('addAfter').addEventListener('click', () => {
    const m = findModule(state.selected); if (!m) return;
    const width = Number(prompt(tx('ui.be-rong-tu-moi-mm'), '600')); if (!width) return;
    run(tx('ui.them-tu'), async () => afterChange(await post('ops',
      { baseRev: state.rev, op: { op: 'add', afterModule: m.id, module: { width, doors: width >= 600 ? [width / 2, width / 2] : [width] }, closeGap: true } })));
  });
  $('removeModule').addEventListener('click', () => {
    const id = state.selected; if (!id) return;
    run(tx('ui.xoa', { 0: id }), async () => { state.selected = null; await afterChange(await post('ops', { baseRev: state.rev, op: { op: 'remove', id, closeGap: true } })); });
  });
  $('undo').addEventListener('click', () => {
    if (!state.id || state.rev <= 1) return setStatus(tx('ui.khong-con-ban-truoc'));
    run(tx('ui.hoan-tac'), async () => afterChange(await post('revert', { baseRev: state.rev, rev: state.rev - 1 })));
  });

  return { renderIssues, renderModuleList, selectModule, clearSelection, onDesignOpened, shiftPick, clearGroup, inGroup };
}
