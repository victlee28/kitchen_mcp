import test from 'node:test';
import assert from 'node:assert/strict';
import { isClick, pickTarget, imageTarget, actionsFor, buildOp, layerFor, describeProposal, menuPosition, selectionEffect, sceneToMm, lineTemplate, floorPoint, dragChange, runModulesOf, openingCommand, cabinetTypeChoices } from '../../web/menu-logic.js';

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
  assert.deepEqual(pickTarget([{ ...hit({ module: 'TD1' }), point: { x: 1, z: 2 } }], ['TD1']),
    { kind: 'module', id: 'TD1', point: { x: 1, z: 2 } });
});

test('right-click door commands place an opening on the nearest wall at the clicked position', () => {
  const doc = { room: { walls: [{ id: 'WALL-BACK', start: { x: 0, z: 0 }, end: { x: -4000, z: 0 } }] } };
  const target = { kind: 'floor', point: { x: -2000, z: 100 } };
  const result = openingCommand('tạo cửa đi rộng 80 cm ở vị trí này', target, spec, doc);
  assert.deepEqual(result.operation, {
    op: 'add-opening',
    opening: { kind: 'door', openingType: 'door-swing-1', point: { x: -2000, z: 100 },
      width: 800, height: 2100, sill: 0, opens: 'in', source: 'human' },
  });
  assert.match(result.summary, /800 mm/);
  assert.equal(openingCommand('đổi màu tủ này', target, spec, doc), null);
});

test('door command can replace the selected cabinet as one atomic preview operation', () => {
  const doc = { room: { walls: [{ id: 'WALL-BACK', start: { x: 0, z: 0 }, end: { x: -4000, z: 0 } }] } };
  const result = openingCommand('thay thế vật đang chọn bằng cửa đi ở vị trí này',
    { kind: 'module', id: 'TD1', point: { x: -300, z: 500 } }, spec, doc);
  assert.deepEqual(result.operation, { op: 'multi', ops: [
    { op: 'remove', id: 'TD1', closeGap: false },
    { op: 'add-opening', opening: { kind: 'door', openingType: 'door-swing-1', point: { x: -300, z: 500 },
      width: 600, height: 720, sill: 0, opens: 'in', source: 'human' } },
  ] });
});

test('door replacement uses the nearest wall even when the selected object is over 900 mm away', () => {
  const doc = { room: { walls: [{ id: 'WALL-BACK', start: { x: 0, z: 0 }, end: { x: -4000, z: 0 } }] } };
  const result = openingCommand('thay thế vật đang chọn bằng cửa đi ở vị trí này',
    { kind: 'module', id: 'TD1', point: { x: -2000, z: 1200 } }, spec, doc);
  assert.equal(result.operation.ops[1].op, 'add-opening');
  assert.deepEqual(result.operation.ops[1].opening.point, { x: -2000, z: 1200 });
  assert.equal(result.warning, 'Không tìm thấy tường đủ gần vị trí đã chọn để đặt cửa.');
});

test('door replacement uses the selected floorplan object width without losing the wall endpoints', () => {
  const floorplan = { binding: { back: 'edge-1' },
    walls: [{ id: 'wall-1', sourceElement: 'wall_001', edge: 'edge-1' }],
    elements: [{ id: 'opening-object' }] };
  const imported = { ...spec, floorplan };
  const doc = { metadata: { floorplan: { binding: { back: 'edge-1' } } },
    room: { walls: [{ id: 'WALL-BACK', start: { x: 0, z: 0 }, end: { x: -4000, z: 0 } }],
      structures: [{ id: 'STRUCT-opening-object', sourceElement: 'opening-object', kind: 'furniture',
        outline: [{ x: -1374, z: 100 }, { x: -626, z: 100 }, { x: -626, z: 500 }, { x: -1374, z: 500 }], height: 2100 }] } };
  const result = openingCommand('thay thế vật đang chọn bằng cửa đi ở vị trí này',
    { kind: 'structure', id: 'STRUCT-opening-object', point: { x: -1000, z: 100 } }, imported, doc);
  assert.equal(result.operation.ops[1].opening.width, 748);
  assert.equal(result.operation.ops[1].opening.height, 2100);
  assert.deepEqual(result.operation.ops[1].opening.point, { x: -1000, z: 0 });          // the middle of the replaced object, on the wall
});

test('door commands leave the wall axis to the server: the clicked point goes as it is', () => {
  const imported = { floorplan: { walls: [{ id: 'wall-1', sourceElement: 'wall_006', edge: 0 }], elements: [] } };
  const doc = { room: { walls: [{ id: 'WALL-BACK', start: { x: 0, z: 0 }, end: { x: -4000, z: 0 } }] } };
  const result = openingCommand('tạo cửa đi ở vị trí này', { kind: 'floor', point: { x: -2000.4, z: 0 } }, imported, doc);
  assert.deepEqual(result.operation.opening.point, { x: -2000, z: 0 });
  assert.equal(result.operation.opening.width, 900);
  assert.equal(result.operation.opening.host, undefined);
});

test('door commands require a clicked point, warn but continue when far from a wall, and require a replacement target', () => {
  const doc = { room: { walls: [{ id: 'WALL-BACK', start: { x: 0, z: 0 }, end: { x: -4000, z: 0 } }] } };
  assert.throws(() => openingCommand('tạo cửa đi ở vị trí này', { kind: 'floor' }, spec, doc), Error);
  const far = openingCommand('tạo cửa đi ở vị trí này', { kind: 'floor', point: { x: 0, z: 2000 } }, spec, doc);
  assert.equal(far.operation.op, 'add-opening');
  assert.equal(far.warning, 'Không tìm thấy tường đủ gần vị trí đã chọn để đặt cửa.');
  assert.throws(() => openingCommand('thay thế vật đang chọn bằng cửa đi ở vị trí này',
    { kind: 'floor', point: { x: -2000, z: 0 } }, spec, doc), Error);
});

test('actions: modules get design and image actions, structures only view actions, corner modules cannot take a neighbour', () => {
  const ids = (t) => actionsFor(t, spec).map((a) => a.id);
  assert.deepEqual(ids({ kind: 'module', id: 'TD1' }), ['material', 'doorStyle', 'add', 'remove', 'image']);
  assert.ok(!ids({ kind: 'module', id: 'KG1' }).includes('add'));
  assert.deepEqual(ids({ kind: 'structure', id: 'S' }), ['struct-hide', 'struct-isolate', 'struct-all']);
  assert.deepEqual(ids({ kind: 'structure', id: 'S', point: { x: 1, z: 2 } }), ['run-i', 'struct-hide', 'struct-isolate', 'struct-all']);   // a clicked point is needed to pick the edge
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
  assert.deepEqual(before, { op: 'add', module: { width: 450 }, beforeModule: 'TD1', closeGap: true });
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

test('a structure hit carries the ray point so the server can pick the edge', () => {
  const t = pickTarget([{ object: { userData: { structureId: 'STRUCT-c1' }, visible: true }, point: { x: 1.5, y: 1, z: 2.5 } }], []);
  assert.deepEqual(t, { kind: 'structure', id: 'STRUCT-c1', point: { x: 1.5, z: 2.5 } });
});

test('picking: a module or a part selects the module; a countertop and empty space only clear the structure selection; a structure selects it', () => {
  assert.deepEqual(selectionEffect({ kind: 'module', id: 'TD1' }), { clearStructure: true, selectModule: 'TD1' });
  assert.deepEqual(selectionEffect({ kind: 'part', part: 'door', id: 'TD2' }), { clearStructure: true, selectModule: 'TD2' });
  assert.deepEqual(selectionEffect({ kind: 'part', part: 'countertop', id: 'x' }), { clearStructure: true });
  assert.deepEqual(selectionEffect({ kind: 'structure', id: 'STRUCT-w1' }), { selectStructure: 'STRUCT-w1' });
  assert.deepEqual(selectionEffect(null), { clearStructure: true });
});

test('scene units to millimetres: the factor table of the scene file (mm 0.001, cm 0.01, m 1; no unit = mm)', () => {
  assert.deepEqual(sceneToMm({ x: 1.5, z: -2 }, 'mm'), { x: 1500, z: -2000 });
  assert.deepEqual(sceneToMm({ x: 1.5, z: 0.2 }, 'cm'), { x: 150, z: 20 });
  assert.deepEqual(sceneToMm({ x: 1.5, z: 7 }, 'm'), { x: 1.5, z: 7 });
  assert.deepEqual(sceneToMm({ x: 1.5, z: 7 }, undefined), { x: 1500, z: 7000 });
});

const byRuns = { runs: [{ id: 'R1', x: -3000, z: 0, yaw: 0 }, { id: 'R2', x: 0, z: 0, yaw: -90 }], appliances: [],
  module: [{ id: 'A1', type: 'base', wall: 'island', run: 'R1', fromCorner: 0, width: 600, y: 0, height: 840, depth: 600 },
    { id: 'B1', type: 'base', wall: 'island', run: 'R2', fromCorner: 600, width: 600, y: 0, height: 840, depth: 600 },
    { id: 'K1', type: 'corner-shelf', wall: 'island', run: 'R1', turnsInto: 'R2', fromCorner: 2400, width: 600, rightLength: 600, y: 1500, height: 700, depth: 350 }] };

test('a cabinet of a run offers the run actions; a corner shelf by runs still takes no neighbour', () => {
  const ids = (id) => actionsFor({ kind: 'module', id }, byRuns).map((a) => a.id);
  assert.deepEqual(ids('A1').slice(-3), ['runMove', 'runStretch', 'runRemove']);
  assert.ok(!ids('K1').includes('add'));
  assert.deepEqual(actionsFor({ kind: 'part', part: 'door', id: 'A1' }, byRuns).map((a) => a.id).slice(-3), ['runMove', 'runStretch', 'runRemove']);
  assert.ok(!actionsFor({ kind: 'part', part: 'handle', id: 'A1' }, byRuns).some((a) => a.id.startsWith('run')));
  assert.ok(!actionsFor({ kind: 'module', id: 'TD1' }, spec).some((a) => a.id.startsWith('run')));
});

test('run operations: moving is told along the run and towards the room, whatever way the run looks', () => {
  assert.deepEqual(buildOp('runMove', 'A1', { along: 200, out: 0, turn: 0 }, byRuns), { op: 'move-run', id: 'R1', changes: { x: -2800, z: 0 } });
  assert.deepEqual(buildOp('runMove', 'A1', { along: 0, out: 300, turn: 0 }, byRuns), { op: 'move-run', id: 'R1', changes: { x: -3000, z: 300 } });
  assert.deepEqual(buildOp('runMove', 'B1', { along: 200, out: 100, turn: 0 }, byRuns), { op: 'move-run', id: 'R2', changes: { x: -100, z: 200 } });   // yaw -90: along is +z, out is -x
  assert.deepEqual(buildOp('runMove', 'B1', { along: 0, out: 0, turn: -90 }, byRuns), { op: 'move-run', id: 'R2', changes: { yaw: -180 } });
  assert.throws(() => buildOp('runMove', 'A1', { along: 0, out: 0, turn: 0 }, byRuns), /Nhập/);
  assert.throws(() => buildOp('runMove', 'A1', { along: 0, out: 0, turn: 30 }, byRuns), /góc xoay/);
  assert.deepEqual(buildOp('runStretch', 'A1', { end: 'start', delta: '-150' }, byRuns), { op: 'stretch-run', id: 'R1', end: 'start', delta: -150 });
  assert.throws(() => buildOp('runStretch', 'A1', { end: 'end', delta: 0 }, byRuns));
  assert.throws(() => buildOp('runStretch', 'A1', { end: 'middle', delta: 10 }, byRuns));
  assert.deepEqual(buildOp('runRemove', 'B1', {}, byRuns), { op: 'remove-run', id: 'R2' });
  assert.throws(() => buildOp('runMove', 'TD1', { along: 10 }, spec), /dãy/);
});

test('a cabinet added to the left of one in a run joins that run', () => {
  const op = buildOp('add', 'A1', { side: 'before', width: 400, closeGap: true }, byRuns);
  assert.deepEqual(op, { op: 'add', module: { width: 400 }, beforeModule: 'A1', closeGap: true }, 'the server places it in the run of A1');
});

test('drawing a run on the floor: the floor is the target where nothing else is, two points and a side make the template', () => {
  assert.deepEqual(floorPoint({ x: 0, y: 2, z: 4 }, { x: 0, y: -1, z: -1 }), { x: 0, z: 2 });
  assert.equal(floorPoint({ x: 0, y: 2, z: 4 }, { x: 0, y: 0.5, z: -1 }), null);
  const ids = (drawing) => actionsFor({ kind: 'floor', id: 'floor', point: { x: 0, z: 0 } }, spec, drawing).map((a) => a.id);
  assert.deepEqual(ids(null), ['line-start']);
  assert.deepEqual(ids({ x: 1, z: 2 }), ['line-end', 'line-start', 'line-cancel']);
  const left = lineTemplate({ x: -3000, z: 1000 }, { x: -1000, z: 1000 }, 'left', '  có chậu rửa ');
  assert.deepEqual(left, { kind: 'run-line', a: { x: -3000, z: 1000 }, b: { x: -1000, z: 1000 }, front: { x: -2000, z: 500 }, prompt: 'có chậu rửa' });
  assert.deepEqual(lineTemplate({ x: -3000, z: 1000 }, { x: -1000, z: 1000 }, 'right').front, { x: -2000, z: 1500 });
  assert.throws(() => lineTemplate({ x: 0, z: 0 }, { x: 100, z: 0 }, 'left'), /300/);
  assert.throws(() => lineTemplate({ x: 0, z: 0 }, { x: 1000, z: 0 }, 'up'));
  assert.deepEqual(selectionEffect({ kind: 'floor', id: 'floor' }), { clearStructure: true });
});

test('dragging a run handle: ends stretch along the run, the middle moves the run, a twitch is nothing', () => {
  assert.deepEqual(dragChange('end', 147, 900), { action: 'runStretch', form: { end: 'end', delta: 150 } });
  assert.deepEqual(dragChange('start', -204, 0), { action: 'runStretch', form: { end: 'start', delta: 200 } });     // pulled to the left: longer
  assert.deepEqual(dragChange('start', 96, 0), { action: 'runStretch', form: { end: 'start', delta: -100 } });
  assert.deepEqual(dragChange('move', 333, -58), { action: 'runMove', form: { along: 330, out: -60, turn: 0 } });
  assert.equal(dragChange('move', 3, -4), null);
  assert.deepEqual(runModulesOf(byRuns, 'K1'), ['A1', 'K1']);
  assert.equal(runModulesOf(spec, 'TD1'), null);
  assert.equal(dragChange('end', 4, 500), null);
  const made = dragChange('move', 200, 0);
  assert.deepEqual(buildOp(made.action, 'A1', made.form, byRuns), { op: 'move-run', id: 'R1', changes: { x: -2800, z: 0 } });
});

test('dragging the turn ring: the run turns about its origin by the angle the pointer went round, snapped near 45° steps', async () => {
  const { dragTurn, runOf } = await import('../../web/menu-logic.js');
  const o = { x: 0, z: 0 };
  assert.equal(dragTurn(o, { x: 1, z: 0 }, { x: 0, z: -1 }), 90, 'from +x round to -z: counter-clockwise, as yaw counts');
  assert.equal(dragTurn(o, { x: 1, z: 0 }, { x: 1, z: 0.3 }), -17);
  assert.equal(dragTurn(o, { x: 1, z: 0 }, { x: 1, z: -0.98 }), 45, 'within 3° of 45: 45');
  assert.equal(dragTurn(o, { x: 1, z: 0 }, { x: 1, z: 0.001 }), null, 'a twitch is nothing');
  assert.equal(dragTurn(o, { x: 1, z: 0 }, { x: -1, z: 0.01 }), 180);
  assert.deepEqual(dragChange('turn', 0, 0, 30), { action: 'runMove', form: { along: 0, out: 0, turn: 30, free: true } });
  assert.equal(dragChange('turn', 0, 0, null), null);
  const run = runOf(byRuns, 'A1');
  const op = buildOp('runMove', 'A1', { along: 0, out: 0, turn: 30, free: true }, byRuns);
  assert.deepEqual(op, { op: 'move-run', id: 'R1', changes: { yaw: ((run.yaw + 30 + 180) % 360 + 360) % 360 - 180 } });
  assert.throws(() => buildOp('runMove', 'A1', { turn: 30 }, byRuns), 'a free angle only from a drag');
});

test('a drawn line along a wall needs no "which side" question', async () => {
  const { lineAlongWall, wallSegments } = await import('../../web/menu-logic.js');
  const doc = { room: { structures: [{ kind: 'wall', outline: [{ x: 0, z: 0 }, { x: 4000, z: 0 }, { x: 4000, z: -120 }, { x: 0, z: -120 }] }] } };
  const walls = wallSegments(doc);
  assert.equal(lineAlongWall({ x: 500, z: 80 }, { x: 3000, z: 90 }, walls), true);
  assert.equal(lineAlongWall({ x: 500, z: 600 }, { x: 3000, z: 600 }, walls), false);      // in the middle of the room
  assert.equal(lineAlongWall({ x: 500, z: 80 }, { x: 500, z: 2500 }, walls), false);       // square to the wall
});

test('a cabinet added beside another can take any type of the same storey', () => {
  const items = [{ id: 'base', data: { storey: 'base', label: { vi: 'Tủ dưới' } } }, { id: 'base-drawers', data: { storey: 'base', label: { vi: 'Tủ ngăn kéo' } } },
    { id: 'upper', data: { storey: 'upper', label: { vi: 'Tủ trên' } } }];
  assert.deepEqual(cabinetTypeChoices(items, { type: 'base-drawers' }).map((c) => c.id), ['base-drawers', 'base']);
  assert.deepEqual(cabinetTypeChoices(items, { type: 'nope' }), []);
  const m = { id: 'TD1', type: 'base', wall: 'back', width: 600, y: 0, height: 720, depth: 560, fromCorner: 0 };
  const spec = { module: [m] };
  assert.equal(buildOp('add', 'TD1', { width: 600, side: 'after', type: 'base-drawers' }, spec).module.type, 'base-drawers');
  assert.equal(buildOp('add', 'TD1', { width: 600, side: 'after', type: 'base' }, spec).module.type, undefined);
});

test('a pixel of the layered picture opens the same menu target as the 3D view', () => {
  const ids = ['TD1', 'TC2'];
  assert.deepEqual(imageTarget({ id: 'STRUCT-furniture_021', module: 'STRUCT-furniture_021', type: 'structure-furniture' }, ids), { kind: 'structure', id: 'STRUCT-furniture_021', structureKind: 'furniture' });
  assert.deepEqual(imageTarget({ id: 'TB4-cooktop-1', module: 'TB4', type: 'cooktop', appliance: true }, ids), { kind: 'appliance', id: 'TB4', applianceType: 'cooktop' });
  assert.deepEqual(imageTarget({ id: 'room-countertop-1', module: null, type: 'countertop' }, ids), { kind: 'part', part: 'countertop', id: 'back' });
  assert.deepEqual(imageTarget({ id: 'TD1-drawer-1', module: 'TD1', type: 'drawer' }, ids), { kind: 'part', part: 'drawer', id: 'TD1' });
  assert.deepEqual(imageTarget({ id: 'TD1-handle-1', module: 'TD1', type: 'handle' }, ids), { kind: 'part', part: 'handle', id: 'TD1' });
  assert.deepEqual(imageTarget({ id: 'TC2-carcass-1', module: 'TC2', type: 'carcass' }, ids), { kind: 'module', id: 'TC2' });
  assert.deepEqual(imageTarget({ id: 'STRUCT-wall_006#inside', module: 'STRUCT-wall_006', type: 'wall-face', surface: 'wall_006#inside', parentType: 'structure-wall' }, ids),
    { kind: 'structure', id: 'STRUCT-wall_006', structureKind: 'wall', surface: 'wall_006#inside' }, 'a face of a floorplan wall');
  assert.deepEqual(imageTarget({ id: 'room-wall-1-2#inside', module: null, type: 'wall-face', surface: 'WALL-BACK#inside' }, ids),
    { kind: 'surface', id: 'WALL-BACK#inside', surface: 'WALL-BACK#inside' }, 'a face of a default wall');
  for (const nothing of [{ id: 'room-wall-1-2', module: null, type: 'wall' }, { id: 'TD9-door-1', module: 'TD9', type: 'door' }, null]) {
    assert.equal(imageTarget(nothing, ids), null);
  }
});

test('the picture gives the point of the plan its pixel lies on: the floor opens the run drawing, the rest carry the point (19/11)', () => {
  const ids = ['TD1'];
  const at = { point: { x: 1200.5, z: -340 }, floor: true };
  assert.deepEqual(imageTarget(null, ids, at), { kind: 'floor', id: 'floor', point: { x: 1200.5, z: -340 } }, 'nothing under the pixel: the floor');
  assert.deepEqual(imageTarget({ id: 'room-floor-1', module: null, type: 'floor' }, ids, at), { kind: 'floor', id: 'floor', point: { x: 1200.5, z: -340 } });
  assert.equal(imageTarget(null, ids, { point: null, floor: true }), null, 'a pixel above the horizon meets no floor');
  assert.equal(imageTarget(null, ids), null);
  const part = { point: { x: 10, z: 20 }, floor: false };
  assert.deepEqual(imageTarget({ id: 'STRUCT-furniture_021', module: 'STRUCT-furniture_021', type: 'structure-furniture' }, ids, part),
    { kind: 'structure', id: 'STRUCT-furniture_021', structureKind: 'furniture', point: { x: 10, z: 20 } }, 'run-i along an object needs its point');
  assert.deepEqual(imageTarget({ id: 'TD1-door-1', module: 'TD1', type: 'door' }, ids, part), { kind: 'part', part: 'door', id: 'TD1', point: { x: 10, z: 20 } });
  assert.deepEqual(imageTarget({ id: 'OP3-leaf-1', module: 'OP3', type: 'opening-leaf' }, ids, part), { kind: 'opening', id: 'OP3', point: { x: 10, z: 20 } },
    'a door the design placed');
  assert.deepEqual(actionsFor({ kind: 'opening', id: 'OP3' }, {}).map((a) => a.id), ['opening-edit', 'opening-reveal', 'image', 'opening-remove']);
});

test('a right click on a placed door or window in the 3D view opens its menu', () => {
  const hits = [{ object: { visible: true, userData: { type: 'opening', openingId: 'OP2', role: 'opening-leaf' } }, point: { x: 1, z: 2 } }];
  assert.deepEqual(pickTarget(hits, ['TD1']), { kind: 'opening', id: 'OP2', point: { x: 1, z: 2 } });
});
