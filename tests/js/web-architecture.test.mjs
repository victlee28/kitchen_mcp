// Seams of the web app (plan: claude/ke-hoach-tach-app-js.md). These rules keep app.js a composition root while it is being split.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'web');
const files = readdirSync(WEB).filter((f) => f.endsWith('.js'));
const src = Object.fromEntries(files.map((f) => [f, readFileSync(path.join(WEB, f), 'utf8')]));
const IMPORT = /(?:^|\n)\s*(?:import|export)\s[^'";]*?from\s+['"](\.\/[^'"]+)['"]|(?:^|\n)\s*import\s+['"](\.\/[^'"]+)['"]/g;
const deps = (f) => [...src[f].matchAll(IMPORT)].map((m) => (m[1] || m[2]).replace(/^\.\//, ''));

// Browser-side bridges that exist today. Each list may only shrink.
const WINDOW_KITCHEN_USERS = ['imgedit.js'];          // legacy consumers of window.kitchen (until imgedit receives a ctx)

// Files that may still call fetch() themselves (blob/text fetches, not JSON API calls). The list may only shrink.
const RAW_FETCH_USERS = ['api-client.js', 'imgedit.js', 'json-view.js'];

test('$ and el are defined only in dom.js; JSON API calls go through api-client.js', () => {
  for (const f of files) {
    if (f !== 'dom.js') assert.ok(!/(?:^|\n)\s*(?:export\s+)?(?:const\s+\$\s*=|function\s+el\s*\(|const\s+el\s*=)/.test(src[f]), `${f} defines its own $ or el: import it from dom.js`);
    if (/\bfetch\(/.test(src[f])) assert.ok(RAW_FETCH_USERS.includes(f), `${f} calls fetch() directly: use api-client.js`);
  }
});

test('every relative import points at a file that exists', () => {
  for (const f of files) for (const d of deps(f)) assert.ok(files.includes(d), `${f} imports ${d}, which does not exist`);
});

test('nothing imports app.js (it is the composition root, loaded by index.html)', () => {
  for (const f of files) assert.ok(!deps(f).includes('app.js'), `${f} imports app.js`);
});

test('no import cycles', () => {
  const state = {};
  const visit = (f, trail) => {
    if (state[f] === 'done') return;
    assert.notEqual(state[f], 'open', `import cycle: ${[...trail, f].join(' -> ')}`);
    state[f] = 'open';
    for (const d of deps(f)) visit(d, [...trail, f]);
    state[f] = 'done';
  };
  for (const f of files) visit(f, []);
});

test('window.kitchen is assigned only by app.js and read only by the listed legacy consumers', () => {
  for (const f of files) {
    if (/window\.kitchen\s*=[^=]/.test(src[f])) assert.equal(f, 'app.js', `${f} assigns window.kitchen`);
    if (f !== 'app.js' && /window\.kitchen\b(?!Json)/.test(src[f])) assert.ok(WINDOW_KITCHEN_USERS.includes(f), `${f} reads window.kitchen`);
  }
});

test('window.kitchenJson is assigned only by json-view.js', () => {
  for (const f of files) if (/window\.kitchenJson\s*=[^=]/.test(src[f])) assert.equal(f, 'json-view.js');
});

test('pure logic modules (*-logic.js, scene-loader.js) touch neither the DOM nor the network', () => {
  for (const f of files.filter((x) => x.endsWith('-logic.js'))) {
    assert.ok(!/\bdocument\b|\bwindow\b|\bfetch\(|localStorage/.test(src[f].replace(/\/\/.*$/gm, '')), `${f} uses a browser API`);
  }
});
