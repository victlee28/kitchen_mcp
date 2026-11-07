import test from 'node:test';
import assert from 'node:assert/strict';
import { FIELDS, moduleOrder, moduleLabel, formChanges, moldingsOp, styleHasMoldings, aiExportUrls } from '../../web/design-logic.js';

test('module list order: back, corner, right, left, island; then height; then distance from the corner', () => {
  const mods = [{ id: 'I', wall: 'island', y: 0 }, { id: 'U', wall: 'back', y: 1450, fromCorner: 0 }, { id: 'B2', wall: 'back', y: 0, fromCorner: 600 },
    { id: 'B1', wall: 'back', y: 0, fromCorner: 0 }, { id: 'R', wall: 'right', y: 0 }, { id: 'K', wall: 'corner', y: 0 }, { id: 'L', wall: 'left', y: 0 }];
  assert.deepEqual(moduleOrder(mods).map((m) => m.id), ['B1', 'B2', 'U', 'K', 'R', 'L', 'I']);
  assert.equal(mods[0].id, 'I', 'the input is not reordered in place');
});

test('module label shows the distance from the corner and the width (or the back length of a corner unit)', () => {
  assert.equal(moduleLabel({ type: 'base', wall: 'back', fromCorner: 600, width: 800 }), 'base · back · 600+800');
  assert.equal(moduleLabel({ type: 'corner-shelf', wall: 'corner', backLength: 900 }), 'corner-shelf · corner · 0+900');
});

const base = { type: 'base', wall: 'back', fromCorner: 0, width: 600, y: 0, doors: [300, 300] };
const same = Object.fromEntries(FIELDS.map(([k]) => [k, base[k] === undefined ? '' : String(base[k])]));

test('form diff: untouched form changes nothing; empty numbers are ignored; numbers become numbers', () => {
  assert.deepEqual(formChanges(base, same, '300, 300'), {});
  assert.deepEqual(formChanges(base, { ...same, width: '800', type: 'base-sink' }, '300,300'), { width: 800, type: 'base-sink' });
  assert.deepEqual(formChanges(base, { ...same, width: '' }, '300,300'), {});
  assert.deepEqual(formChanges(base, { ...same, tall: '0' }, '300,300'), {}, 'a missing number counts as 0');
  assert.deepEqual(formChanges(base, same, '400, 200'), { doors: [400, 200] });
  assert.deepEqual(formChanges(base, same, ' , '), { doors: [] });
});

test('molding payload keeps the old record fields, only for ticked variants, and sends the style', () => {
  const spec = { moldings: [{ id: 'crown-molding', variant: 'crown', profile: 'old', openEnd: 'flat-cut', enabled: false, extra: 7 }] };
  const ui = { crown: true, base: false, crownProfile: 'classic-crown-layered', baseProfile: 'classic-base', openEnd: 'return-to-wall', style: 'Classic' };
  assert.deepEqual(moldingsOp(spec, ui), { op: 'set-moldings', style: 'Classic', moldings: [
    { id: 'crown-molding', variant: 'crown', profile: 'classic-crown-layered', openEnd: 'return-to-wall', enabled: true, extra: 7 }] });
  const both = moldingsOp({}, { ...ui, base: true }).moldings;
  assert.deepEqual(both.map((m) => m.id), ['crown-molding', 'base-molding']);
  assert.deepEqual(moldingsOp({}, { ...ui, crown: false }).moldings, []);
  assert.equal(styleHasMoldings('Neoclassical'), true); assert.equal(styleHasMoldings('Modern'), false);
});

test('AI export URLs carry the lighting under the name the server reads', () => {
  const u = aiExportUrls('d1', 4, 'late-afternoon');
  assert.equal(u.shortUrl, '/api/designs/d1/ai-export?embedImages=1&lighting=late-afternoon');
  assert.equal(u.fullUrl, '/api/designs/d1/ai-export?format=day-du&lighting=late-afternoon');
  assert.equal(u.shortName, 'd1-rev4-ai-request-short.json');
  assert.equal(u.zipName(5), 'd1-rev5-ai-package.zip');
  assert.match(u.fullTitle, /d1 · rev 4$/);
});
