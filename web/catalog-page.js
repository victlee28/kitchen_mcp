// Catalog management page: pick a kind, see the merged items with the layer each comes from, add / edit / hide / reset / undo, export and
// import the role's layer. The edit form is built from the kind's JSON Schema (x-label gives a field's name in each language); anything
// the form cannot show field by field is edited as JSON.
import { loadLang, t, pick, translate, languagePicker, lang } from './i18n.js';
import * as catalog from './catalog-client.js';
import { $, el } from './dom.js';
import { openTypeEditor } from './cabinet-type-editor.js';
import { openLayoutEditor } from './layout-template-editor.js';
import { copyId } from './cabinet-type-logic.js';
let current = null;      // kind shown
let listing = null;      // its listing from the server

function say(msg, kind = '') { $('status').textContent = msg; $('status').className = 'status ' + kind; }
function errorText(e) {
  const key = 'error.' + (e.data?.code || '');
  const known = t(key);
  return known !== key ? known.replace(/\{detail\}/, e.message).replace(/\{\w+\}/g, '') + (known.includes('{detail}') ? '' : ' — ' + e.message) : e.message;
}
async function guard(fn) { try { await fn(); } catch (e) { console.error(e); say(errorText(e), 'warn'); } }

function sourceTag(source) {
  const layer = source.startsWith('user:') ? 'user' : source;
  return el('span', { className: 'src ' + layer, textContent: t('catalog.source.' + layer) });
}
const labelOf = (key, prop) => (prop && prop['x-label'] ? pick(prop['x-label']) : key);
const isLocalized = (p) => p && p.type === 'object' && p.properties && 'vi' in p.properties && Object.keys(p.properties).every((k) => ['vi', 'en'].includes(k));
const resolve = (schema, p) => (p && p.$ref && p.$ref.startsWith('#/$defs/') ? schema.$defs?.[p.$ref.slice(8)] || p : p);

const swatch = (hex) => el('span', { style: `display:inline-block;width:12px;height:12px;background:${hex};border:1px solid #999;margin-right:4px` });
const MATERIAL_KINDS = ['material', 'material-word', 'material-look', 'style'];

function summary(data) {
  const name = data.name ? pick(data.name) : (data.word || data.text || (data.any ? data.any.join(', ') || '*' : ''));
  const hex = typeof data.hex === 'string' ? data.hex : typeof data.look?.color === 'string' ? data.look.color : null;
  return el('span', {}, ...(hex ? [swatch(hex)] : []), name, data.en ? ` → ${data.en}` : '', data.front ? ` · ${data.front}` : '');
}

/** Try a material name against the merged catalog: the English the prompts get, the display colour and the 3D look (stage 1.7). */
function materialTry() {
  const input = el('input', { type: 'text', placeholder: t('catalog.tryPlaceholder'), size: 32 });
  const out = el('span', {});
  const run = () => guard(async () => {
    const r = await catalog.materialPreview(input.value);
    const look = r.look || {};
    out.replaceChildren(swatch(look.color || '#ffffff'), `${t('catalog.tryEnglish')}: ${r.english || '—'} · ${t('catalog.tryColor')}: ${r.color || '—'} · `
      + `${t('catalog.tryLook')}: ${look.color || ''} roughness ${look.roughness ?? '—'}${look.metalness ? ` metalness ${look.metalness}` : ''}${look.transmission ? ' glass' : ''}`);
  });
  input.addEventListener('change', run);
  return el('p', { className: 'row' }, el('b', { textContent: t('catalog.try') }), input, el('button', { type: 'button', textContent: '▶', onclick: run }), out);
}

async function showKinds() {
  const kinds = await catalog.kinds(lang());
  $('kinds').replaceChildren(...kinds.map((k) => {
    const b = el('button', { textContent: `${k.label} (${k.count})`, className: k.kind === current ? 'on' : '' });
    b.onclick = () => guard(() => showKind(k.kind));
    return b;
  }));
  if (!current && kinds.length) await showKind(kinds[0].kind);
  if (!kinds.length) $('list').replaceChildren(el('p', { textContent: t('catalog.empty') }));
}

async function showKind(kind) {
  current = kind;
  listing = await catalog.list(kind, lang());
  const rows = listing.items.map((it) => {
    const actions = el('span', { className: 'row' });
    if (listing.writable) {
      actions.append(el('button', { textContent: t('catalog.edit'), onclick: () => edit(it) }));
      if (kind === 'cabinet-type' || kind === 'layout-template') actions.append(el('button', { textContent: t('catalog.type.copy'), onclick: () => typeEditor(it, copyId(it.id, listing.items.map((x) => x.id))) }));
      if (it.mine) actions.append(el('button', { textContent: it.builtin || it.source !== listing.scope ? t('catalog.reset') : '✕', onclick: () => guard(() => reset(it.id)) }));
      if (!it.mine || it.builtin) actions.append(el('button', { textContent: t('catalog.hide'), onclick: () => guard(() => hide(it.id)) }));
      actions.append(el('button', { textContent: '↶', title: t('catalog.undo'), onclick: () => guard(() => undo(it.id)) }));
    }
    return el('tr', {}, el('td', { textContent: it.id }), el('td', {}, summary(it.data)), el('td', {}, sourceTag(it.source)),
      el('td', { textContent: String(it.version) }), el('td', {}, actions));
  });
  const head = el('tr', {}, ...['catalog.id', '', '', 'catalog.version', ''].map((k) => el('th', { textContent: k ? t(k) : '' })));
  const parts = [el('h2', { textContent: listing.label }),
    listing.writable ? el('button', { textContent: t('catalog.add'), onclick: () => edit(null) }) : el('p', { className: 'muted', textContent: t('catalog.readonly') }),
    csvTools(listing),
    ...(MATERIAL_KINDS.includes(listing.kind) ? [materialTry()] : []),
    listing.items.length ? el('table', {}, head, ...rows) : el('p', { textContent: t('catalog.empty') })];
  if (listing.hidden.length) parts.push(el('p', { className: 'muted', textContent: t('catalog.hide') + ': ' + listing.hidden.join(', ') }));
  $('list').replaceChildren(...parts);
  $('editor').replaceChildren();
  await showKinds();
}

// ---- schema-driven form
function field(schema, key, prop, value) {
  const p = resolve(schema, prop) || {};
  const label = el('label', { textContent: labelOf(key, prop) + (schema.required?.includes(key) ? ' *' : '') });
  if (isLocalized(p)) {
    const inputs = ['vi', 'en'].map((lg) => el('input', { placeholder: lg, value: value?.[lg] ?? '', 'data-lg': lg }));
    return { node: el('div', {}, label, el('div', { className: 'row' }, ...inputs)), read: () => {
      const out = {}; inputs.forEach((i) => { if (i.value.trim()) out[i.dataset.lg] = i.value.trim(); }); return Object.keys(out).length ? out : undefined; } };
  }
  if (p.enum) {
    const s = el('select', {}, el('option', { value: '', textContent: '—' }), ...p.enum.map((v) => el('option', { value: v, textContent: String(v), selected: v === value })));
    return { node: el('div', {}, label, s), read: () => (s.value === '' ? undefined : s.value) };
  }
  if (p.type === 'boolean') {
    const c = el('input', { type: 'checkbox', checked: !!value });
    return { node: el('div', {}, label, c), read: () => c.checked };
  }
  if (p.type === 'number' || p.type === 'integer') {
    const n = el('input', { type: 'number', value: value ?? '', step: p.type === 'integer' ? '1' : 'any', min: p.minimum ?? undefined, max: p.maximum ?? undefined });
    return { node: el('div', {}, label, n), read: () => (n.value === '' ? undefined : Number(n.value)) };
  }
  if (p.type === 'string' && p['x-widget'] === 'color') {
    const c = el('input', { type: 'color', value: value || '#ffffff' });
    return { node: el('div', {}, label, c), read: () => c.value };
  }
  if (p.type === 'string') {
    const s = el('input', { value: value ?? '', pattern: p.pattern || undefined });
    return { node: el('div', {}, label, s), read: () => (s.value === '' ? undefined : s.value) };
  }
  const area = el('textarea', { value: value === undefined ? '' : JSON.stringify(value, null, 1) });
  return { node: el('div', {}, label, area), read: () => (area.value.trim() ? JSON.parse(area.value) : undefined) };
}

/** A cabinet type opens its own editor (steps table, 3D preview, checks); the other kinds the form built from their schema. */
function typeEditor(item, copy = '') {
  const open = current === 'layout-template' ? openLayoutEditor : openTypeEditor;
  open($('editor'), { item, copy, onError: (e) => say(errorText(e), 'warn'),
    onSaved: (id) => guard(async () => { say(t('catalog.saved', { kind: listing.label, id }), 'ok'); await showKind(current); }) });
}

function edit(item) {
  if (current === 'cabinet-type' || current === 'layout-template') return typeEditor(item);
  const schema = listing.schema;
  const props = schema.properties || {};
  const idInput = el('input', { value: item?.id ?? '', disabled: !!item, pattern: '[A-Za-z0-9_.:-]{1,64}' });
  const fields = Object.entries(props).map(([k, p]) => [k, field(schema, k, p, item?.data?.[k])]);
  const raw = el('textarea', { value: JSON.stringify(item?.data ?? {}, null, 1), hidden: true });
  const toggle = el('button', { type: 'button', textContent: t('catalog.json') });
  toggle.onclick = () => { raw.hidden = !raw.hidden; };
  const read = () => {
    if (!raw.hidden) return JSON.parse(raw.value);
    const out = { ...(item?.data || {}) };
    for (const [k, f] of fields) { const v = f.read(); if (v === undefined) delete out[k]; else out[k] = v; }
    return out;
  };
  const form = el('form', { className: 'item' }, el('label', { textContent: t('catalog.id') }), idInput, ...fields.map(([, f]) => f.node), toggle, raw,
    el('p', { className: 'row' }, el('button', { type: 'submit', textContent: t('catalog.save') }), el('button', { type: 'button', textContent: t('catalog.cancel'), onclick: () => form.remove() })));
  form.onsubmit = (ev) => { ev.preventDefault(); guard(async () => {
    const id = idInput.value.trim();
    await catalog.put(current, id, read());
    say(t('catalog.saved', { kind: listing.label, id }), 'ok');
    await showKind(current);
  }); };
  $('editor').replaceChildren(form);
  form.scrollIntoView({ behavior: 'smooth' });
}

async function reset(id) { await catalog.remove(current, id); say(t('catalog.deleted', { kind: listing.label, id }), 'ok'); await showKind(current); }
async function hide(id) { await catalog.put(current, id, {}, true); await showKind(current); }
async function undo(id) { await catalog.undo(current, id); await showKind(current); }

/** CSV of the kind (every merged item; a spreadsheet can edit it) and, for a writable kind, reading one back into the role's layer. */
function csvTools(listing) {
  const kind = listing.kind;
  const down = el('button', { type: 'button', textContent: t('catalog.csvExport'), onclick: () => guard(async () => {
    const csv = await catalog.csvOf(kind);
    el('a', { href: URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv' })), download: `${kind}.csv` }).click();
  }) });
  if (!listing.writable) return el('p', { className: 'row' }, down);
  const up = el('input', { type: 'file', accept: '.csv,text/csv' });
  up.onchange = () => guard(async () => {
    const file = up.files[0]; if (!file) return;
    const r = await catalog.importCsv(kind, await file.text());
    say(`${t('catalog.csvImport')}: ${r.imported}`, 'ok');
    await showKinds(); await showKind(kind);
  });
  return el('p', { className: 'row' }, down, el('label', { className: 'row' }, el('span', { textContent: t('catalog.csvImport') }), up));
}

async function start() {
  await loadLang();
  translate();
  const roleSel = $('role');
  [...roleSel.options].forEach((o) => { o.textContent = t('role.' + o.value); o.selected = o.value === catalog.role(); });
  roleSel.onchange = () => guard(async () => { catalog.setRole(roleSel.value); await showKinds(); if (current) await showKind(current); });
  $('langSlot').append(languagePicker(() => guard(async () => { translate(); [...roleSel.options].forEach((o) => { o.textContent = t('role.' + o.value); }); await showKinds(); if (current) await showKind(current); })));
  $('export').onclick = () => guard(async () => {
    const data = await catalog.exportLayer();
    const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' })), download: `catalog-${data.scope.replace(':', '-')}.json` });
    a.click();
  });
  $('import').onchange = (ev) => guard(async () => {
    const file = ev.target.files[0]; if (!file) return;
    const r = await catalog.importLayer(JSON.parse(await file.text()));
    say(`${t('catalog.import')}: ${r.imported}`, 'ok');
    await showKinds(); if (current) await showKind(current);
  });
  await showKinds();
}
guard(start);
