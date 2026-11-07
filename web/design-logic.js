// Pure logic of the design panels (no DOM, no fetch): list order, form diff, molding payload, AI export URLs.
export const FIELDS = [['type', 'text'], ['wall', 'text'], ['fromCorner', 'number'], ['width', 'number'], ['y', 'number'], ['tall', 'number'], ['back', 'number'], ['blindCorner', 'number'], ['endPanel', 'number']];
const WALL_ORDER = { back: 0, corner: 1, right: 2, left: 3, island: 4 };

/** Modules in list order: by wall, then storey height, then distance from the corner. Unknown walls sort last-ish (NaN compares as equal). */
export function moduleOrder(modules) {
  return [...modules].sort((a, b) => (WALL_ORDER[a.wall] - WALL_ORDER[b.wall]) || (a.y - b.y) || ((a.fromCorner || 0) - (b.fromCorner || 0)));
}

export const moduleLabel = (m) => `${m.type} · ${m.wall} · ${m.fromCorner ?? 0}+${m.width ?? m.backLength}`;

/** What the edit form changed. `values` maps field name -> raw string; `doorsText` is the comma separated doors. */
export function formChanges(m, values, doorsText) {
  const changes = {};
  for (const [k, type] of FIELDS) {
    const raw = values[k];
    const val = type === 'number' ? (raw === '' ? undefined : Number(raw)) : raw;
    if (val !== undefined && val !== (m[k] ?? (type === 'number' ? 0 : ''))) changes[k] = val;
  }
  const doors = String(doorsText).split(',').map((s) => s.trim()).filter(Boolean).map(Number);
  if (doors.join() !== (m.doors || []).join()) changes.doors = doors;
  return changes;
}

/** The set-moldings operation from the molding panel; existing molding records keep their other fields. */
export function moldingsOp(spec, ui) {
  const old = Object.fromEntries((spec.moldings || []).map((m) => [m.id, m]));
  const moldings = [];
  if (ui.crown) moldings.push({ ...(old['crown-molding'] || {}), id: 'crown-molding', variant: 'crown', profile: ui.crownProfile, openEnd: ui.openEnd, enabled: true });
  if (ui.base) moldings.push({ ...(old['base-molding'] || {}), id: 'base-molding', variant: 'base', profile: ui.baseProfile, openEnd: ui.openEnd, enabled: true });
  return { op: 'set-moldings', moldings, style: ui.style };
}

export const CLASSIC_STYLES = ['Classic', 'Neoclassical', 'Transitional'];
export const styleHasMoldings = (style) => CLASSIC_STYLES.includes(style);

/** URLs and file names of the AI export of one design revision. */
export function aiExportUrls(id, rev, light) {
  const base = `/api/designs/${id}/ai-export`;
  const tag = `${id} · rev ${rev}`;
  return {
    base,
    shortUrl: `${base}?embedImages=1&lighting=${light}`,
    shortName: `${id}-rev${rev}-ai-request-short.json`,
    fullUrl: `${base}?format=day-du&lighting=${light}`,
    fullName: `${id}-rev${rev}-ai-request.json`,
    zipName: (r) => `${id}-rev${r}-ai-package.zip`,
    shortTitle: `JSON gửi AI (rút gọn, kèm ảnh) · ${tag}`,
    fullTitle: `JSON đầy đủ (cảnh three.js, vật liệu, camera) · ${tag}`,
  };
}
