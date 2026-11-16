// Wall surfaces (plan claude/ke-hoach-chon-mat-tuong): faces drawn one mesh each, a ray on any of a face's triangles gives that face,
// the selection rules (click, Ctrl/⌘, Shift by room, empty space), and how clicks and the menu share the keys.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../../web/vendor/three/build/three.module.min.js';
import { buildKitchen, surfaceGeometry } from '../../web/scene-loader.js';
import { nextSurfaces, keepSurfaces, surfaceSummary } from '../../web/wall-surface-logic.js';
import { clickEffect, opensMenu, pickTarget, selectionEffect, surfaceHit } from '../../web/menu-logic.js';

// one wall between the kitchen (z > 0) and a hall, 4000 x 2700 x 100, a door 900 wide through it; and a column-like wall of no room
const SIDE = (face, origin, u, normal, room, holes = []) => ({ id: `w1#${face}`, wall: 'w1', structure: 'STRUCT-w1', face, normal, origin, u, width: 4000, height: 2700, holes, room });
const SURFACES = [
  SIDE('inside', [0, 0, 0], [1, 0], [0, 0, 1], 'kitchen', [[1000, 1900, 0, 2100]]),
  SIDE('outside', [4000, 0, -100], [-1, 0], [0, 0, -1], 'hall', [[2100, 3000, 0, 2100]]),
  { id: 'w1#start', wall: 'w1', structure: 'STRUCT-w1', face: 'start', normal: [-1, 0, 0], origin: [0, 0, -100], u: [0, 1], width: 100, height: 2700, holes: [], room: null },
  { id: 'w1#end', wall: 'w1', structure: 'STRUCT-w1', face: 'end', normal: [1, 0, 0], origin: [4000, 0, 0], u: [0, -1], width: 100, height: 2700, holes: [], room: null },
  { id: 'w1#top', wall: 'w1', structure: 'STRUCT-w1', face: 'top', normal: [0, 1, 0], y: 2700, outline: [{ x: 0, z: 0 }, { x: 4000, z: 0 }, { x: 4000, z: -100 }, { x: 0, z: -100 }], room: null },
  { id: 'w1#bottom', wall: 'w1', structure: 'STRUCT-w1', face: 'bottom', normal: [0, -1, 0], y: 0, outline: [{ x: 0, z: 0 }, { x: 4000, z: 0 }, { x: 4000, z: -100 }, { x: 0, z: -100 }], room: null },
  { id: 'w2#inside', wall: 'w2', structure: 'STRUCT-w2', face: 'inside', normal: [-1, 0, 0], origin: [5000, 0, 3000], u: [0, -1], width: 3000, height: 2700, holes: [], room: 'kitchen' },
  { id: 'w3#side-a', wall: 'w3', structure: 'STRUCT-w3', face: 'side-a', normal: [1, 0, 0], origin: [9000, 0, 0], u: [0, -1], width: 1000, height: 2700, holes: [], room: null },
];
const DOC = {
  units: 'mm', materials: [{ id: 'MAT-WALL', threeMaterialType: 'MeshStandardMaterial', color: '#eeeeee' }, { id: 'MAT-SURFACE-1', threeMaterialType: 'MeshStandardMaterial', color: '#7d8a5f' }],
  room: {
    walls: [], surfaces: SURFACES.map((s) => (s.id === 'w2#inside' ? { ...s, materialId: 'MAT-SURFACE-1' } : s)),
    structures: ['w1', 'w2', 'w3'].map((w) => ({ id: `STRUCT-${w}`, sourceElement: w, kind: 'wall', outline: [{ x: 0, z: 0 }, { x: 1, z: 0 }, { x: 1, z: 1 }], base: 0, height: 2700 })),
  },
  modules: [], appliances: [], accessories: [], decorations: [], cameras: [], lighting: [],
};

test('every face is one mesh; a ray on any of its triangles gives that face', () => {
  const k = buildKitchen(DOC, THREE, { edges: false });
  assert.equal(k.surfaces.size, SURFACES.length);
  k.root.updateMatrixWorld(true);
  const ray = new THREE.Raycaster();
  for (const [id, { mesh }] of k.surfaces) {
    const pos = mesh.geometry.getAttribute('position'); const index = mesh.geometry.index;
    const tris = (index ? index.count : pos.count) / 3;
    assert.ok(tris >= 2, `${id}: ${tris} triangles`);
    for (let t = 0; t < tris; t++) {
      const c = new THREE.Vector3();
      for (let j = 0; j < 3; j++) c.add(new THREE.Vector3().fromBufferAttribute(pos, index ? index.getX(t * 3 + j) : t * 3 + j));
      c.divideScalar(3).applyMatrix4(mesh.matrixWorld);
      const n = new THREE.Vector3(...(SURFACES.find((s) => s.id === id).normal));
      ray.set(c.clone().addScaledVector(n, 0.01), n.clone().negate());
      const hit = ray.intersectObjects(k.surfacePickables, false);
      assert.equal(surfaceHit(hit), id, `triangle ${t} of ${id}`);
    }
  }
  assert.equal(k.surfaces.get('w2#inside').mesh.material.color.getHexString(), '7d8a5f', 'a face with its own finish');
  assert.ok(k.structures.get('STRUCT-w1').meshes.length === 6, 'the wall element owns its six faces (structure panel, hide, isolate)');
});

test('a side lies on its wall, faces its room and leaves the door open', () => {
  const g = surfaceGeometry(SURFACES[0], 0.001, THREE); g.computeBoundingBox();
  const b = g.boundingBox;
  assert.deepEqual([b.min.x, b.max.x, b.min.y, b.max.y].map((v) => Math.round(v * 1000)), [0, 4000, 0, 2700]);
  assert.ok(Math.abs(b.min.z) < 1e-6 && Math.abs(b.max.z) < 1e-6, 'on the wall plane z = 0');
  g.computeVertexNormals();
  const n = g.getAttribute('normal');
  assert.ok(n.getZ(0) > 0.99, 'facing the kitchen (+z)');
  const area = (geo) => { let a = 0; const p = geo.getAttribute('position'); const ix = geo.index; for (let t = 0; t < ix.count / 3; t++) { const v = [0, 1, 2].map((j) => new THREE.Vector3().fromBufferAttribute(p, ix.getX(t * 3 + j))); a += v[1].sub(v[0]).cross(v[2].sub(v[0])).length() / 2; } return a; };
  assert.ok(Math.abs(area(g) - (4 * 2.7 - 0.9 * 2.1)) < 1e-6, 'the door hole is cut out');
  const top = surfaceGeometry(SURFACES[4], 0.001, THREE); top.computeBoundingBox();
  assert.ok(Math.abs(top.boundingBox.min.y - 2.7) < 1e-6 && top.boundingBox.min.z < -0.09, 'the top at its height, outline as drawn');
});

test('click picks one face, Ctrl/⌘ adds and drops, Shift takes the room, empty space clears', () => {
  let s = nextSurfaces([], { type: 'click', id: 'w1#inside' }, SURFACES);
  assert.deepEqual(s.ids, ['w1#inside']);
  s = nextSurfaces(s.ids, { type: 'click', id: 'w1#outside' }, SURFACES);
  assert.deepEqual(s.ids, ['w1#outside'], 'a click replaces the selection');
  s = nextSurfaces(s.ids, { type: 'toggle', id: 'w1#top' }, SURFACES);
  assert.deepEqual(s.ids, ['w1#outside', 'w1#top']);
  s = nextSurfaces(s.ids, { type: 'toggle', id: 'w1#outside' }, SURFACES);
  assert.deepEqual(s.ids, ['w1#top'], 'Ctrl on a picked face drops only that face');
  s = nextSurfaces(s.ids, { type: 'region', id: 'w1#inside' }, SURFACES);
  assert.deepEqual(s.ids, ['w1#inside', 'w2#inside'], 'every face looking into the kitchen, and only those');
  s = nextSurfaces(s.ids, { type: 'region', id: 'w3#side-a' }, SURFACES);
  assert.deepEqual(s.ids, ['w3#side-a'], 'no room: only the face clicked');
  assert.ok(s.notice, 'and it says there is no area to spread to');
  assert.deepEqual(nextSurfaces(s.ids, { type: 'clear' }, SURFACES).ids, []);
  assert.deepEqual(nextSurfaces(['w1#top'], { type: 'click', id: 'nope#x' }, SURFACES).ids, ['w1#top'], 'an unknown face changes nothing');
});

test('hidden or vanished faces leave the selection; the summary counts walls', () => {
  assert.deepEqual(keepSurfaces(['w1#inside', 'w2#inside', 'gone#x'], SURFACES, (id) => !id.startsWith('w2')), ['w1#inside']);
  assert.match(surfaceSummary(['w1#inside', 'w1#top', 'w2#inside'], SURFACES), /3\D+2/);
  assert.equal(surfaceSummary([], SURFACES), '');
});

test('keys: Ctrl/⌘ and Shift on a face change the faces only; Shift elsewhere keeps the cabinet group; Ctrl on a face opens no menu', () => {
  assert.deepEqual(clickEffect({ ctrl: true }, 'w1#inside'), { surface: 'toggle', shiftPick: false, pick: false });
  assert.deepEqual(clickEffect({ meta: true }, 'w1#inside'), { surface: 'toggle', shiftPick: false, pick: false });
  assert.deepEqual(clickEffect({ shift: true }, 'w1#inside'), { surface: 'region', shiftPick: false, pick: false });
  assert.deepEqual(clickEffect({ shift: true }, null), { surface: null, shiftPick: true, pick: false });
  assert.deepEqual(clickEffect({}, 'w1#inside'), { surface: 'click', shiftPick: false, pick: true });
  assert.deepEqual(clickEffect({}, null), { surface: 'clear', shiftPick: false, pick: true });
  assert.equal(opensMenu({ button: 0, ctrl: true }, 'w1#inside'), false);
  assert.equal(opensMenu({ button: 0, ctrl: true }, null), true, 'Ctrl+click elsewhere still opens the menu');
  assert.equal(opensMenu({ button: 2 }, 'w1#inside'), true, 'the right button always does');
});

test('the menu target knows the face; the wall is then chosen quietly (the face is lit, not the wall)', () => {
  const face = (userData) => ({ object: { userData, visible: true }, point: { x: 1, z: 2 } });
  const t = pickTarget([face({ structureId: 'STRUCT-w1', kind: 'wall', surfaceId: 'w1#inside' })], []);
  assert.deepEqual([t.kind, t.id, t.surface], ['structure', 'STRUCT-w1', 'w1#inside']);
  assert.deepEqual(selectionEffect(t), { selectStructure: 'STRUCT-w1', quiet: true });
  const d = pickTarget([face({ type: 'wall', surfaceId: 'WALL-BACK#inside' })], []);
  assert.deepEqual([d.kind, d.surface], ['surface', 'WALL-BACK#inside'], 'a default wall face');
  const behind = pickTarget([face({ module: 'TD1' }), face({ type: 'wall', surfaceId: 'WALL-BACK#inside' })], ['TD1']);
  assert.equal(behind.kind, 'module', 'a face behind a cabinet is not what was clicked');
});
