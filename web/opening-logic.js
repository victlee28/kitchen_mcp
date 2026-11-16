// Pure logic of the "Doors & windows" panel (no DOM, no network): rows of the list, the form's values, the operation a form makes.
// Openings follow the server's contract kitchen-opening/1 (docs/adr/0005-opening-contract.md): a wall axis, the centre on it, the
// hole's width and height, middle axes, leaves with a hinge axis and a side; in / out comes from the server (list_openings.opens).

export const FORM_FIELDS = ['openingType', 'wallAxis', 'center', 'fromEdge', 'fromEdgeAt', 'width', 'height', 'sill', 'axes', 'hAxes', 'hinge', 'opens', 'clearWidth'];

const num = (v) => (v === '' || v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v));
const list = (text) => String(text ?? '').split(/[,;\s]+/).filter(Boolean).map(Number);

/** The list rows: one per opening, the floorplan's first, as the server orders them. */
export function openingRows(listed) {
  return (listed?.openings || []).map((o) => ({
    id: o.id, kind: o.kind, type: o.openingType, wallAxis: o.wallAxis?.id || '', center: o.center, width: o.width, height: o.height,
    sill: o.sill, asDrawn: !!o.asDrawn, floorplan: o.sourceElement || null, unsure: o.unsure || [], opens: o.opens || [],
  }));
}

/** Which form fields the server is unsure of (recognition, a drawing without an arc...): the panel paints them yellow. */
export function unsureFields(unsure) {
  const out = new Set();
  for (const u of unsure || []) {
    if (u === 'width' || u === 'height' || u === 'sill' || u === 'center') out.add(u);
    else if (u === 'wallAxis') { out.add('wallAxis'); out.add('center'); }
    else if (u === 'axes' || u === 'hAxes' || u === 'openingType') out.add(u);
    else if (/^leaves\.\d+\.hinge$/.test(u)) out.add('hinge');
    else if (/^leaves\.\d+\.(side|operation)$/.test(u)) out.add('opens');
  }
  return out;
}

/** Hinge seen from the kitchen of the main (active) leaf: the server gives the hinge axis; left / right needs the axis direction
 *  and the kitchen side, so the panel shows the axis index and lets the user pick left / right for a change. */
export function formFromOpening(o, opens) {
  const main = (o.leaves || []).find((l) => l.active) || (o.leaves || [])[0];
  return {
    openingType: o.openingType || '', wallAxis: o.wallAxis?.id || '', center: o.center ?? '', fromEdge: '', fromEdgeAt: 'start',
    width: o.width ?? '', height: o.height ?? '', sill: o.sill ?? 0, axes: (o.axes || []).join(', '), hAxes: (o.hAxes || []).join(', '),
    hinge: '', opens: (opens || [])[Math.max(0, (o.leaves || []).indexOf(main))] || '', clearWidth: o.clearWidth ?? '',
  };
}

/** The empty form of a new opening of ``kind`` on an axis (centre in the middle of the room's stretch of it, else of the whole axis). */
export function newForm(kind, types, axis) {
  const type = (types || []).find((t) => t.kind === kind);
  const door = kind === 'door';
  const [s0, s1] = Array.isArray(axis?.room) ? axis.room : [0, axis?.length ?? 0];
  return { openingType: type?.id || '', wallAxis: axis?.id || '', center: axis ? Math.round((s0 + s1) / 2) : '', fromEdge: '', fromEdgeAt: 'start',
    width: door ? 900 : 1200, height: type?.defaultHeight ?? (door ? 2200 : 1200), sill: type?.defaultSill ?? 0,
    axes: '', hAxes: '', hinge: '', opens: door ? 'in' : 'out', clearWidth: '' };
}

/** Standard hole widths of a type for a country (data: opening-type.sizes), for the width's suggestions. */
export function standardWidths(types, typeId, country) {
  const t = (types || []).find((x) => x.id === typeId);
  const sizes = t?.sizes?.[String(country || '').toUpperCase()] || t?.sizes?.VN;
  return sizes?.widths || [];
}

/** The fields of a form as the server's opening fields (only those given; the server normalizes the rest). */
export function fieldsOf(form, kind) {
  const out = {};
  if (kind) out.kind = kind;
  if (form.openingType) out.openingType = form.openingType;
  if (form.wallAxis) out.wallAxis = form.wallAxis;
  if (num(form.fromEdge) !== null) out.fromEdge = { at: form.fromEdgeAt === 'end' ? 'end' : 'start', distance: num(form.fromEdge) };
  else if (num(form.center) !== null) out.center = num(form.center);
  for (const k of ['width', 'height', 'sill', 'clearWidth']) if (num(form[k]) !== null) out[k] = num(form[k]);
  if (String(form.axes ?? '').trim()) out.axes = list(form.axes); else out.axes = null;
  if (String(form.hAxes ?? '').trim()) out.hAxes = list(form.hAxes); else out.hAxes = null;
  if (form.hinge === 'left' || form.hinge === 'right') out.hinge = form.hinge;
  if (form.opens === 'in' || form.opens === 'out') out.opens = form.opens;
  return out;
}

/** The operation a form makes: a new opening, or the fields that changed on an existing one (floorplan openings included: the
 *  server then writes a record that overrides it). */
export function opFromForm(form, { id = null, kind = 'door', before = null } = {}) {
  const fields = fieldsOf(form, id ? null : kind);
  if (!id) return { op: 'add-opening', opening: { ...fields, source: 'human' } };
  const changes = {};
  const was = before ? fieldsOf(before) : {};
  for (const [k, v] of Object.entries(fields)) if (JSON.stringify(v) !== JSON.stringify(was[k])) changes[k] = v;
  if (changes.fromEdge) delete changes.center;
  if (form.openingType !== before?.openingType && 'axes' in changes && changes.axes === null) delete changes.axes;
  return { op: 'update-opening', id, changes };
}

export const removeOp = (id) => ({ op: 'remove-opening', id });
export const resetOp = (id) => ({ op: 'reset-opening', id });
export const adoptOp = () => ({ op: 'adopt-openings' });

/** Preview lines (menu-logic describeProposal) worded for openings: an added / changed / removed record instead of its JSON, the id
 *  counter left out. ``words(key, params)`` gives the wording. */
export function previewLines(lines, words) {
  const out = [];
  for (const l of lines) {
    if (/^idCounters\./.test(l.text)) continue;
    const m = /^openings\[([^\]]+)\]: (.*) → (.*)$/s.exec(l.text);
    if (!m) { out.push(l); continue; }
    const key = m[2] === '—' ? 'ui.opening.preview-added' : m[3] === '—' ? 'ui.opening.preview-removed' : 'ui.opening.preview-changed';
    out.push({ kind: l.kind, text: words(key, { 0: m[1] }) });
  }
  return out;
}

/** The axes of an opening as lines (mm, the frame of its wall axis, the same as the exported scene): vertical axes from the sill to
 *  the head, horizontal ones across the hole, and its centre axis (``main``) a little longer. ``type``: its opening type (template
 *  axes when the opening keeps the type's). */
export function axisLines(o, wallAxis, type) {
  if (!o || !wallAxis || !(o.width > 0)) return [];
  const w = o.width, h = o.height, sill = o.sill || 0;
  const at = (s, y) => ({ x: wallAxis.start[0] + wallAxis.dir[0] * s, y, z: wallAxis.start[1] + wallAxis.dir[1] * s });
  const mids = o.axes ?? (type?.axesRatio || []).map((r) => -w / 2 + r * w);
  const fixed = (type?.hAxesFromSill || []).filter((v) => v >= 100 && v <= h - 100);
  const hmids = o.hAxes ?? (fixed.length ? fixed : (type?.hAxesRatio || []).map((r) => r * h).filter((v) => v >= 100 && v <= h - 100));
  const out = [-w / 2, ...mids, w / 2].map((v) => ({ a: at(o.center + v, sill), b: at(o.center + v, sill + h), main: false }));
  for (const y of [0, ...hmids, h]) out.push({ a: at(o.center - w / 2, sill + y), b: at(o.center + w / 2, sill + y), main: false });
  out.push({ a: at(o.center, Math.max(0, sill - 200)), b: at(o.center, sill + h + 200), main: true });
  return out;
}

/** A sample of the opening-type preview (front view boxes, mm) as SVG rectangles in a ``w`` x ``h`` picture: {x, y, width, height, kind}
 *  with y downwards, the floor at the bottom; ``kind`` frame | leaf | glass | active. */
export function frontRects(sample, w = 220, h = 180, pad = 8) {
  const boxes = [...(sample.frame || []).map((b) => ({ ...b, kind: 'frame' })),
    ...(sample.leaves || []).map((b) => ({ ...b, kind: b.operation === 'fixed' ? 'glass' : b.active ? 'active' : 'leaf' }))];
  if (!boxes.length) return [];
  const x0 = Math.min(...boxes.map((b) => b.x0)), x1 = Math.max(...boxes.map((b) => b.x1));
  const top = Math.max(...boxes.map((b) => b.y1));
  const k = Math.min((w - 2 * pad) / (x1 - x0 || 1), (h - 2 * pad) / (top || 1));
  return boxes.map((b) => ({ x: pad + (b.x0 - x0) * k, y: h - pad - b.y1 * k, width: (b.x1 - b.x0) * k, height: (b.y1 - b.y0) * k, kind: b.kind }));
}
