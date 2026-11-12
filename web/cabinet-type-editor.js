// The cabinet type editor (workshop): a type's name, storey and properties, its helper values and its steps as a table, a live preview of
// sample cabinets at a few widths (three.js) with what looks wrong, then save into the catalog. Opened from the catalog page.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import * as catalog from './catalog-client.js';
import { el } from './dom.js';
import { t } from './i18n.js';
import { STEP_KINDS, PART_TYPES, FRONT_KINDS, SPECIALS, rowsOf, partsOf, letsText, letsOf } from './cabinet-type-logic.js';

const VARIABLES = 'fromCorner endAt width height depth y top fs0 fs1 b0 b1 p0 p1 endPanel blindCorner niche shelfCount sections doors doorThickness doorGap plinthHeight';
const STOREYS = ['base', 'upper', 'loft', 'tall', 'corner'];
const FRONT_STYLES = ['slab', 'shaker', 'glass'];

let colours = null;
async function partColours() {
  if (!colours) {
    try { colours = (await catalog.list('palette', 'vi')).items.find((it) => it.id === 'display')?.data.colors || {}; } catch { colours = {}; }
  }
  return colours;
}

const select = (values, value, blank = false) => el('select', {}, ...(blank ? [el('option', { value: '', textContent: '—' })] : []),
  ...values.map((v) => el('option', { value: v, textContent: v, selected: v === value })));
const input = (value, size = 14, placeholder = '') => el('input', { value: value ?? '', size, placeholder });

/** A small three.js view of one sample cabinet's panels (mm, the cabinet's own frame). */
function previewCanvas(sample, palette) {
  const box = el('div', { className: 'ct-view' });
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(260, 240);
  box.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf4f1eb);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x888877, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.2); sun.position.set(1, 2, 3); scene.add(sun);
  const group = new THREE.Group(); scene.add(group);
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const p of sample.parts) {
    const size = p.max.map((v, i) => Math.max(1, v - p.min[i]) / 1000);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshStandardMaterial({ color: palette[p.type] || '#cccccc', roughness: 0.7 }));
    mesh.position.set(...p.min.map((v, i) => v / 1000 + size[i] / 2));
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: 0x333333 }));
    mesh.add(edges);
    group.add(mesh);
    p.min.forEach((v, i) => { lo[i] = Math.min(lo[i], v / 1000); hi[i] = Math.max(hi[i], p.max[i] / 1000); });
  }
  const centre = new THREE.Vector3(...lo.map((v, i) => (Number.isFinite(v) ? (v + hi[i]) / 2 : 0)));
  const span = Math.max(0.5, ...hi.map((v, i) => (Number.isFinite(v) ? v - lo[i] : 0)));
  const camera = new THREE.PerspectiveCamera(40, 260 / 240, 0.01, 50);
  camera.position.set(centre.x + span * 0.9, centre.y + span * 0.5, centre.z + span * 1.8);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(centre);
  const draw = () => renderer.render(scene, camera);
  controls.addEventListener('change', draw);
  controls.update(); draw();
  return el('figure', {}, box, el('figcaption', { textContent: t('catalog.type.sample', { 0: sample.width, 1: sample.height, 2: sample.depth }) }));
}

/** The step table: one editable row per step, with up / down / delete; `read()` gives the steps (throws on bad JSON in a repeat row). */
function stepTable(parts) {
  const rows = rowsOf(parts);
  const body = el('tbody');
  const nameField = (row) => (row.kind === 'part' ? select(PART_TYPES.includes(row.name) ? PART_TYPES : [...PART_TYPES, row.name], row.name)
    : row.kind === 'fronts' ? select(FRONT_KINDS, row.name) : row.kind === 'special' ? select(SPECIALS, row.name) : el('span'));
  const draw = () => {
    body.replaceChildren(...rows.map((row, i) => {
      const kind = select(STEP_KINDS, row.kind);
      kind.onchange = () => { row.kind = kind.value; row.name = { part: 'carcass', fronts: 'door', special: 'back-panel' }[row.kind] || ''; if (row.kind === 'repeat' && !row.json) row.json = '{"repeat": "1", "as": "i", "parts": []}'; draw(); };
      const name = nameField(row);
      if (name.tagName === 'SELECT') name.onchange = () => { row.name = name.value; };
      const cell = (key, size = 14) => { const x = input(row[key], size); x.oninput = () => { row[key] = x.value; }; return el('td', {}, x); };
      const tools = el('td', {}, el('button', { type: 'button', textContent: '↑', onclick: () => { if (i) { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; draw(); } } }),
        el('button', { type: 'button', textContent: '↓', onclick: () => { if (i < rows.length - 1) { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; draw(); } } }),
        el('button', { type: 'button', textContent: '✕', onclick: () => { rows.splice(i, 1); draw(); } }));
      if (row.kind === 'repeat') {
        const json = el('textarea', { value: row.json, rows: 3, cols: 70 }); json.oninput = () => { row.json = json.value; };
        return el('tr', {}, el('td', {}, kind), cell('when', 16), el('td', { colSpan: 7 }, json), tools);
      }
      const box = row.kind === 'part' ? [cell('s0'), cell('s1'), cell('d0', 10), cell('d1', 16), cell('y0'), cell('y1')]
        : [cell('s0'), cell('s1'), el('td'), el('td'), cell('y0'), cell('y1')];
      return el('tr', {}, el('td', {}, kind), cell('when', 16), el('td', {}, name), ...box, tools);
    }));
  };
  draw();
  const head = el('tr', {}, ...['kind', 'when', 'name', 's0', 's1', 'd0', 'd1', 'y0', 'y1', ''].map((k) => el('th', { textContent: k ? t('catalog.type.col.' + k) : '' })));
  const add = el('button', { type: 'button', textContent: t('catalog.type.addStep'), onclick: () => {
    rows.push({ kind: 'part', when: '', name: 'shelf', s0: 'fs0', s1: 'fs1', d0: '0', d1: 'depth', y0: 'y', y1: 'y + doorThickness', json: '' }); draw(); } });
  return { node: el('div', {}, el('table', { className: 'ct-steps' }, el('thead', {}, head), body), add), read: () => partsOf(rows) };
}

/**
 * Open the editor in `container`. item: the catalog item to edit ({id, data}) or to copy from (`copy` = the new id), null for a new type.
 * onSaved(id) is called after a save.
 */
export function openTypeEditor(container, { item, copy = '', onSaved, onError }) {
  const data = structuredClone(item?.data || { storey: 'base', label: { vi: '' }, parts: [] });
  const isNew = !item || !!copy;
  const id = input(copy || item?.id || '', 24, 'base-…');
  id.disabled = !isNew;
  const storey = select(STOREYS, data.storey);
  const labelVi = input(data.label?.vi, 24, 'vi'), labelEn = input(data.label?.en, 24, 'en');
  const checks = ['frontless', 'ownDoor', 'mainRunOnly'].map((k) => [k, el('input', { type: 'checkbox', checked: !!data[k] })]);
  const frontStyle = select(FRONT_STYLES, data.frontStyle || 'slab');
  const plainType = input(data.plainType, 14), exportType = input(data.exportType, 16), prompt = input(data.prompt, 32, 'sink base cabinet');
  const lets = el('textarea', { value: letsText(data.let), rows: 3, cols: 70 });
  const table = data.like || data.builder ? null : stepTable(data.parts);
  const views = el('div', { className: 'row' });
  const problems = el('ul');

  const read = () => {
    const out = { ...data, storey: storey.value, label: { vi: labelVi.value.trim(), ...(labelEn.value.trim() ? { en: labelEn.value.trim() } : {}) } };
    for (const [k, c] of checks) { if (c.checked) out[k] = true; else delete out[k]; }
    if (frontStyle.value !== 'slab') out.frontStyle = frontStyle.value; else delete out.frontStyle;
    for (const [k, x] of [['plainType', plainType], ['exportType', exportType], ['prompt', prompt]]) { if (x.value.trim()) out[k] = x.value.trim(); else delete out[k]; }
    const l = letsOf(lets.value);
    if (Object.keys(l).length) out.let = l; else delete out.let;
    if (table) out.parts = table.read();
    return out;
  };
  const preview = async () => {
    try {
      const r = await catalog.typePreview(id.value.trim(), read());
      const found = r.samples.flatMap((s) => s.problems);
      problems.replaceChildren(...(found.length ? found.map((p) => el('li', { className: 'warn', textContent: p.content })) : [el('li', { className: 'ok', textContent: t('catalog.type.noProblem') })]));
      const palette = await partColours();
      views.replaceChildren(...r.samples.map((s) => previewCanvas(s, palette)));      // the checks above show even where WebGL does not
    } catch (e) { onError(e); }
  };
  const save = async () => {
    try { await catalog.put('cabinet-type', id.value.trim(), read()); onSaved(id.value.trim()); } catch (e) { onError(e); }
  };
  const field = (key, ...nodes) => el('label', { className: 'row' }, el('b', { textContent: t('catalog.type.' + key) }), ...nodes);
  const form = el('form', { className: 'item' },
    el('h3', { textContent: t(isNew ? 'catalog.type.new' : 'catalog.type.edit') }),
    field('id', id, el('small', { className: 'muted', textContent: t('catalog.type.idRule') })),
    field('storey', storey), field('label', labelVi, labelEn),
    el('p', { className: 'row' }, ...checks.map(([k, c]) => el('label', { className: 'row' }, c, t('catalog.type.' + k)))),
    field('frontStyle', frontStyle), field('plainType', plainType), field('exportType', exportType), field('prompt', prompt),
    ...(data.like ? [el('p', { textContent: t('catalog.type.likeNote', { 0: data.like }) })] : []),
    ...(data.builder ? [el('p', { textContent: t('catalog.type.builderNote', { 0: data.builder }) })] : []),
    ...(table ? [field('let', lets), el('p', { className: 'muted', textContent: t('catalog.type.variables') + ': ' + VARIABLES }), table.node] : []),
    el('p', { className: 'row' }, el('button', { type: 'button', textContent: t('catalog.type.preview'), onclick: preview }),
      el('button', { type: 'submit', textContent: t('catalog.save') }), el('button', { type: 'button', textContent: t('catalog.cancel'), onclick: () => form.remove() })),
    problems, views);
  form.onsubmit = (ev) => { ev.preventDefault(); save(); };
  container.replaceChildren(form);
  form.scrollIntoView({ behavior: 'smooth' });
  if (item) preview();
}
