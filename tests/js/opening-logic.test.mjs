import test from 'node:test';
import assert from 'node:assert/strict';
import { frontRects, axisLines, previewLines, openingRows, unsureFields, formFromOpening, newForm, standardWidths, fieldsOf, opFromForm, removeOp, resetOp, adoptOp } from '../../web/opening-logic.js';

const door = { id: 'OP1', kind: 'door', openingType: 'door-swing-1', wallAxis: { id: 'back' }, center: 600, width: 900, axes: null, hAxes: null,
  leaves: [{ cols: [0, 1], rows: [0, 1], operation: 'swing', hinge: { axis: 'v', index: 0 }, side: '-', active: true }], sill: 0, height: 2100,
  clearWidth: 795, source: 'human', unsure: [], sourceElement: null };
const types = [{ id: 'door-swing-1', kind: 'door', defaultHeight: 2200, defaultSill: 0, sizes: { VN: { widths: [700, 800, 900, 1200] } } },
  { id: 'window-swing-2', kind: 'window', defaultHeight: 1200, defaultSill: 900 }];

test('rows keep the server order and say which openings are still as drawn', () => {
  const rows = openingRows({ openings: [{ ...door, id: 'opening_002', sourceElement: 'opening_002', asDrawn: true, opens: ['in'] }, door] });
  assert.deepEqual(rows.map((r) => [r.id, r.asDrawn, r.floorplan, r.opens[0] || null]), [['opening_002', true, 'opening_002', 'in'], ['OP1', false, null, null]]);
});

test('unsure fields map to the form fields painted yellow', () => {
  assert.deepEqual([...unsureFields(['width', 'leaves.0.hinge', 'leaves.1.side', 'wallAxis'])].sort(), ['center', 'hinge', 'opens', 'wallAxis', 'width']);
});

test('a form from an opening, and a new one centred on its axis', () => {
  const f = formFromOpening(door, ['in']);
  assert.deepEqual([f.openingType, f.wallAxis, f.center, f.width, f.opens, f.axes], ['door-swing-1', 'back', 600, 900, 'in', '']);
  const w = newForm('window', types, { id: 'right', length: 3000 });
  assert.deepEqual([w.openingType, w.wallAxis, w.center, w.width, w.height, w.sill, w.opens], ['window-swing-2', 'right', 1500, 1200, 1200, 900, 'out']);
  assert.equal(newForm('door', types, { id: 'WA-x', length: 9000, room: [2600, 6200] }).center, 4400, 'an axis running on past the room: the room\'s stretch');
  assert.deepEqual(standardWidths(types, 'door-swing-1', 'vn'), [700, 800, 900, 1200]);
});

test('the distance from a corner wins over the centre; empty axes mean the type template', () => {
  const f = { ...formFromOpening(door, ['in']), fromEdge: '350', fromEdgeAt: 'end', axes: '300', hinge: 'left' };
  assert.deepEqual(fieldsOf(f, 'door'), { kind: 'door', openingType: 'door-swing-1', wallAxis: 'back', fromEdge: { at: 'end', distance: 350 },
    width: 900, height: 2100, sill: 0, clearWidth: 795, axes: [300], hAxes: null, hinge: 'left', opens: 'in' });
});

test('operations: a new opening, only the changed fields of one, removal, reset and adoption', () => {
  const add = opFromForm(newForm('door', types, { id: 'back', length: 3650 }), { kind: 'door' });
  assert.equal(add.op, 'add-opening');
  assert.deepEqual([add.opening.kind, add.opening.center, add.opening.width, add.opening.source], ['door', 1825, 900, 'human']);
  const before = formFromOpening(door, ['in']);
  assert.deepEqual(opFromForm({ ...before, width: '800' }, { id: 'OP1', before }), { op: 'update-opening', id: 'OP1', changes: { width: 800 } });
  assert.deepEqual(opFromForm({ ...before, fromEdge: '100' }, { id: 'OP1', before }), { op: 'update-opening', id: 'OP1', changes: { fromEdge: { at: 'start', distance: 100 } } });
  assert.deepEqual([removeOp('OP1'), resetOp('opening_002'), adoptOp()], [{ op: 'remove-opening', id: 'OP1' }, { op: 'reset-opening', id: 'opening_002' }, { op: 'adopt-openings' }]);
});

test('preview lines name the opening instead of showing its JSON', () => {
  const words = (k, p) => `${k}:${p[0]}`;
  const lines = [{ kind: 'info', text: 'idCounters.OP: 5 → 6' }, { kind: 'info', text: 'openings[OP6]: — → {"id":"OP6"}' },
    { kind: 'info', text: 'openings[OP2]: {"width":900} → {"width":800}' }, { kind: 'warn', text: 'Mới: x' }];
  assert.deepEqual(previewLines(lines, words).map((l) => l.text), ['ui.opening.preview-added:OP6', 'ui.opening.preview-changed:OP2', 'Mới: x']);
});

test('axis lines: outer and middle verticals, sill, transom and head, the centre axis longer', () => {
  const o = { center: 1000, width: 1200, height: 2400, sill: 0, axes: null, hAxes: null };
  const lines = axisLines(o, { start: [0, 0], dir: [1, 0] }, { axesRatio: [0.75], hAxesFromSill: [2100] });
  assert.deepEqual(lines.filter((l) => !l.main && l.a.x === l.b.x).map((l) => l.a.x), [400, 1300, 1600]);
  assert.deepEqual(lines.filter((l) => !l.main && l.a.y === l.b.y).map((l) => l.a.y), [0, 2100, 2400]);
  const main = lines.find((l) => l.main);
  assert.deepEqual([main.a.x, main.a.y, main.b.y], [1000, 0, 2600]);
  assert.deepEqual(axisLines(o, null, null), []);
});

test('front view rectangles fit the picture with the floor at the bottom', () => {
  const rects = frontRects({ frame: [{ part: 'jamb-start', x0: 0, x1: 30, y0: 0, y1: 2100 }], leaves: [{ operation: 'swing', active: true, x0: 30, x1: 870, y0: 3, y1: 2067 }] }, 220, 180, 10);
  assert.deepEqual(rects.map((r) => r.kind), ['frame', 'active']);
  assert.ok(Math.abs(rects[0].y + rects[0].height - 170) < 1e-9);          // standing on the floor line
  assert.ok(rects.every((r) => r.x >= 10 && r.x + r.width <= 210 + 1e-9));
  assert.deepEqual(frontRects({}), []);
});
