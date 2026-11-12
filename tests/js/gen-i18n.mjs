// Writes web/i18n-vi.js (the Vietnamese table bundled with the page) from data/i18n/vi.json. Run after editing the wording:
//   node tests/js/gen-i18n.mjs        (tests/js/i18n.test.mjs fails while the two differ)
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const bundle = () => '// GENERATED from data/i18n/vi.json by tests/js/gen-i18n.mjs — do not edit by hand.\n'
  + 'export default ' + JSON.stringify(JSON.parse(readFileSync(path.join(ROOT, 'data', 'i18n', 'vi.json'), 'utf8')), null, 1) + ';\n';
if (process.argv[1] === fileURLToPath(import.meta.url)) writeFileSync(path.join(ROOT, 'web', 'i18n-vi.js'), bundle());
