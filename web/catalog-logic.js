// The catalog page's data work, without the DOM: what differs between two versions of an item, field by field.

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

/** Every leaf of a JSON value as [path, value] ("name.vi", "parts[2].s[1]"); an empty object or list is a leaf. */
export function leaves(value, path = '') {
  if (isObject(value) && Object.keys(value).length) return Object.entries(value).flatMap(([k, v]) => leaves(v, path ? `${path}.${k}` : k));
  if (Array.isArray(value) && value.length) return value.flatMap((v, i) => leaves(v, `${path}[${i}]`));
  return path ? [[path, value]] : [];       // an empty root has no leaf
}

/** [{path, before, after}] for each leaf that differs (undefined: the leaf is not there), in the order the paths first appear. */
export function diffFields(before, after) {
  const a = new Map(leaves(before ?? {})), b = new Map(leaves(after ?? {}));
  const paths = [...new Set([...a.keys(), ...b.keys()])];
  return paths.filter((p) => JSON.stringify(a.get(p)) !== JSON.stringify(b.get(p))).map((p) => ({ path: p, before: a.get(p), after: b.get(p) }));
}

export const show = (v) => (v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v));
