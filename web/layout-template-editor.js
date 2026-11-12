// The layout template editor (workshop and user): a template's name, the walls it uses, its values ("name = formula") and steps (corner
// cabinet, base run, corner shelf, wall cabinet run), island / peninsula; a preview of sample kitchens at three back wall lengths seen from
// above, with the notes the layout made; then save into the catalog. Opened from the catalog page.
import * as catalog from './catalog-client.js';
import { el } from './dom.js';
import { t } from './i18n.js';
import { letsText, letsOf } from './cabinet-type-logic.js';
import { STEP_DOS, WALLS, FIELDS, rowsOf, stepsOf, topView } from './layout-template-logic.js';

const NAMES = 'back right left g upperDepth fridge lr islandLength aisle';
const COLOURS = { base: '#c9a777', tall: '#8b6b45', upper: '#d9d2c3', loft: '#e8e3d8', corner: '#b8c4a8' };
const SVG = 'http://www.w3.org/2000/svg';

const input = (value, size = 14, placeholder = '') => el('input', { value: value ?? '', size, placeholder });
const select = (values, value) => el('select', {}, ...values.map((v) => el('option', { value: v, textContent: v, selected: v === value })));

function svgOf(sample) {
  const view = topView(sample.parts.filter((p) => ['base', 'tall', 'corner'].includes(p.storey)), 260);
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('width', view.width); svg.setAttribute('height', view.height);
  svg.setAttribute('style', 'background:#f4f1eb;border:1px solid #ccc;border-radius:4px');
  for (const r of view.rects) {
    const rect = document.createElementNS(SVG, 'rect');
    for (const [k, v] of Object.entries({ x: r.x, y: r.y, width: r.w, height: r.h, fill: COLOURS[r.storey] || '#ccc', stroke: '#555', 'stroke-width': 0.4 })) rect.setAttribute(k, v);
    svg.append(rect);
  }
  const counts = {};
  for (const m of sample.modules) counts[m.type] = (counts[m.type] || 0) + 1;
  return el('figure', {}, svg, el('figcaption', { textContent: t('catalog.layout.sample', { 0: sample.back }) }),
    el('small', { textContent: Object.entries(counts).map(([k, n]) => `${k} ×${n}`).join(', ') }),
    ...sample.notes.map((n) => el('div', { className: n.status === 'built' ? 'muted' : 'warn', textContent: n.message })));
}

function stepTable(steps) {
  const rows = rowsOf(steps);
  const body = el('tbody');
  const draw = () => {
    body.replaceChildren(...rows.map((row, i) => {
      const kind = select(STEP_DOS, row.do);
      kind.onchange = () => { rows[i] = { do: kind.value, wall: row.wall }; draw(); };
      const wall = select(WALLS, row.wall); wall.onchange = () => { row.wall = wall.value; };
      const fields = (FIELDS[row.do] || []).map(([key, how]) => {
        const x = how === 'json' ? el('textarea', { value: row[key] ?? '', rows: 1, cols: 34 }) : input(row[key], how === 'list' ? 10 : 16);
        x.oninput = () => { row[key] = x.value; };
        return el('label', { className: 'row' }, el('small', { textContent: t('catalog.layout.f.' + key) }), x);
      });
      const tools = el('span', {}, el('button', { type: 'button', textContent: '↑', onclick: () => { if (i) { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; draw(); } } }),
        el('button', { type: 'button', textContent: '↓', onclick: () => { if (i < rows.length - 1) { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; draw(); } } }),
        el('button', { type: 'button', textContent: '✕', onclick: () => { rows.splice(i, 1); draw(); } }));
      return el('tr', {}, el('td', {}, kind), el('td', {}, row.do === 'corner-shelf' ? el('span') : wall), el('td', { className: 'row' }, ...fields), el('td', {}, tools));
    }));
  };
  draw();
  const add = el('button', { type: 'button', textContent: t('catalog.layout.addStep'), onclick: () => { rows.push({ do: 'upper-run', wall: 'back', start: '0', end: 'back' }); draw(); } });
  return { node: el('div', {}, el('table', { className: 'ct-steps' }, body), add), read: () => stepsOf(rows) };
}

/** Open the editor in `container`. item: the catalog item to edit, or to copy from (`copy` = the new id); null for a new template. */
export function openLayoutEditor(container, { item, copy = '', onSaved, onError }) {
  const data = structuredClone(item?.data || { label: { vi: '' }, walls: ['back'], steps: [] });
  const isNew = !item || !!copy;
  const id = input(copy || item?.id || '', 24, 'I-…'); id.disabled = !isNew;
  const labelVi = input(data.label?.vi, 24, 'vi'), labelEn = input(data.label?.en, 24, 'en');
  const wallChecks = WALLS.map((w) => [w, el('input', { type: 'checkbox', checked: (data.walls || ['back']).includes(w) })]);
  const vars = el('textarea', { value: letsText(data.vars), rows: 3, cols: 70 });
  const room = input(data.room, 20), uses = input(data.peninsulaUses, 8);
  const islandStart = input(data.island?.start, 28), islandLength = input(data.island?.length, 40);
  const penAt = input(data.peninsula?.at, 14), penRoom = input(data.peninsula?.room, 20);
  const table = stepTable(data.steps);
  const options = ['fridge', 'loft', 'island', 'peninsula'].map((k) => [k, el('input', { type: 'checkbox' })]);
  const views = el('div', { className: 'row' });

  const read = () => {
    const out = { ...data, label: { vi: labelVi.value.trim(), ...(labelEn.value.trim() ? { en: labelEn.value.trim() } : {}) },
      walls: wallChecks.filter(([, c]) => c.checked).map(([w]) => w), steps: table.read() };
    const v = letsOf(vars.value);
    if (Object.keys(v).length) out.vars = v; else delete out.vars;
    for (const [k, x] of [['room', room], ['peninsulaUses', uses]]) { if (x.value.trim()) out[k] = x.value.trim(); else delete out[k]; }
    if (islandStart.value.trim() && islandLength.value.trim()) out.island = { start: islandStart.value.trim(), length: islandLength.value.trim() }; else delete out.island;
    if (penAt.value.trim() && penRoom.value.trim()) out.peninsula = { at: penAt.value.trim(), room: penRoom.value.trim() }; else delete out.peninsula;
    return out;
  };
  const preview = async () => {
    try {
      const r = await catalog.layoutPreview(id.value.trim(), read(), Object.fromEntries(options.map(([k, c]) => [k, c.checked])));
      views.replaceChildren(...r.samples.map(svgOf));
    } catch (e) { onError(e); }
  };
  const save = async () => { try { await catalog.put('layout-template', id.value.trim(), read()); onSaved(id.value.trim()); } catch (e) { onError(e); } };
  const field = (key, ...nodes) => el('label', { className: 'row' }, el('b', { textContent: t('catalog.layout.' + key) }), ...nodes);
  const form = el('form', { className: 'item' },
    el('h3', { textContent: t(isNew ? 'catalog.layout.new' : 'catalog.layout.edit') }),
    field('id', id), field('label', labelVi, labelEn),
    field('walls', ...wallChecks.map(([w, c]) => el('label', { className: 'row' }, c, w))),
    field('vars', vars), el('p', { className: 'muted', textContent: t('catalog.type.variables') + ': ' + NAMES }),
    table.node,
    field('island', islandStart, islandLength), field('peninsula', penAt, penRoom), field('room', room), field('peninsulaUses', uses),
    el('p', { className: 'row' }, el('b', { textContent: t('catalog.layout.try') }), ...options.map(([k, c]) => el('label', { className: 'row' }, c, t('catalog.layout.opt.' + k))),
      el('button', { type: 'button', textContent: t('catalog.type.preview'), onclick: preview }),
      el('button', { type: 'submit', textContent: t('catalog.save') }), el('button', { type: 'button', textContent: t('catalog.cancel'), onclick: () => form.remove() })),
    views);
  form.onsubmit = (ev) => { ev.preventDefault(); save(); };
  container.replaceChildren(form);
  form.scrollIntoView({ behavior: 'smooth' });
  if (item) preview();
}
