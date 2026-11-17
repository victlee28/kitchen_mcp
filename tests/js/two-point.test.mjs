import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { twoPoint, MAX_PITCH_DEG } from '../../web/two-point.js';

test('an eye-level view looks level and shifts its picture so the aimed point stays in the middle', () => {
  const tp = twoPoint([0, 1.6, 4], [0, 0.9, 0], 50, 960);
  assert.deepEqual(tp.look.map((v) => Math.round(v * 1000) / 1000), [0, 1.6, 3]);
  const focal = 480 / Math.tan(25 * Math.PI / 180);
  assert.ok(Math.abs(tp.offsetY - focal * 0.7 / 4) < 1e-9, 'looking down: the window moves down by focal × tan(pitch)');
  assert.ok(twoPoint([0, 1, 4], [0, 1.5, 0], 50, 960).offsetY < 0, 'looking up: it moves up');
  assert.equal(twoPoint([0, 1, 0], [0, 1, 5], 50, 960).offsetY + 0, 0);
});

test('steep views (plan, overhead) keep their tilt, and the limit is the renderer’s', () => {
  assert.equal(twoPoint([0, 6.5, 0.001], [0, 0, 0], 36, 960), null);
  assert.equal(twoPoint([0, 5, 5], [0, 0, 0], 50, 960), null, '45°');
  assert.equal(twoPoint([0, 0, 0], [0, 3, 0], 50, 960), null);
  const py = readFileSync(new URL('../../kitchen/two_point.py', import.meta.url), 'utf8');
  assert.equal(Number(py.match(/^MAX_PITCH_DEG = ([\d.]+)/m)[1]), MAX_PITCH_DEG);
});
