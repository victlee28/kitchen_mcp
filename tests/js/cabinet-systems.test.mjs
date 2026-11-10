// Shift-selection by cabinet system: the pure parts (design-logic.js, menu-logic.js, selection.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import { groupLabel, groupLayerIds, groupRole, manySystems, shiftGroup } from '../../web/design-logic.js';
import { buildGroupOp, groupActions, SYSTEM_STYLES, systemTemplate } from '../../web/menu-logic.js';
import { shiftGroupId } from '../../web/selection.js';

// furniture_003: A1, A2 (base), U1 (upper), H1 (loft). furniture_017: C1, C2 (base).
const systems = {
  A1: { system: 'furniture_003', tier: 'base', storey: 'base' }, A2: { system: 'furniture_003', tier: 'base', storey: 'base' },
  U1: { system: 'furniture_003', tier: 'upper', storey: 'upper' }, H1: { system: 'furniture_003', tier: 'upper', storey: 'loft' },
  C1: { system: 'furniture_017', tier: 'base', storey: 'base' }, C2: { system: 'furniture_017', tier: 'base', storey: 'base' },
};
const spec = { common: { material: {} }, runs: [], appliances: [],
  module: ['A1', 'A2', 'U1', 'H1', 'C1', 'C2'].map((id) => ({ id, type: 'base', wall: 'island', run: id[0] === 'C' ? 'R3' : 'R1', fromCorner: 0, width: 600, y: 0, height: 840, depth: 600, ...(id === 'A2' ? { material: 'Sồi' } : {}) })) };

test('the role comes from what was clicked; worktops, structures and the floor make no group', () => {
  assert.equal(groupRole({ kind: 'part', part: 'door', id: 'A1' }), 'door');
  assert.equal(groupRole({ kind: 'part', part: 'drawer', id: 'A1' }), 'drawer');
  assert.equal(groupRole({ kind: 'part', part: 'handle', id: 'A1' }), 'handle');
  assert.equal(groupRole({ kind: 'module', id: 'A1' }), 'all');
  for (const t of [{ kind: 'part', part: 'countertop', id: 'back' }, { kind: 'structure', id: 'S' }, { kind: 'floor', id: 'floor' }, null]) assert.equal(groupRole(t), null);
});

test('Shift selects the same system and tier only; loft goes with upper', () => {
  assert.deepEqual(shiftGroup({ kind: 'part', part: 'door', id: 'A1' }, systems), { system: 'furniture_003', tier: 'base', role: 'door', modules: ['A1', 'A2'] });
  assert.deepEqual(shiftGroup({ kind: 'part', part: 'door', id: 'C2' }, systems).modules, ['C1', 'C2']);
  assert.deepEqual(shiftGroup({ kind: 'module', id: 'U1' }, systems).modules, ['U1', 'H1']);
  assert.equal(shiftGroup({ kind: 'part', part: 'countertop', id: 'x' }, systems), null);
  assert.equal(shiftGroup({ kind: 'module', id: 'nope' }, systems), null);
});

test('only modules that show a part of the role join (a drawer-only cabinet is not in the doors group)', () => {
  const has = (id, role) => !(id === 'A2' && role === 'door');
  assert.deepEqual(shiftGroup({ kind: 'part', part: 'door', id: 'A1' }, systems, has).modules, ['A1']);
});

test('labels and the image-tab layers of a group', () => {
  const g = shiftGroup({ kind: 'part', part: 'drawer', id: 'A1' }, systems);
  assert.equal(groupLabel(g), '2 tủ · mặt ngăn kéo tủ dưới · hệ furniture_003');
  assert.equal(manySystems(systems), true);
  assert.equal(manySystems({ A1: systems.A1, A2: systems.A2 }), false);
  assert.deepEqual(groupLayerIds(g, true), ['sys:furniture_003:tier:base:drawer', 'sys:furniture_003:tier:base:front', 'sys:furniture_003:tier:base:all']);
  assert.deepEqual(groupLayerIds({ ...g, role: 'handle' }, false), ['tier:base:handle']);
});

test('group menu: actions fit the role; one operation for every module, modules it would not change are left out', () => {
  const doors = { system: 'furniture_003', tier: 'base', role: 'door', modules: ['A1', 'A2'] };
  assert.deepEqual(groupActions(doors).map((a) => a.id), ['material', 'doorStyle', 'handleVariant', 'handleMaterial', 'image', 'replaceSystem']);
  assert.deepEqual(groupActions({ ...doors, role: 'handle' }).map((a) => a.id), ['handleVariant', 'handleMaterial', 'image', 'replaceSystem']);
  assert.deepEqual(groupActions({ ...doors, role: 'drawer' }).map((a) => a.id), ['material', 'handleVariant', 'handleMaterial', 'image', 'replaceSystem']);
  assert.deepEqual(buildGroupOp('material', doors, { material: 'Sồi' }, spec), { op: 'update', id: 'A1', changes: { material: 'Sồi' }, closeGap: false }, 'A2 already has it');
  assert.deepEqual(buildGroupOp('doorStyle', doors, { style: 'glass' }, spec).ops.map((o) => o.id), ['A1', 'A2']);
  assert.throws(() => buildGroupOp('material', { ...doors, modules: ['A2'] }, { material: 'Sồi' }, spec), /đã dùng/);
  assert.throws(() => buildGroupOp('remove', doors, {}, spec), /không hỗ trợ/);
  assert.throws(() => buildGroupOp('image', doors, {}, spec));
});

test('image tab: Shift on a part uses its system group when the catalogue has one, the design-wide group otherwise', () => {
  const layers = [{ id: 'tier:base:door' }, { id: 'sys:furniture_003:tier:base:door' }, { id: 'sys:furniture_017:tier:base:door' }, { id: 'sys:furniture_003:tier:base:front' }, { id: 'tier:base:handle' }];
  assert.equal(shiftGroupId({ storey: 'base', type: 'door', cabinetSystemId: 'furniture_003' }, layers), 'sys:furniture_003:tier:base:door');
  assert.equal(shiftGroupId({ storey: 'base', type: 'glass-door', cabinetSystemId: 'furniture_017' }, layers), 'sys:furniture_017:tier:base:door');
  assert.equal(shiftGroupId({ storey: 'base', type: 'carcass', cabinetSystemId: 'furniture_003' }, layers), 'sys:furniture_003:tier:base:front', '"all" was dropped as equal to "front"');
  assert.equal(shiftGroupId({ storey: 'base', type: 'handle', cabinetSystemId: 'furniture_003' }, layers), null, 'never the design-wide handles of another system');
  assert.equal(shiftGroupId({ storey: 'base', type: 'handle', cabinetSystemId: 'auto-R1' }, layers), 'tier:base:handle', 'one system: the design-wide group');
  assert.equal(shiftGroupId({ storey: 'loft', type: 'door' }), 'tier:upper:door');
});

test('replacing a whole system: a sentence lays it out again, none restyles it', () => {
  assert.deepEqual(systemTemplate('wall_h10', '  có chậu rửa  ', 'warm-oak'), { kind: 'replace-system', system: 'wall_h10', prompt: 'có chậu rửa' });
  assert.deepEqual(systemTemplate('wall_h10', '', 'warm-oak'), { kind: 'replace-system', system: 'wall_h10', style: 'warm-oak' });
  assert.deepEqual(systemTemplate('auto-R1', null), { kind: 'replace-system', system: 'auto-R1', style: 'auto' });
  assert.throws(() => systemTemplate(undefined, 'x'), /hệ tủ/);
  assert.throws(() => systemTemplate('S', '', 'no-such'), /Phong cách/);
  assert.equal(SYSTEM_STYLES[0][0], 'auto');
  assert.throws(() => buildGroupOp('replaceSystem', { system: 'S', tier: 'base', role: 'door', modules: ['A1'] }, {}, {}), /không hỗ trợ/);
});
