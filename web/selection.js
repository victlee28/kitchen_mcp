// Pure helpers for multi-selection in the "image editing by layers" tab. No DOM: used by imgedit.js and tested with node.
// A selection is an ordered list of part IDs. Catalogue entries come from GET /api/designs/<id>/layers (variant: part | group).

export const TIER_OF = { base: 'base', upper: 'upper', loft: 'upper', tall: 'tall', corner: 'corner' };  // loft shares the upper tier
const FRONT = ['door', 'glass-door', 'drawer'];
const ROLE_VI = { handle: 'tay nắm', door: 'cánh tủ', 'glass-door': 'cánh kính', drawer: 'mặt ngăn kéo', carcass: 'thân tủ',
  'side-panel': 'tấm hông', shelf: 'kệ', plinth: 'len chân', countertop: 'mặt đá', molding: 'phào' };

export const roleName = (type) => ROLE_VI[type] || type;
export const partIndex = (layers) => new Map(layers.filter((l) => l.variant === 'part').map((l) => [l.id, l]));

/** Group a Shift+click selects for a clicked part: the same role within the same tier. */
export function shiftGroupId(part) {
  const tier = TIER_OF[part.storey];
  if (!tier) return `type:${part.type}`;
  if (part.type === 'handle') return `tier:${tier}:handle`;
  if (part.type === 'door' || part.type === 'glass-door') return `tier:${tier}:door`;
  if (part.type === 'drawer') return `tier:${tier}:drawer`;
  return `tier:${tier}:all`;  // cabinet body clicked: fronts and handles of the tier
}

/** Part IDs a Ctrl+click adds or removes. With a handle selected, a door/drawer stands for its own handle(s), and the reverse. */
export function ctrlIds(selType, part, layers) {
  if (!selType || part.type === selType) return { ids: [part.id] };
  const parts = layers.filter((l) => l.variant === 'part');
  if (selType === 'handle' && FRONT.includes(part.type)) {
    const ids = parts.filter((l) => l.type === 'handle' && l.parent === part.id).map((l) => l.id);
    return ids.length ? { ids } : { error: 'Cánh/ngăn kéo này không có tay nắm (tay âm hoặc nhấn mở)' };
  }
  if (FRONT.includes(selType) && part.type === 'handle') {
    const host = parts.find((l) => l.id === part.parent);
    return host && host.type === selType ? { ids: [host.id] } : { error: `Tay nắm này không gắn với ${roleName(selType)}` };
  }
  return { error: `Ctrl+bấm chỉ thêm chi tiết cùng loại (đang chọn: ${roleName(selType)})` };
}

/** Add the IDs, or remove them when all are already selected. */
export function toggleIds(sel, ids) {
  return ids.every((i) => sel.includes(i)) ? sel.filter((i) => !ids.includes(i)) : [...sel, ...ids.filter((i) => !sel.includes(i))];
}

/** Catalogue layer whose members equal the selection exactly (so the job can target it by name), or null. */
export function layerIdFor(ids, layers) {
  if (!ids.length) return null;
  const want = [...ids].sort().join('|');
  const hit = layers.find((l) => [...(l.component || [l.id])].sort().join('|') === want);
  return hit ? hit.id : null;
}

/** Split an ad-hoc selection into one list per part type: a job task keeps a single role for its prompt. */
export function partitionByType(ids, index) {
  const groups = new Map();
  for (const id of ids) {
    const t = index.get(id)?.type ?? '?';
    groups.set(t, [...(groups.get(t) || []), id]);
  }
  return [...groups.values()];
}

export const targetFor = (ids) => (ids.length === 1 ? ids[0] : `parts:${ids.join(',')}`);

/** Part IDs behind a task target (a catalogue layer or `parts:a,b,c`). */
export function partsOf(target, layers) {
  if (target.startsWith('parts:')) return target.slice(6).split(',').filter(Boolean);
  const l = layers.find((x) => x.id === target);
  return l ? (l.component || [l.id]) : [target];
}

/** Short text for a task target in the task list. */
export function targetLabel(target, layers) {
  if (!target.startsWith('parts:')) return target;
  const ids = partsOf(target, layers);
  const p = layers.find((l) => l.id === ids[0]);
  return `${ids.length} × ${roleName(p?.type || '?')}`;
}
