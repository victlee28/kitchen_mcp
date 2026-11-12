// The layout template editor's data, without the DOM: a step's fields by kind (text, JSON or a comma list), and the top view of a sample.

export const STEP_DOS = ['base-run', 'cabinets', 'corner-base', 'corner-shelf', 'upper-run'];
export const WALLS = ['back', 'right', 'left'];

/** The fields a step of each kind shows: [key, how] — how = 'text' | 'json' | 'list' (comma separated formulas) | 'bool-text'. */
export const FIELDS = {
  'base-run': [['start', 'text'], ['length', 'text'], ['front', 'text'], ['fridgeAtEnd', 'text'], ['appliances', 'json'], ['extras', 'json']],
  'cabinets': [['start', 'text'], ['length', 'text'], ['items', 'json']],
  'corner-base': [['type', 'text'], ['width', 'text'], ['blind', 'text'], ['doors', 'list']],
  'corner-shelf': [],
  'upper-run': [['start', 'text'], ['end', 'text']],
};

/** A step as the strings its inputs show. */
export function rowOf(step) {
  const row = { do: step.do, wall: step.wall || 'back' };
  for (const [key, how] of FIELDS[step.do] || []) {
    const v = step[key];
    row[key] = v === undefined ? '' : how === 'json' ? JSON.stringify(v) : how === 'list' ? v.join(', ') : String(v);
  }
  return row;
}

/** The inputs of a row as a step (an empty field is left out; throws on JSON that does not parse). */
export function stepOf(row) {
  const out = { do: row.do };
  if (row.do !== 'corner-shelf') out.wall = row.wall || 'back';
  for (const [key, how] of FIELDS[row.do] || []) {
    const v = String(row[key] ?? '').trim();
    if (!v) continue;
    out[key] = how === 'json' ? JSON.parse(v) : how === 'list' ? v.split(',').map((x) => x.trim()).filter(Boolean) : v;
  }
  return out;
}

export const rowsOf = (steps) => (steps || []).map(rowOf);
export const stepsOf = (rows) => rows.map(stepOf);

/** The top view of a sample: its panels' footprints as rectangles in a box `size` wide, y down (the back wall at the top), with the
 * scale. parts: [{storey, x: [x0, x1], z: [z0, z1]}] in mm. */
export function topView(parts, size = 260, margin = 8) {
  if (!parts.length) return { rects: [], scale: 1, width: size, height: size };
  const xs = parts.flatMap((p) => p.x), zs = parts.flatMap((p) => p.z);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), z0 = Math.min(...zs), z1 = Math.max(...zs);
  const scale = (size - 2 * margin) / Math.max(x1 - x0, z1 - z0, 1);
  const rects = parts.map((p) => ({ storey: p.storey, x: margin + (p.x[0] - x0) * scale, y: margin + (p.z[0] - z0) * scale,
    w: Math.max(0.5, (p.x[1] - p.x[0]) * scale), h: Math.max(0.5, (p.z[1] - p.z[0]) * scale) }));
  return { rects, scale, width: size, height: Math.round(2 * margin + (z1 - z0) * scale) };
}
