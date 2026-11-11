// What the pages need before their modules run (top-level await, so importing this waits): the wording of the chosen language and the
// fixed colour tables. Imported by app.js, imgedit.js and photo-render.js; loaded once.
import { loadLang } from './i18n.js';
import './palette-client.js';

try { await loadLang(); } catch { /* no server wording: keys show as themselves */ }
