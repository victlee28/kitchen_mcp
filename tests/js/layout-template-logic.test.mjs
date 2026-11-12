import test from 'node:test';
import assert from 'node:assert/strict';
import { rowsOf, stepsOf, rowOf, stepOf, topView } from '../../web/layout-template-logic.js';

const STEPS = [
  { do: 'corner-base', wall: 'right', type: 'base-corner-sink', width: 'g + 450', blind: 'g', doors: ['450'] },
  { do: 'base-run', wall: 'back', start: 'g', length: 'back - g', appliances: [{ when: 'fridge', items: ['sink'] }, { items: ['cooktop'] }], fridgeAtEnd: 'fridge',
    extras: [{ type: 'base-wine', width: '300', at: 'end' }] },
  { do: 'corner-shelf' },
  { do: 'upper-run', wall: 'back', start: '600', end: 'back - lr' },
];

test('steps survive the editor rows both ways', () => {
  assert.deepEqual(stepsOf(rowsOf(STEPS)), STEPS);
  assert.equal(rowOf(STEPS[0]).doors, '450');
});

test('an empty field is left out; bad JSON throws', () => {
  assert.deepEqual(stepOf({ do: 'upper-run', wall: 'left', start: ' 0 ', end: '' }), { do: 'upper-run', wall: 'left', start: '0' });
  assert.throws(() => stepOf({ do: 'base-run', wall: 'back', appliances: '[oops' }));
});

test('top view fits the parts, back wall at the top', () => {
  const v = topView([{ storey: 'base', x: [-3000, 0], z: [0, 600] }, { storey: 'base', x: [-600, 0], z: [600, 2400] }], 248, 4);
  assert.equal(v.scale, 240 / 3000);
  assert.deepEqual(v.rects[0], { storey: 'base', x: 4, y: 4, w: 240, h: 48 });
  assert.equal(v.height, Math.round(8 + 2400 * v.scale));
  assert.deepEqual(topView([]).rects, []);
});
