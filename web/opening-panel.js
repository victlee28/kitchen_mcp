// "Doors & windows" panel (plan slice 2): the design's room openings - the floorplan's and its own - in a list, a form to add or
// change one by its axes, preview before saving, and turning the floorplan's openings into the design's (drawn with frames and leaves).
// No context-menu entry is added (rule of 10/11/2026); the first command box of the context menu keeps creating doors at a click.
import { $, el } from './dom.js';
import { describeProposal } from './menu-logic.js';
import { FORM_FIELDS, adoptOp, axisLines, formFromOpening, newForm, openingRows, opFromForm, previewLines, removeOp, resetOp, standardWidths, unsureFields } from './opening-logic.js';
import { tx } from './i18n.js';

export function createOpeningPanel({ state, api, run, afterChange, showAxes = () => {} }) {
  let listed = { openings: [], wallAxes: [], problems: [] };
  let types = [];
  let current = null;            // {id, kind, before} of the opening in the form; id null = a new one
  const input = (name) => $(`op_${name}`);
  const kindLabel = (k) => tx(`ui.opening.kind.${k}`);

  async function load() {
    if (!state.id) return;
    const country = state.qg || state.spec?.country || '';
    [listed, types] = await Promise.all([api(`/api/designs/${state.id}/openings${country ? `?country=${encodeURIComponent(country)}` : ''}`),
      types.length ? types : api(`/api/opening-types${country ? `?country=${encodeURIComponent(country)}` : ''}`).then((r) => r.items || [])]);
    draw();
  }

  function draw() {
    const rows = openingRows(listed);
    $('opList').replaceChildren(...rows.map((r) => el('li', { className: current?.id === r.id ? 'sel' : '', onclick: () => edit(r.id),
      textContent: `${r.id} · ${kindLabel(r.kind)} · ${r.wallAxis} @${Math.round(r.center)} · ${Math.round(r.width)}×${Math.round(r.height)}`
        + (r.asDrawn ? ` · ${tx('ui.opening.as-drawn')}` : r.floorplan ? ` · ${tx('ui.opening.overridden', { 0: r.floorplan })}` : '')
        + (r.unsure.length ? ' ⚠' : '') })));
    if (!rows.length) $('opList').append(el('li', { className: 'muted', textContent: tx('ui.opening.none') }));
    $('opNote').textContent = (listed.problems || []).join(' · ');
    $('opAdopt').hidden = !rows.some((r) => r.asDrawn);
  }

  function fillSelects(kind, form) {
    $('op_openingType').replaceChildren(...types.filter((t) => t.kind === kind).map((t) => el('option', { value: t.id, textContent: t.label?.[document.documentElement.lang] || t.label?.en || t.id })));
    $('op_wallAxis').replaceChildren(...(listed.wallAxes || []).map((a) => el('option', { value: a.id, textContent: `${a.id} (${Math.round(a.length)} mm)` })));
    $('opWidths').replaceChildren(...standardWidths(types, form.openingType, state.qg || state.spec?.country).map((w) => el('option', { value: String(w) })));
  }

  function showForm(kind, form, unsure) {
    fillSelects(kind, form);
    for (const f of FORM_FIELDS) { const n = input(f); if (n) { n.value = form[f] ?? ''; n.classList.toggle('unsure', unsure.has(f)); } }
    $('opTitle').textContent = current.id ? `${current.id} · ${kindLabel(kind)}` : tx('ui.opening.new', { 0: kindLabel(kind) });
    $('opRemove').hidden = !current.id;
    $('opReset').hidden = !(current.id && listed.openings.find((o) => o.id === current.id)?.sourceElement);
    $('opPreview').replaceChildren();
    $('opForm').hidden = false;
    draw();
  }

  function edit(id) {
    const o = listed.openings.find((x) => x.id === id);
    if (!o) return;
    showAxes(axisLines(o, (listed.wallAxes || []).find((a) => a.id === o.wallAxis?.id), types.find((t) => t.id === o.openingType)));
    const form = formFromOpening(o, o.opens);
    current = { id: o.sourceElement && o.asDrawn ? o.sourceElement : o.id, kind: o.kind, before: form };
    showForm(o.kind, form, unsureFields(o.unsure));
  }

  function add(kind) {
    const axis = (listed.wallAxes || [])[0];
    current = { id: null, kind, before: null };
    showForm(kind, newForm(kind, types, axis), new Set());
  }

  const formValues = () => Object.fromEntries(FORM_FIELDS.map((f) => [f, input(f)?.value ?? '']));
  const operation = () => opFromForm(formValues(), { id: current.id, kind: current.kind, before: current.before });

  async function apply(op) {
    await afterChange(await api(`/api/designs/${state.id}/ops`, 'POST', { baseRev: state.rev, op }));
    current = null; $('opForm').hidden = true; showAxes([]);
  }

  $('opAddDoor').addEventListener('click', () => add('door'));
  $('opAddWindow').addEventListener('click', () => add('window'));
  $('opAdopt').addEventListener('click', () => run(tx('ui.opening.adopting'), () => apply(adoptOp())));
  $('op_openingType').addEventListener('change', () => { $('opWidths').replaceChildren(...standardWidths(types, input('openingType').value, state.qg || state.spec?.country).map((w) => el('option', { value: String(w) }))); });
  $('opCancel').addEventListener('click', () => { current = null; $('opForm').hidden = true; showAxes([]); draw(); });
  $('opRemove').addEventListener('click', () => current?.id && run(tx('ui.opening.removing'), () => apply(removeOp(current.id))));
  $('opReset').addEventListener('click', () => current?.id && run(tx('ui.opening.resetting'), () => apply(resetOp(current.id))));
  $('opShow').addEventListener('click', () => run(tx('ui.opening.previewing'), async () => {
    const p = await api(`/api/designs/${state.id}/propose`, 'POST', { baseRev: state.rev, op: operation() });
    $('opPreview').replaceChildren(...previewLines(describeProposal(p), tx).map((l) => el('li', { className: l.kind, textContent: l.text })));
  }));
  $('opForm').addEventListener('submit', (ev) => { ev.preventDefault(); run(tx('ui.opening.saving'), () => apply(operation())); });
  window.addEventListener('design-opened', () => { current = null; $('opForm').hidden = true; showAxes([]); run(tx('ui.opening.loading'), load); });
  return { load };
}
