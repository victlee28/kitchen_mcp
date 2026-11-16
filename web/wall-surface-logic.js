// Selecting wall surfaces (plan claude/ke-hoach-chon-mat-tuong): pure functions over ids, no DOM, no three.js.
// A surface is one flat face of one wall (schema 1.7 room.surfaces: {id, wall, face, room}); the selection is a list of their ids.
import { tx } from './i18n.js';

/**
 * The selection after an action: `click` (just this face), `toggle` (Ctrl/⌘: add it, or take it out), `region` (Shift: every face looking
 * into the same room; a face with no room selects itself and says so), `clear`. `surfaces`: the scene's records ({id, wall, room}).
 * Returns { ids, notice } — notice: a message for the status line, or ''.
 */
export function nextSurfaces(ids, action, surfaces) {
  const current = ids || [];
  const byId = new Map((surfaces || []).map((s) => [s.id, s]));
  const id = action?.id;
  switch (action?.type) {
    case 'clear': return { ids: [], notice: '' };
    case 'click': return byId.has(id) ? { ids: [id], notice: '' } : { ids: current, notice: '' };
    case 'toggle':
      if (!byId.has(id)) return { ids: current, notice: '' };
      return { ids: current.includes(id) ? current.filter((x) => x !== id) : [...current, id], notice: '' };
    case 'region': {
      const rec = byId.get(id);
      if (!rec) return { ids: current, notice: '' };
      if (!rec.room) return { ids: [id], notice: tx('ui.surface.no-region') };
      return { ids: (surfaces || []).filter((s) => s.room === rec.room).map((s) => s.id), notice: '' };
    }
    default: return { ids: current, notice: '' };
  }
}

/** Ids that still name a face of the scene and are not hidden (`shown(id)`): a hidden wall takes its faces out of the selection. */
export function keepSurfaces(ids, surfaces, shown = () => true) {
  const known = new Set((surfaces || []).map((s) => s.id));
  return (ids || []).filter((id) => known.has(id) && shown(id));
}

/** "N faces on M walls" (empty selection: ''). */
export function surfaceSummary(ids, surfaces) {
  if (!ids?.length) return '';
  const wallOf = new Map((surfaces || []).map((s) => [s.id, s.wall]));
  const walls = new Set(ids.map((id) => wallOf.get(id) ?? id.split('#')[0]));
  return tx('ui.surface.summary', { n: ids.length, m: walls.size });
}
