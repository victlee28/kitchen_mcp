// Design editor: issue list, module list, module form and the add/remove/undo buttons.
// Owns the module selection (state.selected). Receives its dependencies; never imports app.js.
import { $, el } from './dom.js';
import { FIELDS, moduleOrder, moduleLabel, formChanges } from './design-logic.js';

export function createDesignEditor({ state, api, run, setStatus, afterChange, setViewerSelected }) {
  const post = (path, body) => api(`/api/designs/${state.id}/${path}`, 'POST', body);
  const findModule = (id) => state.spec?.module.find((x) => x.id === id);

  function renderIssues(v) {
    const ul = $('issues'); ul.replaceChildren();
    ul.append(el('li', { class: 'muted' }, `Áp tiêu chuẩn: ${v.country || v.region || 'toàn cầu (chưa chọn quốc gia)'}`));
    ul.append(el('li', { class: v.valid ? 'ok' : 'warn' }, v.valid ? `Hợp lệ · ${v.dem.warning} cảnh báo · ${v.dem.info} ghi chú` : `${v.dem.error} lỗi · ${v.dem.warning} cảnh báo`));
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
    for (const m of moduleOrder(state.spec.module)) {
      ul.append(el('li', { class: m.id === state.selected ? 'sel' : '', onclick: () => selectModule(m.id) },
        el('b', {}, m.id), ` ${moduleLabel(m)}`));
    }
  }

  function selectModule(id) {
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
    const had = state.selected;
    state.selected = null; setViewerSelected(null);
    $('moduleForm').hidden = true;
    if (redraw && had && state.spec) renderModuleList();
  }

  // A design was (re)loaded: redraw the panels and keep the selection if the module still exists.
  function onDesignOpened(validation) {
    renderIssues(validation); renderModuleList();
    if (state.selected && !findModule(state.selected)) state.selected = null;
    if (state.selected) selectModule(state.selected); else $('moduleForm').hidden = true;
  }

  $('moduleForm').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = ev.target; const m = findModule(state.selected);
    const changes = formChanges(m, Object.fromEntries(FIELDS.map(([k]) => [k, f.elements[k].value])), f.elements.doors.value);
    if (!Object.keys(changes).length) return setStatus('Không có thay đổi');
    run(`sửa ${m.id}`, async () => afterChange(await post('ops',
      { baseRev: state.rev, op: { op: 'update', id: m.id, changes, closeGap: f.elements.closeGap.checked } })));
  });
  $('addAfter').addEventListener('click', () => {
    const m = findModule(state.selected); if (!m) return;
    const width = Number(prompt('Bề rộng tủ mới (mm)', '600')); if (!width) return;
    run('thêm tủ', async () => afterChange(await post('ops',
      { baseRev: state.rev, op: { op: 'add', afterModule: m.id, module: { width, doors: width >= 600 ? [width / 2, width / 2] : [width] }, closeGap: true } })));
  });
  $('removeModule').addEventListener('click', () => {
    const id = state.selected; if (!id) return;
    run(`xóa ${id}`, async () => { state.selected = null; await afterChange(await post('ops', { baseRev: state.rev, op: { op: 'remove', id, closeGap: true } })); });
  });
  $('undo').addEventListener('click', () => {
    if (!state.id || state.rev <= 1) return setStatus('Không còn bản trước');
    run('hoàn tác', async () => afterChange(await post('revert', { baseRev: state.rev, rev: state.rev - 1 })));
  });

  return { renderIssues, renderModuleList, selectModule, clearSelection, onDesignOpened };
}
