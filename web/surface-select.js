// The wall surfaces the user picked (plan claude/ke-hoach-chon-mat-tuong): the list of ids, kept in step with the scene and shown on it.
// The viewer draws (setSelectedSurfaces) and says what is visible (surfaceShown); the rules are in wall-surface-logic.js.
import { keepSurfaces, nextSurfaces, surfaceSummary } from './wall-surface-logic.js';
import { tx } from './i18n.js';

export function createSurfaceSelection({ viewer, setStatus }) {
  let ids = []; let records = [];
  const show = () => viewer.setSelectedSurfaces(ids);
  return {
    /** A new scene: its faces (viewer surfaces map); ids that no longer exist or are hidden are dropped. */
    setScene(surfaces) { records = [...(surfaces?.values() || [])].map((e) => e.record); this.sync(); },
    /** A click on a face (or on nothing / something else: id null): 'click' | 'toggle' | 'region' | 'clear'. */
    pick(id, mode) {
      const next = nextSurfaces(ids, { type: id ? mode : 'clear', id }, records);
      const changed = next.ids.length !== ids.length || next.ids.some((x, i) => x !== ids[i]);
      ids = next.ids; show();
      if (next.notice) setStatus(next.notice, 'warn');
      else if (changed && ids.length) setStatus(`${surfaceSummary(ids, records)} — ${tx('ui.surface.hint')}`);
    },
    /** A right click on a face that is not picked yet picks it alone, so the menu always acts on what is lit. */
    contextOn(id) { if (id && !ids.includes(id)) this.pick(id, 'click'); },
    /** Walls hidden or shown (structure panel, views): hidden faces leave the selection. */
    sync() { ids = keepSurfaces(ids, records, (id) => viewer.surfaceShown(id)); show(); },
    ids: () => [...ids],
  };
}
