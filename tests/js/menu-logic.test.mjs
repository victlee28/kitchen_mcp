import test from 'node:test';
import assert from 'node:assert/strict';
import { isClick, pickTarget, actionsFor, buildOp, layerFor, describeProposal, menuPosition } from '../../web/menu-logic.js';

const spec = { module: [{ id: 'TD1', type: 'base', wall: 'back', y: 0, height: 720, depth: 560, fromCorner: 0, width: 600, material: 'Trắng mờ' }, { id: 'KG1', type: 'corner-shelf', wall: 'corner' }] };
const hit = (userData, visible = true) => ({ object: { userData, visible } });

test('a short press without movement is a click; a drag or a long press is not', () => {
  assert.equal(isClick({ x: 10, y: 10, t: 0 }, { x: 12, y: 11, t: 200 }), true);
  assert.equal(isClick({ x: 10, y: 10, t: 0 }, { x: 40, y: 10, t: 200 }), false);   // camera pan
  assert.equal(isClick({ x: 10, y: 10, t: 0 }, { x: 10, y: 10, t: 2000 }), false);
  assert.equal(isClick(null, { x: 0, y: 0, t: 0 }), false);
});

test('the nearest module or visible structure wins; empty space and unknown meshes give nothing', () => {
  assert.deepEqual(pickTarget([hit({ module: 'TD1' })], ['TD1']), { kind: 'module', id: 'TD1' });
  assert.deepEqual(pickTarget([hit({ structureId: 'STRUCT-w1' }), hit({ module: 'TD1' })], ['TD1']), { kind: 'structure', id: 'STRUCT-w1' });
  assert.deepEqual(pickTarget([hit({ structureId: 'STRUCT-w1' }, false), hit({ module: 'TD1' })], ['TD1']), { kind: 'module', id: 'TD1' });
  assert.equal(pickTarget([hit({ module: 'molding-1' })], ['TD1']), null);
  assert.equal(pickTarget([], ['TD1']), null);
});

test('actions: modules get design and image actions, structures only view actions, corner modules cannot take a neighbour', () => {
  const ids = (t) => actionsFor(t, spec).map((a) => a.id);
  assert.deepEqual(ids({ kind: 'module', id: 'TD1' }), ['material', 'doorStyle', 'add', 'remove', 'image']);
  assert.ok(!ids({ kind: 'module', id: 'KG1' }).includes('add'));
  assert.deepEqual(ids({ kind: 'structure', id: 'S' }), ['struct-hide', 'struct-isolate', 'struct-all']);
  assert.deepEqual(ids(null), []);
});

test('buildOp makes structured operations and refuses incomplete or pointless forms', () => {
  assert.deepEqual(buildOp('material', 'TD1', { material: ' Laminate xanh ' }, spec), { op: 'update', id: 'TD1', changes: { material: 'Laminate xanh' }, closeGap: false });
  assert.throws(() => buildOp('material', 'TD1', { material: '  ' }, spec), /vật liệu/);
  assert.throws(() => buildOp('material', 'TD1', { material: 'Trắng mờ' }, spec), /đã dùng/);
  assert.deepEqual(buildOp('doorStyle', 'TD1', { style: 'glass' }, spec).changes, { doorStyle: 'glass' });
  assert.throws(() => buildOp('doorStyle', 'TD1', { style: 'round' }, spec));
  assert.deepEqual(buildOp('remove', 'TD1', { closeGap: true }, spec), { op: 'remove', id: 'TD1', closeGap: true });
  const after = buildOp('add', 'TD1', { side: 'after', width: '450', closeGap: true }, spec);
  assert.deepEqual(after, { op: 'add', module: { width: 450 }, afterModule: 'TD1', closeGap: true });
  const before = buildOp('add', 'TD1', { side: 'before', width: 450, closeGap: true }, spec);
  assert.equal(before.module.fromCorner, 0);
  assert.equal(before.afterModule, undefined);
  assert.throws(() => buildOp('add', 'TD1', { side: 'after', width: 50 }, spec), /Chiều rộng/);
  assert.throws(() => buildOp('add', 'KG1', { side: 'after', width: 400 }, spec));
  assert.throws(() => buildOp('remove', 'GONE', {}, spec), /Không còn module/);
});

test('layers: fronts for appearance changes, the module for the rest', () => {
  assert.equal(layerFor('material', 'TD1'), 'frontSections:TD1');
  assert.equal(layerFor('doorStyle', 'TD1'), 'frontSections:TD1');
  assert.equal(layerFor('image', 'TD1'), 'module:TD1');
});

test('describeProposal: changes, neighbours, new and resolved issues, refusals', () => {
  const base = { applicable: true, unchanged: false, diff: { modules: { added: [], removed: ['TD1'], changed: { TD2: [{ field: 'fromCorner', old: 600, new: 0 }] } }, other: [], truncated: false },
    outsideScope: ['TD2'], validation: { introduced: [{ severity: 'error', content: 'quá dài' }], resolved: [{ severity: 'warning', content: 'cũ' }] } };
  const lines = describeProposal(base);
  assert.deepEqual(lines.map((l) => l.kind), ['info', 'info', 'warn', 'bad', 'ok']);
  assert.match(lines[1].text, /fromCorner 600 → 0/);
  assert.equal(describeProposal({ ...base, unchanged: true })[0].kind, 'warn');
  assert.match(describeProposal({ applicable: false, error: { message: 'x' } })[0].text, /Không áp dụng được: x/);
});

test('menu stays inside the viewport', () => {
  assert.deepEqual(menuPosition(900, 700, 300, 200, 1000, 800), { left: 692, top: 592 });
  assert.deepEqual(menuPosition(-5, 2, 300, 200, 1000, 800), { left: 8, top: 8 });
});

test('schema 1.4 partRef: a click on a handle, door or countertop maps to that part; the handle in front wins over its door', () => {
  const ids = ['TD1'];
  assert.deepEqual(pickTarget([hit({ module: 'TD1', part: { kind: 'handle', module: 'TD1' } }), hit({ module: 'TD1', part: { kind: 'door', module: 'TD1' } })], ids), { kind: 'part', part: 'handle', id: 'TD1' });
  assert.deepEqual(pickTarget([hit({ module: 'TD1', part: { kind: 'door', module: 'TD1' } })], ids), { kind: 'part', part: 'door', id: 'TD1' });
  assert.deepEqual(pickTarget([hit({ module: 'countertop-back', part: { kind: 'countertop', wall: 'back' } })], ids), { kind: 'part', part: 'countertop', id: 'back' });
  assert.deepEqual(pickTarget([hit({ module: 'TD1', part: { kind: 'door', module: 'GONE' } })], ids), { kind: 'module', id: 'TD1' });   // module no longer in the design: fall back
});

test('part actions and their operations', () => {
  const sp = { ...spec, common: { material: { base: 'Trắng', countertop: 'Đá trắng' }, countertopOverhang: 20 } };
  sp.module[0].handle = { variant: 'bar', material: 'Nhôm' };
  const ids = (t) => actionsFor(t, sp).map((a) => a.id);
  assert.deepEqual(ids({ kind: 'part', part: 'countertop', id: 'back' }), ['countertopMaterial', 'countertopOverhang']);
  assert.deepEqual(ids({ kind: 'part', part: 'handle', id: 'TD1' }), ['handleVariant', 'handleMaterial']);
  assert.ok(ids({ kind: 'part', part: 'door', id: 'TD1' }).includes('doorStyle'));
  assert.ok(!ids({ kind: 'part', part: 'drawer', id: 'TD1' }).includes('doorStyle'));
  assert.deepEqual(buildOp('countertopMaterial', 'back', { material: 'Đá granite tối' }, sp), { op: 'common', changes: { material: { base: 'Trắng', countertop: 'Đá granite tối' } } });
  assert.throws(() => buildOp('countertopMaterial', 'back', { material: 'Đá trắng' }, sp), /đã dùng/);
  assert.deepEqual(buildOp('countertopOverhang', 'back', { overhang: '35' }, sp), { op: 'common', changes: { countertopOverhang: 35 } });
  assert.throws(() => buildOp('countertopOverhang', 'back', { overhang: '500' }, sp));
  assert.deepEqual(buildOp('handleVariant', 'TD1', { variant: 'knob' }, sp).changes, { handle: { variant: 'knob', material: 'Nhôm' } });   // keeps the other override
  assert.deepEqual(buildOp('handleMaterial', 'TD1', { material: 'Đồng thau' }, sp).changes, { handle: { variant: 'bar', material: 'Đồng thau' } });
  assert.throws(() => buildOp('handleVariant', 'TD1', { variant: 'ring' }, sp));
});
