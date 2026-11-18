import test from 'node:test';
import assert from 'node:assert/strict';
import { clampView, zoomAt, panBy, wheelFactor, transformOf, fitted, ZOOM_MAX, ZOOM_STEP } from '../../web/zoom-logic.js';

const W = 800, H = 600;

test('zooming keeps the point under the pointer where it is', () => {
  const v = zoomAt(fitted(), 2, 200, 150, W, H);
  assert.equal(v.scale, 2);
  // the picture point under (200, 150) before: (200, 150); after: x + 200 * 2 = 200
  assert.equal(v.x + 200 * v.scale, 200);
  assert.equal(v.y + 150 * v.scale, 150);
});

test('the picture never gets smaller than the frame nor bigger than the limit', () => {
  assert.deepEqual(zoomAt(fitted(), 0.5, 100, 100, W, H), fitted());
  let v = fitted();
  for (let i = 0; i < 30; i += 1) v = zoomAt(v, ZOOM_STEP, 400, 300, W, H);
  assert.equal(v.scale, ZOOM_MAX);
});

test('panning stops at the picture edges', () => {
  const v = zoomAt(fitted(), 2, 0, 0, W, H);            // top-left corner kept
  assert.deepEqual(panBy(v, 50, 50, W, H), { scale: 2, x: 0, y: 0 });
  assert.deepEqual(panBy(v, -5000, -5000, W, H), { scale: 2, x: -800, y: -600 });
  assert.deepEqual(clampView({ scale: 1, x: -30, y: 12 }, W, H), fitted());
});

test('wheel up zooms in, down zooms out; the CSS transform', () => {
  assert.equal(wheelFactor(-100), ZOOM_STEP);
  assert.equal(wheelFactor(100), 1 / ZOOM_STEP);
  assert.equal(transformOf({ scale: 2, x: -10, y: -5 }), 'translate(-10px, -5px) scale(2)');
});
