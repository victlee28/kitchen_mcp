// 18/11/2026: several cabinets picked in the image tab, then a right click: the menu's sentence (and the inbox record) is about all of them.
import test from 'node:test';
import assert from 'node:assert/strict';
import { withSelection } from '../../web/menu-logic.js';
import { selectedModules, partIndex } from '../../web/selection.js';
import { commandPlace } from '../../web/assist-logic.js';

const layers = [
  { id: 'TD15-drawer-1', variant: 'part', module: 'TD15', type: 'drawer' },
  { id: 'TD16-drawer-1', variant: 'part', module: 'TD16', type: 'drawer' },
  { id: 'TD16-drawer-2', variant: 'part', module: 'TD16', type: 'drawer' },
  { id: 'TD17-drawer-1', variant: 'part', module: 'TD17', type: 'drawer' },
  { id: 'wall-1', variant: 'part', module: 'STRUCT-wall_011', type: 'wall-face' },
];

test('the selected parts give their cabinets once each, walls left out', () => {
  const ids = ['TD15-drawer-1', 'TD16-drawer-1', 'TD16-drawer-2', 'TD17-drawer-1', 'wall-1'];
  assert.deepEqual(selectedModules(ids, partIndex(layers)), ['TD15', 'TD16', 'TD17']);
  assert.deepEqual(selectedModules([], partIndex(layers)), []);
});

test('a clicked cabinet in a selection of several carries them all; alone or outside it, nothing changes', () => {
  const t = { kind: 'part', part: 'drawer', id: 'TD15' };
  assert.deepEqual(withSelection(t, ['TD15', 'TD16', 'TD17']).modules, ['TD15', 'TD16', 'TD17']);
  assert.equal(withSelection(t, ['TD15']), t);
  assert.equal(withSelection(t, ['TD16', 'TD17']), t);
  assert.equal(withSelection({ kind: 'part', part: 'countertop', id: 'back' }, ['TD15', 'TD16']).modules, undefined);
  assert.equal(withSelection(null, ['TD15']), null);
});

test('the inbox record lists every selected cabinet', () => {
  const place = commandPlace(withSelection({ kind: 'part', part: 'drawer', id: 'TD15' }, ['TD15', 'TD16', 'TD17']), '3 tủ');
  assert.deepEqual(place.modules, ['TD15', 'TD16', 'TD17']);
  assert.equal(place.module, 'TD15');
  assert.equal(commandPlace({ kind: 'part', part: 'drawer', id: 'TD15' }).modules, undefined);
});

import { materialFromPicture, commandBody } from '../../web/assist-logic.js';

test('a sentence about the material in the picture is sent with it; one about cabinets is recognition', () => {
  for (const s of ['ốp tường bằng vật liệu trong ảnh tham chiếu cho tôi', 'sơn tủ màu giống ảnh', 'lát sàn gạch như hình', 'mặt bàn đá như ảnh'])
    assert.equal(materialFromPicture(s), true, s);
  for (const s of ['tạo tủ theo ảnh', 'nhận diện hệ tủ trong ảnh', ''])
    assert.equal(materialFromPicture(s), false, s);
  const pic = { name: 'a.png', type: 'image/png', data: 'AAAA' };
  assert.deepEqual(commandBody('ốp tường', 3, { kind: 'structure' }, 'vi', pic).picture, pic);
  assert.equal('picture' in commandBody('ốp tường', 3, {}, 'vi'), false);
});

test('a Shift group right-clicked: the clicked cabinet with the group, recorded with every cabinet', () => {
  const g = { modules: ['TD15', 'TD16', 'TD17'] };
  const place = commandPlace({ kind: 'part', part: 'drawer', id: 'TD16', modules: [...g.modules], group: g }, 'Nhóm');
  assert.deepEqual([place.kind, place.module, place.modules], ['part', 'TD16', ['TD15', 'TD16', 'TD17']]);
});
