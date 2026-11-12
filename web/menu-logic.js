import { t, tx } from './i18n.js';
// Pure logic of the module context menu (no DOM, no three.js), so it can be tested with `node --test tests/js`.
export const CLICK_MAX_MOVE = 4;     // px between press and context-menu event: more is a camera drag, not a click
export const CLICK_MAX_MS = 600;
export const DOOR_STYLES = [['flat', tx('ui.canh-phang')], ['frame', tx('ui.canh-khung-shaker')], ['glass', tx('ui.canh-kinh')]];
// Input limits (mm) of the menu: the workshop's catalog "defaults" (menu section), set by boot.js; these are the builtin values.
export const LIMITS = { addWidthMin: 200, addWidthMax: 1200, overhangMax: 100, runShiftMax: 10000, stretchMax: 1500 };
export function setLimits(menu) { for (const k of Object.keys(LIMITS)) if (Number.isFinite(menu?.[k])) LIMITS[k] = menu[k]; }
export const HANDLE_VARIANTS = [['bar', 'Tay thanh'], ['knob', tx('ui.num')], ['concealed', tx('ui.tay-am')], ['none', tx('ui.khong-tay-nhan-mo')]];
export const RUN_ACTIONS = ['runMove', 'runStretch', 'runRemove'];
export const RUN_TURNS = [[0, tx('ui.khong-xoay')], [90, tx('ui.xoay-90-nguoc-chieu-kim-dong-ho')], [-90, tx('ui.xoay-90-theo-chieu-kim-dong-ho')], [180, tx('ui.quay-nguoc-lai-180')], [45, tx('ui.xoay-45-nguoc-chieu')], [-45, tx('ui.xoay-45-theo-chieu')]];

/** Was the press-and-release a click (pointer barely moved, short)? down/up: {x, y, t}. */
export function isClick(down, up) {
  if (!down || !up) return false;
  return Math.hypot(up.x - down.x, up.y - down.y) <= CLICK_MAX_MOVE && up.t - down.t <= CLICK_MAX_MS;
}

/** First hit that is a cabinet module of the design or a visible floorplan element. hits: raycaster results, nearest first. */
export function pickTarget(hits, moduleIds) {
  for (const h of hits) {
    const u = h.object?.userData || {};
    if (u.structureId && h.object.visible !== false) return { kind: 'structure', id: u.structureId, ...(u.kind ? { structureKind: u.kind } : {}), ...(h.point ? { point: { x: h.point.x, z: h.point.z } } : {}) };   // point: where the ray hit, scene units
    if (u.appliance) return { kind: 'appliance', id: u.appliance, applianceType: u.role };     // a hob, sink, tap, hood, fridge or oven
    const part = u.part;   // schema 1.4 partRef: a door, drawer front, handle or countertop run
    if (part?.kind === 'countertop') return { kind: 'part', part: 'countertop', id: part.wall || 'back' };
    if (part && ['door', 'drawer', 'handle'].includes(part.kind) && moduleIds.includes(part.module)) return { kind: 'part', part: part.kind, id: part.module };
    if (u.module && moduleIds.includes(u.module)) return { kind: 'module', id: u.module };
  }
  return null;
}

/** What can be done to the whole run a cabinet stands in (a click on a cabinet usually lands on its door, so doors offer these too). */
function runActions(m) {
  return m?.run ? [{ id: 'runMove', label: tx('ui.doi-xoay-day', { 0: m.run }) }, { id: 'runStretch', label: tx('ui.keo-dai-thu-ngan-day', { 0: m.run }) }, { id: 'runRemove', label: tx('ui.xoa-ca-day', { 0: m.run }) }] : [];
}

/** Actions the menu offers for a target. */
export function actionsFor(target, spec, drawing = null) {
  if (!target) return [];
  if (target.kind === 'floor') {     // drawing a run: first point, then the second; `drawing` is the first point while one is pending
    return drawing ? [{ id: 'line-end', label: tx('ui.ve-day-tu-ket-thuc-o-diem') }, { id: 'line-start', label: tx('ui.bat-dau-lai-tu-diem-nay') }, { id: 'line-cancel', label: tx('ui.bo-day-dang-ve') }]
      : [{ id: 'line-start', label: tx('ui.ve-day-tu-bat-dau-tu-diem') }];
  }
  if (target.kind === 'part') {
    if (target.part === 'countertop') return [{ id: 'countertopMaterial', label: tx('ui.doi-vat-lieu-mat-ban') }, { id: 'countertopOverhang', label: tx('ui.doi-do-nho-mat-ban') }];
    if (target.part === 'handle') return [{ id: 'handleVariant', label: tx('ui.doi-kieu-tay-nam') }, { id: 'handleMaterial', label: tx('ui.doi-vat-lieu-tay-nam') }];
    return [...(target.part === 'door' ? [{ id: 'doorStyle', label: tx('ui.doi-kieu-canh') }] : []), { id: 'material', label: tx('ui.doi-vat-lieu-mat-truoc') },
      { id: 'handleVariant', label: tx('ui.doi-kieu-tay-nam') }, { id: 'image', label: tx('ui.sua-anh-cua-module-nay') }, ...runActions(spec?.module?.find((x) => x.id === target.id))];
  }
  if (target.kind === 'appliance') return [];       // an appliance: its title and the command box only ("đổi sang bếp gas", "thay chậu đôi")
  if (target.kind === 'structure') return [...(target.point ? [{ id: 'run-i', label: target.structureKind === 'furniture' ? tx('ui.thay-vat-nay-bang-day-tu') : tx('ui.tao-day-tu-chu-i-doc-canh') }] : []), { id: 'struct-hide', label: tx('ui.an-thanh-phan-nay') }, { id: 'struct-isolate', label: tx('ui.chi-giu-thanh-phan-nay') }, { id: 'struct-all', label: tx('ui.hien-tat-ca') }];
  const m = spec?.module?.find((x) => x.id === target.id);
  const out = [{ id: 'material', label: tx('ui.doi-vat-lieu-mat-truoc') }, { id: 'doorStyle', label: tx('ui.doi-kieu-canh') }];
  if (m && m.wall !== 'corner' && m.type !== 'corner-shelf') out.push({ id: 'add', label: tx('ui.them-tu-ben-canh') });
  out.push({ id: 'remove', label: tx('ui.xoa-module') }, { id: 'image', label: tx('ui.sua-anh-cua-module-nay') });
  return [...out, ...runActions(m)];
}

/** Operation for a form. Throws Error with a message the user can read. */
export function buildOp(action, id, form, spec) {
  if (action === 'countertopMaterial') {
    const material = String(form.material || '').trim();
    if (!material) throw new Error(tx('ui.nhap-ten-vat-lieu-mat-ban'));
    if (material === spec?.common?.material?.countertop) throw new Error(tx('ui.mat-ban-da-dung-vat-lieu-nay'));
    return { op: 'common', changes: { material: { ...(spec?.common?.material || {}), countertop: material } } };
  }
  if (action === 'countertopOverhang') {
    const mm = Number(form.overhang);
    if (!Number.isFinite(mm) || mm < 0 || mm > LIMITS.overhangMax) throw new Error(tx('ui.do-nho-0-mm', { 0: LIMITS.overhangMax }));
    if (mm === spec?.common?.countertopOverhang) throw new Error(tx('ui.mat-ban-da-nho-dung-muc-nay'));
    return { op: 'common', changes: { countertopOverhang: mm } };
  }
  if (!['material', 'doorStyle', 'remove', 'add', 'handleVariant', 'handleMaterial', ...RUN_ACTIONS].includes(action)) throw new Error(tx('ui.hanh-dong-khong-ho-tro', { 0: action }));   // checked first: a wrong action must not look like a missing module
  const m = spec?.module?.find((x) => x.id === id);
  if (!m) throw new Error(tx('ui.khong-con-module-trong-thiet-ke', { 0: id }));
  if (action === 'material') {
    const material = String(form.material || '').trim();
    if (!material) throw new Error(tx('ui.nhap-ten-vat-lieu'));
    if (material === m.material) throw new Error(tx('ui.module-da-dung-vat-lieu-nay'));
    return { op: 'update', id, changes: { material }, closeGap: false };
  }
  if (action === 'doorStyle') {
    if (!DOOR_STYLES.some(([v]) => v === form.style)) throw new Error(tx('ui.chon-kieu-canh'));
    return { op: 'update', id, changes: { doorStyle: form.style }, closeGap: false };
  }
  if (action === 'handleVariant') {
    if (!HANDLE_VARIANTS.some(([v]) => v === form.variant)) throw new Error(tx('ui.chon-kieu-tay-nam'));
    return { op: 'update', id, changes: { handle: { ...(m.handle || {}), variant: form.variant } }, closeGap: false };   // keep the module's other handle overrides
  }
  if (action === 'handleMaterial') {
    const material = String(form.material || '').trim();
    if (!material) throw new Error(tx('ui.nhap-vat-lieu-tay-nam'));
    return { op: 'update', id, changes: { handle: { ...(m.handle || {}), material } }, closeGap: false };
  }
  if (RUN_ACTIONS.includes(action)) {
    const run = spec?.runs?.find((r) => r.id === m.run);
    if (!run) throw new Error(tx('ui.module-khong-dung-trong-mot-day', { 0: id }));
    if (action === 'runRemove') return { op: 'remove-run', id: run.id };
    if (action === 'runStretch') {
      const delta = Number(form.delta);
      if (!['start', 'end'].includes(form.end)) throw new Error(tx('ui.chon-dau-day-can-keo'));
      if (!Number.isFinite(delta) || delta === 0 || Math.abs(delta) > LIMITS.stretchMax) throw new Error(tx('ui.nhap-so-mm-khac-0-toi-da', { 0: LIMITS.stretchMax }));
      return { op: 'stretch-run', id: run.id, end: form.end, delta };
    }
    const along = Number(form.along || 0), out = Number(form.out || 0), turn = Number(form.turn || 0);   // along the run (to the right, seen from the front) / towards the room
    if (![along, out, turn].every(Number.isFinite) || Math.abs(along) > LIMITS.runShiftMax || Math.abs(out) > LIMITS.runShiftMax) throw new Error(tx('ui.khoang-doi-toi-da-mm', { 0: LIMITS.runShiftMax }));
    if (!RUN_TURNS.some(([v]) => v === turn)) throw new Error(tx('ui.chon-goc-xoay'));
    if (!along && !out && !turn) throw new Error(tx('ui.nhap-khoang-doi-hoac-chon-goc-xoay'));
    const t = (run.yaw * Math.PI) / 180; const cos = Math.cos(t), sin = Math.sin(t);
    const round = (v) => Math.round(v * 10) / 10;
    const changes = {};
    if (along || out) { changes.x = round(run.x + along * cos + out * sin); changes.z = round(run.z - along * sin + out * cos); }
    if (turn) changes.yaw = ((run.yaw + turn + 180) % 360 + 360) % 360 - 180;
    return { op: 'move-run', id: run.id, changes };
  }
  if (action === 'remove') return { op: 'remove', id, closeGap: !!form.closeGap };
  if (action === 'add') {
    const width = Number(form.width);
    if (!Number.isFinite(width) || width < LIMITS.addWidthMin || width > LIMITS.addWidthMax) throw new Error(tx('ui.chieu-rong-mm', { 0: LIMITS.addWidthMin, 1: LIMITS.addWidthMax }));
    if (m.wall === 'corner') throw new Error(tx('ui.khong-them-canh-module-goc-o-day'));
    if (form.side === 'after') return { op: 'add', module: { width }, afterModule: id, closeGap: !!form.closeGap };
    const where = m.run ? { run: m.run } : m.wall === 'island' ? { offset: m.offset, facing: m.facing } : {};      // the same run / free row as the cabinet it stands beside
    return { op: 'add', module: { width, type: m.type, wall: m.wall, ...where, y: m.y, height: m.height, depth: m.depth, fromCorner: m.fromCorner }, closeGap: !!form.closeGap };
  }
  throw new Error(tx('ui.hanh-dong-khong-ho-tro', { 0: action }));
}

/** Layer an action targets in the image editor: whole fronts for a material/style change, the whole module otherwise. */
export function layerFor(action, id) {
  return action === 'material' || action === 'doorStyle' ? `frontSections:${id}` : `module:${id}`;
}

const show = (v) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));

/** Preview lines for the UI: [{kind: 'ok'|'info'|'warn'|'bad', text}]. */
export function describeProposal(p) {
  if (!p.applicable) return [{ kind: 'bad', text: tx('ui.khong-ap-dung-duoc', { 0: p.error?.message || tx('ui.loi-khong-ro') }) }];
  const out = [];
  if (p.unchanged) return [{ kind: 'warn', text: tx('ui.thao-tac-nay-khong-thay-doi-gi') }];
  const mod = p.diff.modules;
  for (const id of mod.added) out.push({ kind: 'info', text: tx('ui.them', { 0: id }) });
  for (const id of mod.removed) out.push({ kind: 'info', text: tx('ui.xoa-4', { 0: id }) });
  for (const [id, ch] of Object.entries(mod.changed)) out.push({ kind: 'info', text: `${id}: ` + ch.map((c) => `${c.field} ${show(c.old)} → ${show(c.new)}`).join('; ') });
  for (const e of p.diff.other) out.push({ kind: 'info', text: `${e.path}: ${show(e.old)} → ${show(e.new)}` });
  if (p.diff.truncated) out.push({ kind: 'warn', text: tx('ui.danh-sach-thay-doi-bi-cat-bot') });
  if (p.outsideScope?.length) out.push({ kind: 'warn', text: tx('ui.cung-lam-doi-module-khac', { 0: p.outsideScope.join(', ') }) });
  for (const i of p.validation.introduced) out.push({ kind: i.severity === 'error' ? 'bad' : 'warn', text: tx('ui.moi', { 0: i.content }) });
  for (const i of p.validation.resolved) out.push({ kind: 'ok', text: tx('ui.het', { 0: i.content }) });
  return out;
}

/** Place a w x h popup at (x, y) inside a vw x vh viewport with a margin. */
export function menuPosition(x, y, w, h, vw, vh, margin = 8) {
  return { left: Math.max(margin, Math.min(x, vw - w - margin)), top: Math.max(margin, Math.min(y, vh - h - margin)) };
}

/**
 * What picking `target` (a click or a right click) does to the selection. null = empty space.
 * -> {clearStructure?: true, selectStructure?: id, selectModule?: id}. A countertop is not a module: it only clears the structure selection.
 */
/** The run-line template for a drawn run: from `a` to `b` (mm), doors looking to the LEFT or RIGHT of the drawing direction, seen from above. */
export function lineTemplate(a, b, side, prompt = '') {
  const ex = b.x - a.x, ez = b.z - a.z; const len = Math.hypot(ex, ez);
  if (!(len >= 300)) throw new Error(tx('ui.hai-diem-phai-cach-nhau-it-nhat'));
  if (!['left', 'right'].includes(side)) throw new Error(tx('ui.chon-phia-canh-tu-quay-ra'));
  const k = side === 'left' ? 1 : -1;        // left of a -> b seen from above (x to the right, z towards the viewer) is (ez, -ex)
  const front = { x: (a.x + b.x) / 2 + (k * ez / len) * 500, z: (a.z + b.z) / 2 - (k * ex / len) * 500 };
  return { kind: 'run-line', a: { x: a.x, z: a.z }, b: { x: b.x, z: b.z }, front, ...(prompt.trim() ? { prompt: prompt.trim() } : {}) };
}

/** Ids of the cabinets standing in the same explicit run as cabinet `id`; null when it is in none. */
export function runModulesOf(spec, id) {
  const m = spec?.module?.find((x) => x.id === id);
  return m?.run ? spec.module.filter((x) => x.run === m.run).map((x) => x.id) : null;
}

export const guideText = (mm) => tx('ui.day-tu-dang-ve-mm-chuot-phai', { 0: Math.round(mm) });

export const DRAG_STEP = 10, DRAG_MIN = 10;      // mm: a drag is rounded to this step; a shorter one is a click, not a drag

/** What a drag of a run handle asks for, from the movement of the pointer on the floor (mm along the run and towards the room):
 *  the form `buildOp` takes, or null when the pointer hardly moved. `handle`: 'start' | 'end' (drag an end) or 'move' (the whole run). */
export function dragChange(handle, along, out) {
  const snap = (v) => Math.round(v / DRAG_STEP) * DRAG_STEP;
  if (handle === 'move') {
    const a = snap(along), o = snap(out);
    return Math.abs(a) < DRAG_MIN && Math.abs(o) < DRAG_MIN ? null : { action: 'runMove', form: { along: a, out: o, turn: 0 } };
  }
  const delta = snap(handle === 'end' ? along : -along);      // pulling the start to the left makes the run longer
  return Math.abs(delta) < DRAG_MIN ? null : { action: 'runStretch', form: { end: handle, delta } };
}

/** Where a ray meets the floor (y = 0), or null when it points away from it. Scene units in, scene units out. */
export function floorPoint(origin, direction) {
  if (!(direction.y < -1e-9) || !(origin.y > 0)) return null;
  const t = -origin.y / direction.y;
  return { x: origin.x + t * direction.x, z: origin.z + t * direction.z };
}

export function selectionEffect(target) {
  if (!target) return { clearStructure: true };
  if (target.kind === 'structure') return { selectStructure: target.id };
  if (target.kind === 'module' || (target.kind === 'part' && target.part !== 'countertop')) return { clearStructure: true, selectModule: target.id };
  return { clearStructure: true };
}

/** Scene units -> millimetres for a picked point; `units` is the unit name of the scene file (mm, cm or m). */
export function sceneToMm(point, units) {
  const k = { mm: 0.001, cm: 0.01, m: 1 }[units || 'mm'];
  return { x: point.x / k, z: point.z / k };
}

/** What the menu offers on a Shift-selected group (shiftGroup in design-logic.js): the changes that make sense for every module of it. */
export function groupActions(g) {
  if (!g) return [];
  const out = [];
  if (g.role !== 'handle') out.push({ id: 'material', label: tx('ui.doi-vat-lieu-mat-truoc-ca-nhom') });
  if (['front', 'door', 'all'].includes(g.role)) out.push({ id: 'doorStyle', label: tx('ui.doi-kieu-canh-ca-nhom') });
  out.push({ id: 'handleVariant', label: tx('ui.doi-kieu-tay-nam-ca-nhom') }, { id: 'handleMaterial', label: tx('ui.doi-vat-lieu-tay-nam-ca-nhom') },
    { id: 'image', label: tx('ui.sua-anh-cua-vung-chon-nay') });
  return out;
}

/** One operation for a group: the menu's own operation for each module (buildOp), together. A module the change does nothing to (it
 *  already has that material) is left out; when it does nothing to any, the first reason is the error. */
export function buildGroupOp(action, g, form, spec) {
  if (!groupActions(g).some((a) => a.id === action) || action === 'image') throw new Error(tx('ui.hanh-dong-khong-ho-tro-cho-nhom', { 0: action }));
  const ops = []; const reasons = [];
  for (const id of g.modules) {
    try { ops.push(buildOp(action, id, form, spec)); } catch (e) { reasons.push(e.message); }
  }
  if (!ops.length) throw new Error(reasons[0] || tx('ui.khong-co-thay-doi'));
  return ops.length === 1 ? ops[0] : { op: 'multi', ops };
}

/** The server template that replaces a whole cabinet system: laid out again from `prompt` when there is one, else restyled with `style`.
 * `styles`: the catalog's style presets ([{ id }]) when loaded, to refuse an unknown one here (the server checks it anyway). */
export function systemTemplate(system, prompt, style = 'auto', styles = null) {
  if (!system) throw new Error(tx('ui.khong-biet-tu-nay-thuoc-he-tu'));
  const text = String(prompt || '').trim();
  if (text) return { kind: 'replace-system', system, prompt: text };
  if (style !== 'auto' && styles && !styles.some((x) => x.id === style)) throw new Error(tx('ui.phong-cach-khong-co', { 0: style }));
  return { kind: 'replace-system', system, style };
}

/** The choices of the "which edge is the back" popup (an object with no edge against a wall): label and the line to show, room frame mm. */
export function edgeChoices(edges) {
  return (edges || []).map((e) => ({ index: e.index, a: e.a, b: e.b,
    label: tx('ui.lung-tu-tren-canh-dai-mm', { 0: Math.round(e.length), 1: e.gapToWall == null ? '' : tx('ui.cach-tuong-mm', { 0: Math.round(e.gapToWall) }) }) }));
}

const FIT_VI = { ok: tx('ui.vua'), check: tx('ui.can-kiem-tra'), bad: tx('ui.khong-vua'), later: tx('ui.chua-ho-tro-doi-loai'), blocked: tx('ui.khong-dat-duoc-o-day') };

/** Lines of the model popup: label, the fit and why; `later` and `blocked` (another kind that cannot go there) cannot be picked. Sizes in mm. */
export function modelChoices(models) {
  return (models || []).map((m) => ({ id: m.id, status: m.status, pickable: !['later', 'blocked'].includes(m.status), reasons: m.reasons || [],
    label: `${m.name} · ${m.size.w}×${m.size.d}${m.size.h ? `×${m.size.h}` : ''}${m.cutout ? ` · khoét ${m.cutout.w}×${m.cutout.d}` : ''} — ${FIT_VI[m.status] || m.status}` }));
}

/** The image-tab layer of an appliance (the server names it <id>-<type>-1), for "Sửa ảnh". */
export const applianceLayer = (id, type) => `${id}-${type}-1`;

/** Wall faces of a three.js scene file as segments [{a, b}] (mm, the frame picked points are in): the floorplan's wall outlines
 *  (every edge) and the drawn room's walls. */
export function wallSegments(doc) {
  const out = [];
  for (const st of doc?.room?.structures || []) {
    if (st.kind !== 'wall' || !Array.isArray(st.outline)) continue;
    st.outline.forEach((p, i) => out.push({ a: p, b: st.outline[(i + 1) % st.outline.length] }));
  }
  for (const w of doc?.room?.walls || []) if (w.start && w.end) out.push({ a: w.start, b: w.end });
  return out;
}

/** Does the drawn line from -> to (mm) run along a wall: parallel within 2° and both ends within 150 mm of the same wall face, overlapping
 *  it by half the line at least? Then the server turns the backs to the wall, so the "which side" question is left out (kitchen/wall_line.py). */
export function lineAlongWall(from, to, walls, near = 150, degrees = 2) {
  const len = Math.hypot(to.x - from.x, to.z - from.z);
  if (len < 1) return false;
  const ux = (to.x - from.x) / len, uz = (to.z - from.z) / len;
  for (const { a, b } of walls) {
    const wl = Math.hypot(b.x - a.x, b.z - a.z);
    if (wl < 1) continue;
    const wx = (b.x - a.x) / wl, wz = (b.z - a.z) / wl;
    if (Math.abs(ux * wz - uz * wx) > Math.sin((degrees * Math.PI) / 180)) continue;           // not parallel
    const off = (p) => Math.abs((p.x - a.x) * wz - (p.z - a.z) * wx);
    if (off(from) > near || off(to) > near) continue;
    const t = (p) => (p.x - a.x) * wx + (p.z - a.z) * wz;
    const lo = Math.max(Math.min(t(from), t(to)), 0), hi = Math.min(Math.max(t(from), t(to)), wl);
    if (hi - lo >= len * 0.5) return true;
  }
  return false;
}
