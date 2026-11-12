// The cabinet type editor's data, without the DOM: a type's steps as table rows and back, its helper values as "name = formula" lines.
// A row: { kind: 'part' | 'fronts' | 'special' | 'repeat', when, name, s0, s1, d0, d1, y0, y1, json }. A repeat (and anything the table
// cannot show) is kept as its JSON in `json`.

export const STEP_KINDS = ['part', 'fronts', 'special', 'repeat'];
export const PART_TYPES = ['carcass', 'side-panel', 'shelf', 'plinth', 'drawer', 'door', 'glass-door'];
export const FRONT_KINDS = ['door', 'glass-door', 'drawer'];
export const SPECIALS = ['back-panel', 'front-sections'];

const pair = (v) => (Array.isArray(v) ? v.map(String) : ['', '']);

/** One step of the type (catalog JSON) as a table row. */
export function rowOf(step) {
  const when = step.when || '';
  if (step.part !== undefined) {
    const [s0, s1] = pair(step.s), [d0, d1] = pair(step.d), [y0, y1] = pair(step.y);
    return { kind: 'part', when, name: step.part, s0, s1, d0, d1, y0, y1, json: '' };
  }
  if (step.fronts !== undefined) {
    const [s0, s1] = pair(step.s), [y0, y1] = pair(step.y);
    return { kind: 'fronts', when, name: step.fronts, s0, s1, d0: '', d1: '', y0, y1, json: '' };
  }
  if (step.special !== undefined) {
    const [s0, s1] = step.s ? pair(step.s) : ['', ''], [y0, y1] = step.y ? pair(step.y) : ['', ''];
    return { kind: 'special', when, name: step.special, s0, s1, d0: '', d1: '', y0, y1, json: '' };
  }
  const { when: _w, ...rest } = step;
  return { kind: 'repeat', when, name: '', s0: '', s1: '', d0: '', d1: '', y0: '', y1: '', json: JSON.stringify(rest) };
}

/** A table row as a step (throws on a repeat row whose JSON does not parse). */
export function stepOf(row) {
  const when = (row.when || '').trim();
  const w = when ? { when } : {};
  const t = (x) => String(x ?? '').trim();
  if (row.kind === 'part') return { ...w, part: t(row.name), s: [t(row.s0), t(row.s1)], d: [t(row.d0), t(row.d1)], y: [t(row.y0), t(row.y1)] };
  if (row.kind === 'fronts') return { ...w, fronts: t(row.name), s: [t(row.s0), t(row.s1)], y: [t(row.y0), t(row.y1)] };
  if (row.kind === 'special') {
    const span = t(row.s0) ? { s: [t(row.s0), t(row.s1)], y: [t(row.y0), t(row.y1)] } : {};
    return { ...w, special: t(row.name), ...span };
  }
  return { ...w, ...JSON.parse(row.json || '{}') };
}

export const rowsOf = (parts) => (parts || []).map(rowOf);
export const partsOf = (rows) => rows.map(stepOf);

/** {name: formula} as "name = formula" lines, and back (blank lines and lines without "=" are left out). */
export const letsText = (lets) => Object.entries(lets || {}).map(([k, v]) => `${k} = ${v}`).join('\n');
export function letsOf(text) {
  const out = {};
  for (const line of String(text || '').split('\n')) {
    const at = line.indexOf('=');
    if (at > 0 && line[at + 1] !== '=' && line[at - 1] !== '!' && line[at - 1] !== '<' && line[at - 1] !== '>') {
      const name = line.slice(0, at).trim();
      if (name) out[name] = line.slice(at + 1).trim();
    }
  }
  return out;
}

/** A new id for a copy of type `id` that keeps its storey prefix and is not taken: base-sink -> base-sink-copy, base-sink-copy-2... */
export function copyId(id, taken) {
  const have = new Set(taken);
  let n = 1, out = `${id}-copy`;
  while (have.has(out)) { n += 1; out = `${id}-copy-${n}`; }
  return out;
}
