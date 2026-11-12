import { test } from 'node:test';
import assert from 'node:assert/strict';
import { saveTemplateRequest, savedMessage } from '../../web/design-logic.js';

const state = { selected: 'TD2', rev: 7, systems: { TD2: { system: 'wall_006', tier: 'base', storey: 'base' } } };

test('the request names the selected cabinet system, the name and the revision', () => {
  assert.deepEqual(saveTemplateRequest(state, '  Bếp nhà tôi '), { system: 'wall_006', label: 'Bếp nhà tôi', rev: 7 });
});

test('no system or no name is refused', () => {
  assert.throws(() => saveTemplateRequest({ ...state, selected: 'X' }, 'a'));
  assert.throws(() => saveTemplateRequest(state, '   '));
});

test('the message lists the cabinets left out', () => {
  const plain = savedMessage({ id: 'bep-nha-toi', skipped: [] }, 'Bếp nhà tôi');
  assert.match(plain, /bep-nha-toi/);
  assert.match(savedMessage({ id: 'x', skipped: ['TD9', 'TT4'] }, 'X'), /TD9, TT4/);
  assert.ok(!plain.includes('TD9'));
});
