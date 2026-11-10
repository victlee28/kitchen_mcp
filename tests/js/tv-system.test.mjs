// TV wall units (10/11/2026): the command box sends "tạo hệ tủ tivi" to the furniture's run; the TV box shows a screen.
import test from 'node:test';
import assert from 'node:assert/strict';
import { templateIntent, systemIntent } from '../../web/assist-logic.js';
import { applianceDecor } from '../../web/scene-loader.js';

test('a TV unit sentence is a described run, not a system change', () => {
  for (const t of ['tạo hệ tủ tivi', 'làm kệ tivi gỗ sồi', 'tạo tủ TV']) {
    assert.deepEqual(templateIntent(t), { kind: 'run-i', described: true }, t);
    assert.equal(systemIntent(t), null, t);
  }
});

test('the TV stand-in box draws its screen on the front', () => {
  const d = applianceDecor({ kind: 'tv', finish: 'black-glass' }, { width: 1450, height: 830, depth: 30 });
  assert.equal(d.length, 1);
  assert.equal(d[0].kind, 'slot');
  assert.equal(d[0].z, 31);
});

test('a sentence about the TV system goes to the whole system, the TV words kept for the server', () => {
  assert.deepEqual(systemIntent('đổi hệ tivi sang kín cả vách'), { prompt: 'tivi sang kín cả vách' });
  assert.deepEqual(systemIntent('thay cả hệ tủ thành tủ tivi kệ treo'), { prompt: 'tủ tivi kệ treo' });
});
