import test from 'node:test';
import assert from 'node:assert/strict';
import { leaves, diffFields, show } from '../../web/catalog-logic.js';

test('leaves of nested data', () => {
  assert.deepEqual(leaves({ name: { vi: 'A', en: 'B' }, parts: [{ s: ['0', 'w'] }], tags: [], x: {} }),
    [['name.vi', 'A'], ['name.en', 'B'], ['parts[0].s[0]', '0'], ['parts[0].s[1]', 'w'], ['tags', []], ['x', {}]]);
});

test('field-level differences, added and removed fields included', () => {
  assert.deepEqual(diffFields({ front: 'Trắng', door: 'flat', name: { vi: 'A' } }, { front: 'Xám', name: { vi: 'A', en: 'B' } }), [
    { path: 'front', before: 'Trắng', after: 'Xám' }, { path: 'door', before: 'flat', after: undefined }, { path: 'name.en', before: undefined, after: 'B' }]);
  assert.deepEqual(diffFields({ a: 1 }, { a: 1 }), []);
  assert.deepEqual(diffFields(null, { a: 1 }), [{ path: 'a', before: undefined, after: 1 }]);
  assert.equal(show(undefined), '—');
  assert.equal(show([1]), '[1]');
});
