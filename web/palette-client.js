// The fixed colour tables (catalog kind "palette", locked: builtin only): edit-zone colours, appliance box finishes...
// Loaded once, before the modules that import it run (top-level await); an unreachable server leaves the tables empty.
import * as catalog from './catalog-client.js';
import { setFinishes } from './scene-loader.js';

async function load() {
  try {
    const d = await catalog.list('palette', 'vi');
    return Object.fromEntries(d.items.map((it) => [it.id, it.data.colors]));
  } catch { return {}; }
}

/** '#rrggbb' -> 0xrrggbb (null stays null). */
export const hexNumber = (h) => (typeof h === 'string' ? parseInt(h.replace('#', ''), 16) : null);

export const PALETTES = await load();
setFinishes(Object.fromEntries(Object.entries(PALETTES['appliance-finish'] || {}).map(([k, v]) => [k, hexNumber(v)])));
