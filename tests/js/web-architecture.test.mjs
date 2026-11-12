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

test('there is no window.kitchen bridge: modules talk through factories arguments and window events', () => {
  for (const f of files) assert.ok(!/window\.kitchen\b(?!Json)/.test(src[f].replace(/\/\/.*$/gm, '')), `${f} uses window.kitchen`);
});

test('window.kitchenJson is assigned only by json-view.js', () => {
  for (const f of files) if (/window\.kitchenJson\s*=[^=]/.test(src[f])) assert.equal(f, 'json-view.js');
});

const NO_DOM_FILES = ['design-controller.js'];   // the controller talks to the page only through callbacks

test('pure logic modules (*-logic.js, design-controller.js) touch neither the DOM nor the network', () => {
  for (const f of files.filter((x) => x.endsWith('-logic.js') || NO_DOM_FILES.includes(x))) {
    assert.ok(!/\bdocument\b|\bwindow\b|\bfetch\(|localStorage/.test(src[f].replace(/\/\/.*$/gm, '')), `${f} uses a browser API`);
  }
});

test('kitchen-viewer.js knows nothing of the design state, the API or the popup', () => {
  const code = src['kitchen-viewer.js'].replace(/\/\/.*$/gm, '');
  assert.ok(!/\bfetch\(|document\.getElementById|\bstate\b|\$\(/.test(code), 'kitchen-viewer.js reaches into the page');
  assert.deepEqual(deps('kitchen-viewer.js').sort(), ['menu-logic.js', 'scene-loader.js']);
});

test('design-editor.js depends only on dom/design-logic and receives everything else', () => {
  assert.deepEqual(deps('design-editor.js').sort(), ['design-logic.js', 'dom.js', 'i18n.js']);
  const code = src['design-editor.js'].replace(/\/\/.*$/gm, '');
  assert.ok(!/window\.kitchen|\bfetch\(/.test(code));
});

test('panels and header controls take their dependencies as arguments (no app.js, no window.kitchen)', () => {
  for (const f of ['design-create-panel.js', 'floorplan-panel.js', 'molding-panel.js', 'output-panel.js', 'header-controls.js']) {
    assert.ok(deps(f).every((d) => ['dom.js', 'design-logic.js', 'i18n.js'].includes(d)), `${f} imports ${deps(f).join(', ')}`);
    assert.ok(!/window\.kitchen\b(?!Json)/.test(src[f].replace(/\/\/.*$/gm, '')), `${f} uses window.kitchen`);
  }
});

test('app.js stays a composition root', () => {
  const lines = src['app.js'].split('\n').length;
  assert.ok(lines <= 100, `app.js has ${lines} lines: move logic into a module`);
});
