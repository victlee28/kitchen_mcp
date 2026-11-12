import test from 'node:test';
import assert from 'node:assert/strict';
import { rowOf, stepOf, rowsOf, partsOf, letsText, letsOf, copyId } from '../../web/cabinet-type-logic.js';

const PARTS = [
  { when: 'y == 0', part: 'plinth', s: ['fs0', 'fs1'], d: ['0', 'depth - doorThickness - 50'], y: ['0', 'plinthHeight'] },
  { fronts: 'door', s: ['fs0', 'fs1'], y: ['body', 'top'] },
  { when: 'sections == 0', special: 'back-panel' },
  { special: 'front-sections', s: ['fs0', 'fs1'], y: ['body', 'top'] },
  { repeat: '3', as: 'i', let: { yb: 'y + i * 10' }, parts: [{ part: 'shelf', s: ['0', 'width'], d: ['0', 'depth'], y: ['yb', 'yb + 18'] }] },
];

test('steps survive the table both ways', () => {
  assert.deepEqual(partsOf(rowsOf(PARTS)), PARTS);
  assert.equal(rowOf(PARTS[4]).kind, 'repeat');
  assert.equal(rowOf(PARTS[0]).d1, 'depth - doorThickness - 50');
});

test('a row trims its formulas and drops an empty when', () => {
  assert.deepEqual(stepOf({ kind: 'part', when: ' ', name: ' shelf ', s0: ' 0', s1: 'width ', d0: '0', d1: 'depth', y0: 'y', y1: 'top' }),
    { part: 'shelf', s: ['0', 'width'], d: ['0', 'depth'], y: ['y', 'top'] });
  assert.throws(() => stepOf({ kind: 'repeat', json: '{bad' }));
});

test('helper values as lines; comparisons inside a formula are not a new name', () => {
  const lets = { body: 'max(y, plinthHeight) if y == 0 else y', h: '(top - body) / 3' };
  assert.equal(letsText(lets), 'body = max(y, plinthHeight) if y == 0 else y\nh = (top - body) / 3');
  assert.deepEqual(letsOf(letsText(lets) + '\n\nnot a line\n'), lets);
});

test('a copy keeps the storey prefix and a free id', () => {
  assert.equal(copyId('base-sink', ['base', 'base-sink']), 'base-sink-copy');
  assert.equal(copyId('base-sink', ['base-sink-copy', 'base-sink-copy-2']), 'base-sink-copy-3');
});
