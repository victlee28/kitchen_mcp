// Context menu on a cabinet module in the 3D view: pick an action, fill a small form, preview what it would change, confirm.
// The server decides what a change means (POST .../propose previews, POST .../ops saves); nothing here edits data directly.
import { el } from './dom.js';
import { request } from './api-client.js';
import { interpretBody, describeInterpret, templateIntent, systemIntent, mentionsReference, checkUpload, recognizeBody, recognizeJobBody, anchorFor, describeRecognition, recognitionLines } from './assist-logic.js';
import { actionsFor, buildGroupOp, buildOp, describeProposal, groupActions, layerFor, lineTemplate, menuPosition, DOOR_STYLES, HANDLE_VARIANTS, RUN_ACTIONS, RUN_TURNS, systemTemplate, edgeChoices, modelChoices, applianceLayer, lineAlongWall, wallSegments } from './menu-logic.js';
import { groupLabel, groupLayerIds, manySystems } from './design-logic.js';
import * as catalog from './catalog-client.js';
import { applianceName, lang, tx } from './i18n.js';

let styles = [];                     // the style presets of a whole cabinet system (catalog kind "style"), named in a sentence
catalog.list('style', lang()).then((d) => {
  styles = d.items.map((it) => ({ id: it.id, names: [it.data.name?.vi, it.data.name?.en].filter(Boolean) }));
}).catch(() => { /* a preset can still be picked by "phong cách khác" */ });

const call = (path, body) => request(path, 'POST', body);
const JOB_KEY = 'recogJob';
// the waiting job and where its run will stand ({job, anchor, mode}); the anchor is the object picked when the picture was sent
function readJob() { try { const v = JSON.parse(localStorage.getItem(JOB_KEY) || 'null'); return v && typeof v.job === 'string' ? v : null; } catch { return null; } }
function keepJob(v) { try { if (v) localStorage.setItem(JOB_KEY, JSON.stringify(v)); else localStorage.removeItem(JOB_KEY); } catch { /* no storage: the job lives until the page closes */ } }

/**
 * ctx: { box, getState() -> {id, rev, spec}, afterChange(result), reload(), imageEdit({layer, material}), structure: {hide, isolate, showAll}, setStatus, keepOpenOn?(node) -> true when a press there must not close the popup (the 3D view decides on click) }
 */
export function createModuleMenu(ctx) {
  const box = ctx.box;
  const saved = readJob();
  let pendingJob = saved?.job ?? null; let pendingPlace = { anchor: saved?.anchor ?? null, mode: saved?.mode ?? 'add' }; let recMode = 'add';   // a recognition waiting for Claude (inbox mode): survives closing the menu and reloading the page
  let target = null; let step = null; let busy = false; let previewOfJob = null; let attached = null;   // attached: the picture chosen with 📎, sent together with the sentence when "Xem trước" is pressed   // picking: the native file dialog is open (the window blurs, the menu must stay)
  let lineFrom = null;
  let lastAppliance = null;   // the appliance model being previewed: once applied, the image tab opens on it      // first point of a run being drawn on the floor (mm); survives closing the menu, the second right click ends the line
  box.setAttribute('role', 'dialog'); box.hidden = true;

  const close = () => { box.hidden = true; box.replaceChildren(); target = null; step = null; busy = false; attached = null; ctx.guide?.(lineFrom); };   // a line being drawn goes back to following the pointer
  const header = (text) => el('div', { class: 'ctx-head' }, text, el('button', { type: 'button', class: 'ctx-x', title: tx('ui.dong-esc'), onclick: close }, '×'));
  const err = (text) => el('p', { class: 'ctx-msg bad', role: 'alert' }, text);

  function place(x, y) {
    box.hidden = false;
    const { left, top } = menuPosition(x, y, box.offsetWidth || 300, box.offsetHeight || 220, window.innerWidth, window.innerHeight);
    box.style.left = `${left}px`; box.style.top = `${top}px`;
  }

  // The menu of a Shift-selected group: changes for every module of it, and the image tab with the same group.
  function listGroup() {
    const g = target.group;
    box.onkeydown = null;
    box.replaceChildren(header(tx('ui.nhom-2', { 0: groupLabel(g) })), el('ul', { class: 'ctx-list' }, ...groupActions(g).map((a) =>
      el('li', {}, el('button', { type: 'button', onclick: () => choose(a.id) }, a.label)))));
  }

  const actionList = (spec) => (target.group ? groupActions(target.group) : actionsFor(target, spec));

  function list() {
    if (target.group) return listGroup();
    const { spec } = ctx.getState();
    const partName = { door: tx('ui.canh-2'), drawer: tx('ui.mat-ngan-keo-2'), handle: tx('ui.tay-nam-3'), countertop: tx('ui.mat-ban-2') }[target.part];
    const appl = target.kind === 'appliance' ? spec.appliances?.find((a) => a.id === target.id) : null;
    const title = appl ? `${applianceName(appl.type)} ${appl.id}${appl.name ? ` · ${appl.name}` : ''}` : target.kind === 'part' ? (target.part === 'countertop' ? tx('ui.mat-ban-2') : `${partName} · ${target.id}`)
      : target.kind === 'module' ? `Module ${target.id}` : target.kind === 'floor' ? (lineFrom ? tx('ui.san-dang-ve-day-tu') : tx('ui.san-2'))
        : tx('ui.thanh-phan-mat-bang', { 0: target.id.replace(/^STRUCT-/, '') });
    box.onkeydown = null;
    const cmd = target.kind === 'floor' ? null : commandBox();
    box.replaceChildren(header(title), ...(cmd ? [cmd] : []), el('ul', { class: 'ctx-list' }, ...actionsFor(target, spec, lineFrom).map((a) =>
      el('li', {}, el('button', { type: 'button', onclick: () => choose(a.id) }, a.label)))));
  }

  // A free sentence about THIS module (a floorplan object has no module: the sentence then covers the whole design) ("đổi sang màu trắng", "rộng 800"): the server reads it, the preview shows the result, nothing is saved before Áp dụng.
  function commandBox(text = '', message = '', choices = []) {
    const input = el('input', { type: 'text', value: text, placeholder: target.kind === 'structure' ? tx('ui.ra-lenh-cho-ca-thiet-ke-enter') : target.kind === 'appliance' ? tx('ui.vd-doi-sang-bep-gas-thay-chau') : tx('ui.ra-lenh-cho-enter', { 0: target.id }), autocomplete: 'off', 'aria-label': tx('ui.cau-lenh-cho-module-nay') });
    const run = () => (attached ? recognizeImage(attached.file, attached.kind, input.value) : command(input.value));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); run(); } });
    const kind = el('select', { 'aria-label': tx('ui.loai-anh-tham-chieu'), title: tx('ui.loai-anh-tham-chieu') }, el('option', { value: 'photo' }, tx('ui.anh-chup')), el('option', { value: 'drawing' }, tx('ui.ban-ve')));
    const mode = el('select', { 'aria-label': tx('ui.cach-dat-day-tu-nhan-dien'), title: tx('ui.them-day-tu-vao-cac-tu-hien') },
      el('option', { value: 'add' }, tx('ui.them-vao')), el('option', { value: 'replace' }, tx('ui.thay-tu-cu')));
    mode.value = recMode;
    mode.addEventListener('change', () => { recMode = mode.value; });
    const file = el('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true });
    file.addEventListener('change', () => {
      if (file.files[0]) { attached = { file: file.files[0], kind: kind.value }; redraw(input.value, ''); }
    });
    kind.addEventListener('change', () => { if (attached) attached.kind = kind.value; });
    if (attached) kind.value = attached.kind;
    const attach = el('button', { type: 'button', class: 'ghost', title: tx('ui.nhap-anh-chup-bep-hoac-ban-ve'), onclick: () => file.click() }, tx('ui.anh-tham-chieu'));
    const chip = attached ? el('div', { class: 'ctx-pending' }, el('span', {}, tx('ui.bam-xem-truoc-de-nhan-dien', { 0: attached.file.name })),
      el('button', { type: 'button', class: 'ghost small', title: tx('ui.bo-anh'), onclick: () => { attached = null; redraw(input.value, ''); } }, tx('ui.bo-anh'))) : null;
    const waiting = pendingJob ? el('div', { class: 'ctx-pending' },
      el('span', {}, tx('ui.job-dang-cho-claude', { 0: pendingJob })),
      el('button', { type: 'button', class: 'primary', title: tx('ui.lay-ket-qua-claude-da-tra-loi'), onclick: () => updateJob(input.value) }, tx('ui.cap-nhat')),
      el('button', { type: 'button', class: 'ghost small', title: tx('ui.bo-job-nay'), onclick: () => { setJob(null); redraw(input.value, ''); } }, tx('ui.bo'))) : null;
    return el('div', { class: 'ctx-cmd' }, input, el('button', { type: 'button', class: 'primary', onclick: run }, tx('ui.xem-truoc')), attach, kind, mode, file,
      ...(chip ? [chip] : []), ...(waiting ? [waiting] : []),
      ...(message ? [el('p', { class: 'ctx-msg warn' }, message)] : []),
      ...(choices.length ? [el('div', { class: 'chips' }, ...choices.map((c) => el('button', { type: 'button', class: 'ghost small', onclick: () => command(`${input.value.trim()} ${c}`) }, c)))] : []));
  }

  async function command(text) {
    if (busy) return; const { id, rev } = ctx.getState();
    if (mentionsReference(text)) return redraw(text, tx('ui.cau-lenh-nhac-toi-anh-tham-chieu'));
    if (target.kind === 'appliance') return applianceModels(text);
    const wish = target.kind === 'structure' ? null : systemIntent(text, styles);
    if (wish) return replaceSystem(text, wish);
    const intent = templateIntent(text);
    if (intent?.kind === 'shape') return redraw(text, tx('ui.chua-tao-duoc-tu-chu-bang-lenh', { 0: intent.shape }));
    if (intent?.kind === 'run-i') {
      if (target.kind === 'structure') return runI(text);
      if (!intent.described) return redraw(text, tx('ui.muon-tao-day-tu-doc-mot-canh'));
    }
    let body;
    try { body = interpretBody(text, rev, { scope: target.kind === 'structure' ? undefined : [target.id] }); } catch (e) { return ctx.setStatus(e.message, 'warn'); }
    busy = true; ctx.setStatus(tx('ui.doc-cau-lenh-2'));
    try {
      const { status, data } = await call(`/api/designs/${id}/interpret`, body);
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error) return redraw(text, data?.error || tx('ui.loi', { 0: status }));
      const d = describeInterpret(data);
      if (d.kind === 'preview') return showPreview('cmd', d.proposal, null, d.summary);
      redraw(text, d.kind === 'clarify' ? d.question : d.message, d.kind === 'clarify' ? d.choices : []);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  function fileBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(',')[1] || '');
      r.onerror = () => reject(new Error(tx('ui.khong-doc-duoc-tep')));
      r.readAsDataURL(file);
    });
  }

  function setJob(job, placeAt = { anchor: null, mode: 'add' }) { pendingJob = job; pendingPlace = placeAt; keepJob(job ? { job, ...placeAt } : null); }

  // Shared by "Xem trước" with an image and by "Cập nhật": the answer is a preview, a message, or "pending" (the job still waits for Claude).
  function showRecognition(data, text, placeAt) {
    const d = describeRecognition(data);
    if (d.kind === 'pending') { setJob(d.job, placeAt); return redraw(text, d.text); }
    if (data.status === 'empty') setJob(null);
    if (d.kind !== 'preview') return redraw(text, d.text);
    previewOfJob = pendingJob;       // applying this preview finishes the job
    showPreview('cmd', d.proposal, null, [{ kind: 'warn', text: warning(data) }, ...(data.summary || []), ...recognitionLines(data)]);
  }

  function warning(data) {
    if (!data.structureId) return tx('ui.ket-qua-nhan-dien-se-thay-toan');
    return data.mode === 'replace' ? tx('ui.cac-tu-hien-co-se-bi-thay')
      : tx('ui.day-tu-nhan-dien-duoc-se-duoc');
  }

  async function recognizeImage(file, kind, text) {
    if (busy) return; const { id, rev } = ctx.getState();
    const bad = checkUpload(file); if (bad) return redraw(text, bad);
    const anchor = anchorFor(target);
    if (!anchor) return redraw(text, tx('ui.hay-chuot-phai-vao-mot-canh-vat'));
    busy = true; ctx.setStatus(tx('ui.nhan-dien-anh-tham-chieu'));
    try {
      const { status, data } = await call(`/api/designs/${id}/recognize`, recognizeBody(kind, file.name, file.type, await fileBase64(file), rev, text, anchor, recMode));
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error) return redraw(text, data?.error || tx('ui.loi', { 0: status }));
      attached = null;
      showRecognition(data, text, { anchor, mode: recMode });
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  async function updateJob(text) {
    if (busy || !pendingJob) return; const { id, rev } = ctx.getState();
    busy = true; ctx.setStatus(tx('ui.lay-ket-qua-cua-job'));
    try {
      const { status, data } = await call(`/api/designs/${id}/recognize-job`, recognizeJobBody(pendingJob, rev, pendingPlace.anchor, pendingPlace.mode));
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error) return redraw(text, data?.error || tx('ui.loi', { 0: status }));
      showRecognition(data, text, pendingPlace);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  function redraw(text, message, choices = []) {
    const old = box.querySelector('.ctx-cmd');
    const fresh = commandBox(text, message, choices);
    if (old) old.replaceWith(fresh); else list();
    fresh.querySelector('input')?.focus();
  }

  function choose(action) {
    if (action === 'run-i') return runI();
    if (action === 'line-start') { lineFrom = { ...target.point }; close(); return ctx.setStatus(tx('ui.da-dat-diem-dau-cua-day-tu'), 'ok'); }
    if (action === 'line-cancel') { lineFrom = null; close(); return ctx.setStatus(tx('ui.da-bo-day-dang-ve')); }
    if (action === 'line-end') return lineForm();
    if (action === 'struct-hide') { ctx.structure.hide(); return close(); }
    if (action === 'struct-isolate') { ctx.structure.isolate(); return close(); }
    if (action === 'struct-all') { ctx.structure.showAll(); return close(); }
    if (action === 'image' && target.group) {
      const ids = groupLayerIds(target.group, manySystems(ctx.getState().systems)); close();
      return ctx.imageEdit({ layer: ids[0], alts: ids.slice(1) });
    }
    if (action === 'image') { const id = target.id; close(); return ctx.imageEdit({ layer: layerFor('image', id), module: id }); }
    form(action);
  }

  // The second point of a drawn run: which side the doors look at, and optionally what stands in it; the server makes the run, the preview shows it.
  function lineForm(message = '', keep = {}) {
    const from = lineFrom; const to = { ...target.point };
    ctx.guide?.(from, to);
    const len = Math.round(Math.hypot(to.x - from.x, to.z - from.z));
    const side = el('select', {}, el('option', { value: 'left' }, tx('ui.ben-trai-huong-ve')), el('option', { value: 'right' }, tx('ui.ben-phai-huong-ve')));
    side.value = keep.side || 'left';
    const text = el('input', { type: 'text', value: keep.text || '', placeholder: tx('ui.de-trong-toan-tu-duoi-vd-co'), autocomplete: 'off' });
    const out = el('div', { class: 'ctx-msg' }); if (message) out.append(err(message));
    const go = el('button', { type: 'button', class: 'primary', onclick: () => drawRun(from, to, side.value, text.value) }, tx('ui.xem-truoc'));
    const along = lineAlongWall(from, to, wallSegments(ctx.getState().doc));     // the server turns the backs to the wall: nothing to ask
    const facing = along ? el('p', { class: 'ctx-msg' }, tx('ui.day-chay-sat-tuong-lung-tu-tu')) : el('label', {}, tx('ui.canh-tu-quay-ra'), side);
    box.replaceChildren(header(tx('ui.day-tu-moi-dai-mm', { 0: len })), facing, el('label', {}, tx('ui.trong-day-co-gi-khong-bat-buoc'), text), out,
      el('div', { class: 'row' }, go, el('button', { type: 'button', class: 'ghost', onclick: list }, tx('ui.quay-lai'))));
    box.onkeydown = (e) => { if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); go.click(); } };
    go.focus();
  }

  async function drawRun(from, to, side, text) {
    if (busy) return; const { id, rev } = ctx.getState();
    let template;
    try { template = lineTemplate(from, to, side, text); } catch (e) { return lineForm(e.message, { side, text }); }
    busy = true; ctx.setStatus(tx('ui.tinh-day-tu-tren-duong-vua-ve'));
    try {
      const { status, data } = await call(`/api/designs/${id}/template`, { template, baseRev: rev });
      busy = false;
      if (status === 409) return stale('run-line');
      if (!data || data.error || !data.proposal) return lineForm(data?.error || tx('ui.loi', { 0: status }), { side, text });
      showPreview('run-line', data.proposal, null, data.summary || []);
    } catch (e) { busy = false; lineForm(e.message, { side, text }); }
  }

  // "Thay cả hệ tủ …" typed in the command box: the clicked cabinet's whole system, laid out again from what follows, or restyled when nothing does.
  async function replaceSystem(text, wish) {
    if (busy) return; const { id, rev, systems } = ctx.getState();
    let template;
    try { template = systemTemplate(systems?.[target.id]?.system, wish.prompt, wish.style, styles.length ? styles : null); } catch (e) { return redraw(text, e.message); }
    busy = true; ctx.setStatus(template.prompt ? tx('ui.xep-lai-ca-he-tu-theo-mo') : tx('ui.doi-phong-cach-ca-he-tu'));
    try {
      const { status, data } = await call(`/api/designs/${id}/template`, { template, baseRev: rev });
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error || !data.proposal) return redraw(text, data?.error || tx('ui.loi', { 0: status }));
      showPreview('cmd', data.proposal, null, data.summary || []);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  function form(action, message) {
    const { spec } = ctx.getState();
    const m = spec.module.find((x) => x.id === target.id);
    const f = {}; const fields = [];
    if (action === 'countertopMaterial' || action === 'handleMaterial') {
      f.material = el('input', { type: 'text', value: action === 'handleMaterial' ? (m?.handle?.material || spec.common?.handle?.material || '') : (spec.common?.material?.countertop || ''),
        placeholder: action === 'handleMaterial' ? tx('ui.vd-nhom-den-mo') : tx('ui.vd-da-granite-toi'), autocomplete: 'off' });
      fields.push(el('label', {}, action === 'handleMaterial' ? tx('ui.vat-lieu-tay-nam') : tx('ui.vat-lieu-mat-ban'), f.material));
    } else if (action === 'countertopOverhang') {
      f.overhang = el('input', { type: 'number', min: 0, max: 100, step: 5, value: spec.common?.countertopOverhang ?? 20 });
      fields.push(el('label', {}, tx('ui.do-nho-phia-truoc-mm'), f.overhang));
    } else if (action === 'handleVariant') {
      const storey = ctx.getState().systems?.[m?.id]?.storey;      // the spec JSON has no storey: the server sends it with the systems
      const current = m?.handle?.variant || spec.common?.handleByStorey?.[storey]?.variant || spec.common?.handle?.variant;
      f.variant = el('select', {}, ...HANDLE_VARIANTS.map(([v, t]) => el('option', { value: v, selected: v === current }, t)));
      fields.push(el('label', {}, tx('ui.kieu-tay-nam'), f.variant));
    } else if (action === 'material') {
      const used = [...new Set([...Object.values(spec.common?.material || {}), ...spec.module.map((x) => x.material)].filter((v) => typeof v === 'string' && v))];
      const dl = el('datalist', { id: 'ctxMats' }, ...used.map((v) => el('option', { value: v })));
      catalog.list('material', lang()).then((d) => {               // the suggested materials are catalog items (workshop + user)
        for (const it of d.items) if (!used.includes(it.data.text)) dl.append(el('option', { value: it.data.text }));
      }).catch(() => { /* suggestions only */ });
      f.material = el('input', { type: 'text', value: m?.material || '', placeholder: tx('ui.vd-laminate-xanh-reu-mo'), autocomplete: 'off' }); f.material.setAttribute('list', 'ctxMats');
      fields.push(el('label', {}, tx('ui.vat-lieu-mat-truoc'), f.material, dl));
    } else if (action === 'doorStyle') {
      f.style = el('select', {}, ...DOOR_STYLES.map(([v, t]) => el('option', { value: v, selected: v === m?.doorStyle }, t)));
      fields.push(el('label', {}, tx('ui.kieu-canh'), f.style));
    } else if (action === 'remove') {
      f.closeGap = el('input', { type: 'checkbox', checked: true });
      const owned = spec.appliances.filter((a) => a.module === target.id).map((a) => a.name || a.id);
      fields.push(el('label', { class: 'inline' }, f.closeGap, tx('ui.don-cac-tu-con-lai-lap-cho')));
      if (owned.length) fields.push(el('p', { class: 'ctx-msg warn' }, tx('ui.thiet-bi-gan-theo-module-nay-cung', { 0: owned.join(', ') })));
    } else if (action === 'runMove') {
      f.along = el('input', { type: 'number', step: 50, value: 0 });
      f.out = el('input', { type: 'number', step: 50, value: 0 });
      f.turn = el('select', {}, ...RUN_TURNS.map(([v, t]) => el('option', { value: v }, t)));
      fields.push(el('label', {}, tx('ui.doc-theo-day-sang-phai-khi-nhin'), f.along), el('label', {}, tx('ui.ra-phia-truoc-canh-tu-mm-am'), f.out),
        el('label', {}, tx('ui.xoay-quanh-dau-trai-cua-day'), f.turn));
    } else if (action === 'runStretch') {
      f.end = el('select', {}, el('option', { value: 'end' }, tx('ui.dau-phai-nhin-tu-truoc')), el('option', { value: 'start' }, tx('ui.dau-trai-nhin-tu-truoc')));
      f.delta = el('input', { type: 'number', step: 50, value: 100 });
      fields.push(el('label', {}, tx('ui.keo-dau-nao'), f.end), el('label', {}, tx('ui.bao-nhieu-mm-duong-dai-ra-am'), f.delta),
        el('p', { class: 'ctx-msg' }, tx('ui.tu-dung-ngay-dau-duoc-keo-se')));
    } else if (action === 'runRemove') {
      const inRun = spec.module.filter((x) => x.run === m?.run).map((x) => x.id);
      fields.push(el('p', { class: 'ctx-msg warn' }, tx('ui.se-xoa-module-cua-day-cung-thiet', { 0: inRun.length, 1: m?.run, 2: inRun.join(', ') })));
    } else if (action === 'add') {
      f.side = m?.run ? el('select', {}, el('option', { value: 'after' }, tx('ui.ben-phai-nhin-tu-truoc')), el('option', { value: 'before' }, tx('ui.ben-trai-nhin-tu-truoc')))
        : el('select', {}, el('option', { value: 'after' }, tx('ui.phia-sau-xa-goc-hon')), el('option', { value: 'before' }, tx('ui.phia-truoc-gan-goc-hon')));
      f.width = el('input', { type: 'number', min: 200, max: 1200, step: 10, value: m?.width || 600 });
      f.closeGap = el('input', { type: 'checkbox', checked: true });
      fields.push(el('label', {}, tx('ui.vi-tri'), f.side), el('label', {}, tx('ui.chieu-rong-mm-2'), f.width), el('label', { class: 'inline' }, f.closeGap, tx('ui.day-cac-tu-phia-sau-ra')));
    }
    const out = el('div', { class: 'ctx-msg' });
    if (message) out.append(err(message));
    const read = () => Object.fromEntries(Object.entries(f).map(([k, n]) => [k, n.type === 'checkbox' ? n.checked : n.value]));
    const go = el('button', { type: 'button', class: 'primary', onclick: () => preview(action, read) }, tx('ui.xem-truoc'));
    const extra = [];
    if (action === 'material' && !target.group) {   // same material, but as a picture first: opens the image tab with the job form filled (quick mode, preview on)
      extra.push(el('button', { type: 'button', class: 'ghost', title: tx('ui.mo-tab-sua-anh-voi-vat-lieu'),
        onclick: () => { const material = read().material.trim(); if (!material) return form(action, tx('ui.nhap-ten-vat-lieu')); const id = target.id; close(); ctx.imageEdit({ layer: layerFor('material', id), module: id, material, mode: 'quick', preview: true }); } }, tx('ui.tao-anh-voi-vat-lieu-nay')));
    }
    box.replaceChildren(header(`${target.group ? groupLabel(target.group) : target.part === 'countertop' ? tx('ui.mat-ban-2') : target.id}: ${actionList(spec).find((a) => a.id === action)?.label}`), ...fields, out,
      el('div', { class: 'row' }, go, ...extra, el('button', { type: 'button', class: 'ghost', onclick: list }, tx('ui.quay-lai'))));
    (f.material || f.style || f.width || f.along || f.delta || go).focus?.();
    box.onkeydown = (e) => { if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); go.click(); } };
  }

  async function preview(action, read) {
    if (busy) return; const { id, rev, spec } = ctx.getState();
    let op;
    try { op = target.group ? buildGroupOp(action, target.group, read(), spec) : buildOp(action, target.id, read(), spec); } catch (e) { return form(action, e.message); }
    busy = true; ctx.setStatus(tx('ui.xem-truoc-thay-doi'));
    try {
      const { status, data } = await call(`/api/designs/${id}/propose`, { op, baseRev: rev, ...(target.group ? { scope: target.group.modules } : target.part === 'countertop' || RUN_ACTIONS.includes(action) ? {} : { scope: [target.id] }) });   // a run action is meant to touch the whole run
      busy = false;
      if (status === 409) return stale(action);
      if (!data || data.error) return form(action, data?.error || tx('ui.loi', { 0: status }));
      showPreview(action, data, read);
    } catch (e) { busy = false; form(action, e.message); }
  }

  // A cabinet run against the clicked edge of a floorplan object: the server picks the edge and the facing, the preview shows the result.
  async function runI(text = '', backEdge = null) {
    if (busy) return; const { id, rev } = ctx.getState();
    busy = true; ctx.setStatus(target.structureKind === 'furniture' ? tx('ui.tinh-day-tu-thay-vat-nay') : tx('ui.tinh-day-tu-doc-canh-vat-the'));
    try {
      const { status, data } = await call(`/api/designs/${id}/template`, { template: { kind: 'run-i', structureId: target.id, point: target.point, ...(text.trim() ? { prompt: text.trim() } : {}), ...(backEdge != null ? { backEdge } : {}) }, baseRev: rev });
      busy = false;
      if (status === 409) return stale('run-i');
      if (data?.status === 'choose-edge') return chooseEdge(data, text);
      if (!data || data.error || !data.proposal) {
        box.replaceChildren(header(tx('ui.day-tu', { 0: target.id.replace(/^STRUCT-/, '') })), err(data?.error || tx('ui.loi', { 0: status })),
          el('div', { class: 'row' }, el('button', { type: 'button', class: 'ghost', onclick: list }, tx('ui.quay-lai'))));
        return;
      }
      showPreview('run-i', data.proposal, null, data.summary || []);
    } catch (e) { busy = false; ctx.setStatus(e.message, 'warn'); }
  }

  // An appliance: the sentence picks the models offered ("đổi sang bếp gas"); a popup lists them, the one picked is previewed.
  async function applianceModels(text) {
    if (busy) return; const { id, rev } = ctx.getState();
    busy = true; ctx.setStatus(tx('ui.tim-mau-thiet-bi'));
    try {
      const { status, data } = await call(`/api/designs/${id}/template`, { template: { kind: 'replace-appliance', id: target.id, prompt: text }, baseRev: rev });
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error) return redraw(text, data?.error || tx('ui.loi', { 0: status }));
      ctx.setStatus(tx('ui.mau-co-the-thay', { 0: data.models?.length || 0, 1: applianceName(data.appliance?.type) }), 'ok');
      chooseModel(data, text);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  function chooseModel(data, text) {
    const now = data.appliance;
    const rows = modelChoices(data.models).map((c) => el('li', {}, el('button', { type: 'button', disabled: !c.pickable, title: c.reasons.join('\n'),
      onclick: () => (c.status === 'bad' ? fitChoice(c, text) : replaceAppliance(c.id, false, text)) }, c.label),
      ...(c.reasons.length ? [el('small', { class: 'muted' }, c.reasons[0])] : [])));
    box.replaceChildren(header(tx('ui.doi-mau-2', { 0: applianceName(now.type), 1: now.id })),
      el('p', { class: 'ctx-msg' }, tx('ui.dang-dung', { 0: now.name || now.model, 1: now.size ? ` (${now.size.w}×${now.size.d} mm)` : '' })),
      rows.length ? el('ul', { class: 'ctx-list' }, ...rows) : err(tx('ui.khong-co-mau-nao-khac-cung-loai')),
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'ghost', onclick: list }, tx('ui.quay-lai'))));
    box.querySelector('.ctx-list button:not([disabled])')?.focus();
  }

  // A model that does not fit where it is: keep the cabinet (and see the warning) or widen it.
  function fitChoice(c, text) {
    box.replaceChildren(header(c.label.split(' — ')[0]), el('p', { class: 'ctx-msg warn' }, c.reasons.join(' · ')),
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'primary', onclick: () => replaceAppliance(c.id, true, text) }, tx('ui.noi-tu-do')),
        el('button', { type: 'button', onclick: () => replaceAppliance(c.id, false, text) }, tx('ui.giu-tu')),
        el('button', { type: 'button', class: 'ghost', onclick: () => applianceModels(text) }, tx('ui.quay-lai'))));
  }

  async function replaceAppliance(model, resizeHost, text) {
    if (busy) return; const { id, rev } = ctx.getState();
    busy = true; ctx.setStatus(tx('ui.xem-truoc-mau-moi'));
    try {
      const { status, data } = await call(`/api/designs/${id}/template`, { template: { kind: 'replace-appliance', id: target.id, model, resizeHost }, baseRev: rev });
      busy = false;
      if (status === 409) return stale('cmd');
      if (!data || data.error || !data.proposal) return redraw(text, data?.error || tx('ui.loi', { 0: status }));
      lastAppliance = { id: target.id, type: data.appliance.type, model, facts: data.aiFacts };
      showPreview('appliance', data.proposal, null, data.summary || []);
    } catch (e) { busy = false; redraw(text, e.message); }
  }

  // No edge of the object lies against a wall: the user picks the edge the backs go on (hovering one draws it in the 3D view).
  function chooseEdge(data, text) {
    const choices = edgeChoices(data.edges);
    box.replaceChildren(header(tx('ui.chon-huong-day-tu', { 0: target.id.replace(/^STRUCT-/, '') })),
      el('p', { class: 'ctx-msg' }, tx('ui.vat-nay-khong-co-canh-nao-sat')),
      el('ul', { class: 'ctx-list' }, ...choices.map((c) => el('li', {}, el('button', { type: 'button',
        onmouseenter: () => ctx.guide?.(c.a, c.b), onfocus: () => ctx.guide?.(c.a, c.b), onmouseleave: () => ctx.guide?.(null),
        onclick: () => { ctx.guide?.(null); runI(text, c.index); } }, c.label)))),
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'ghost', onclick: () => { ctx.guide?.(null); list(); } }, tx('ui.quay-lai'))));
    if (!choices.length) box.append(err(tx('ui.khong-co-canh-nao-dai-tu-600')));
    box.querySelector('.ctx-list button')?.focus();
  }

  function showPreview(action, p, read, extra = []) {
    const lines = [...extra.map((x) => (typeof x === 'string' ? { kind: 'info', text: x } : x)), ...describeProposal(p)];
    const confirm = el('button', { type: 'button', class: p.validation?.introducesErrors ? 'danger' : 'primary', disabled: !p.applicable || p.unchanged,
      onclick: () => apply(action, p) }, p.validation?.introducesErrors ? tx('ui.van-ap-dung') : tx('ui.ap-dung'));
    const back = ['run-i', 'run-line', 'cmd', 'appliance'].includes(action) ? list : () => form(action);
    box.replaceChildren(header(tx('ui.xem-truoc-2', { 0: action === 'run-line' ? tx('ui.day-tu-moi') : target.group ? groupLabel(target.group) : target.id })), el('ul', { class: 'ctx-preview' }, ...lines.map((l) => el('li', { class: l.kind }, l.text))),
      el('div', { class: 'row' }, confirm, el('button', { type: 'button', class: 'ghost', onclick: back }, ['run-i', 'run-line', 'cmd', 'appliance'].includes(action) ? tx('ui.quay-lai') : tx('ui.sua-lai')), el('button', { type: 'button', class: 'ghost', onclick: close }, tx('ui.huy'))));
    confirm.focus();
  }

  async function apply(action, p) {
    if (busy) return; busy = true; ctx.setStatus(tx('ui.ap-dung-2'));
    try {
      const { status, data } = await call(`/api/designs/${p.id}/ops`, { op: p.operation, baseRev: p.baseRev, expect: p.opHash });
      busy = false;
      if (status === 409) return stale(action);
      if (!data || data.error) { ctx.setStatus(data?.error || tx('ui.loi', { 0: status }), 'warn'); return ['cmd', 'appliance'].includes(action) ? list() : form(action, data?.error || tx('ui.loi', { 0: status })); }
      if (previewOfJob && previewOfJob === pendingJob) setJob(null);
      previewOfJob = null;
      if (action === 'run-line') lineFrom = null;
      const swapped = action === 'appliance' ? lastAppliance : null;
      close(); await ctx.afterChange(data); ctx.setStatus(tx('ui.da-ap-dung-rev', { 0: data.rev }), 'ok');
      if (swapped) {        // the picture follows: the image tab opens on that appliance with the model's description filled in (nothing sent yet)
        ctx.imageEdit({ layer: applianceLayer(swapped.id, swapped.type), module: swapped.id, material: '',     // not a material: the model goes in the request
          instruction: swapped.facts?.prompt || '', mode: 'quick', preview: true });
      }
    } catch (e) { busy = false; if (['cmd', 'appliance'].includes(action)) ctx.setStatus(e.message, 'warn'); else form(action, e.message); }
  }

  function stale(action) {
    box.replaceChildren(header(tx('ui.thiet-ke-da-thay-doi')), el('p', { class: 'ctx-msg warn' }, tx('ui.co-ban-sua-moi-hon-o-tab')),
      el('div', { class: 'row' }, el('button', { type: 'button', class: 'primary', onclick: async () => { const id = target.id; await ctx.reload(); if (action === 'cmd' && target.kind === 'structure') list(); else if (ctx.getState().spec.module.some((x) => x.id === id)) (action === 'cmd' ? list() : form(action)); else close(); } }, tx('ui.tai-lai-2')),
        el('button', { type: 'button', class: 'ghost', onclick: close }, tx('ui.huy'))));
  }

  document.addEventListener('pointerdown', (e) => { if (!box.hidden && !box.contains(e.target) && !ctx.keepOpenOn?.(e.target)) close(); }, true);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !box.hidden) { e.stopPropagation(); close(); } }, true);
  window.addEventListener('design-opened', () => { lineFrom = null; ctx.guide?.(null); if (!busy) close(); });

  return {
    open(t, x, y) {
      const g = ctx.getState().multi;      // a right click on a module of the Shift-selected group: the group's menu
      const onGroup = g && t && (t.kind === 'module' || (t.kind === 'part' && t.part !== 'countertop')) && g.modules.includes(t.id);
      target = onGroup ? { kind: 'group', id: t.id, group: g } : t;
      list(); place(x, y); box.querySelector('button:not(.ctx-x)')?.focus();
    },
    /** A run handle was dragged in the 3D view: the same previewed change the menu would make, shown where the drag ended. */
    runDrag(change, at) { if (busy) return; target = { kind: 'module', id: change.module }; place(at.x, at.y); preview(change.action, () => change.form); },
    close, get isOpen() { return !box.hidden; },
  };
}
