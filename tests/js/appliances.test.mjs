// Appliance models in the web app: picking an appliance in the 3D view, the model popup, the stand-in box drawing.
import test from 'node:test';
import assert from 'node:assert/strict';
import { actionsFor, applianceLayer, modelChoices, pickTarget } from '../../web/menu-logic.js';
import { applianceDecor } from '../../web/scene-loader.js';

test('an appliance in the 3D view is its own target, with no menu entries of its own (the command box only)', () => {
  const hit = [{ object: { userData: { module: 'TB4', role: 'Cooktop_Induction', appliance: 'TB4' } } }];
  const t = pickTarget(hit, ['TD1']);
  assert.deepEqual(t, { kind: 'appliance', id: 'TB4', applianceType: 'Cooktop_Induction' });
  assert.deepEqual(actionsFor(t, { module: [] }), []);
  assert.equal(applianceLayer('TB4', 'cooktop'), 'TB4-cooktop-1');
});

test('the model popup says what fits; a model that changes the cabinet cannot be picked yet', () => {
  const c = modelChoices([
    { id: 'hob-ind-4z-60', name: 'Bếp từ 4 vùng 60 cm', size: { w: 590, d: 520, h: 55 }, cutout: { w: 560, d: 490 }, status: 'ok', reasons: [] },
    { id: 'fridge-int-56', name: 'Tủ lạnh âm tủ', size: { w: 560, d: 550, h: 1770 }, status: 'later', reasons: ['changes the cabinet'] }]);
  assert.equal(c[0].label, 'Bếp từ 4 vùng 60 cm · 590×520×55 · khoét 560×490 — vừa');
  assert.equal(c[0].pickable, true);
  assert.equal(c[1].pickable, false);
});

test('the stand-in box draws hob zones and burners, sink bowls and fridge doors', () => {
  const hob = applianceDecor({ zones: 1, burners: 1 }, { width: 730, height: 60, depth: 430 });
  assert.equal(hob.filter((d) => d.kind === 'disc').length, 2);
  assert.ok(hob.every((d) => d.y > 60), 'on the top face');
  assert.equal(applianceDecor({ basins: 2 }, { width: 820, height: 4, depth: 450 }).filter((d) => d.kind === 'rect').length, 2);
  assert.equal(applianceDecor({ doors: 2 }, { width: 600, height: 1600, depth: 620 })[0].kind, 'slot');
  assert.deepEqual(applianceDecor({}, { width: 1, height: 1, depth: 1 }), []);
});
