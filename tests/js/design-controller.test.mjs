import test from 'node:test';
import assert from 'node:assert/strict';
import { createDesignController } from '../../web/design-controller.js';

// A fake server: each design answers its four endpoints; `delay[id]` (ms) slows that design down.
function setup({ designs = { a: 2, b: 5 }, delay = {} } = {}) {
  const calls = []; const lists = []; const opened = [];
  const api = async (path) => {
    calls.push(path);
    if (path === '/api/designs') return Object.entries(designs).map(([id, rev]) => ({ id, name: id, rev }));
    const [, , , id, part] = path.split('?')[0].split('/');
    if (delay[id]) await new Promise((r) => setTimeout(r, delay[id]));
    if (!part) return { rev: designs[id], spec: { module: [{ id: `${id}1` }] } };
    if (part === 'scene') return { views: { front: { name: 'F' } } };
    if (part === 'validate') return { valid: true, country: path.includes('country=') ? path.split('country=')[1] : null };
    if (part === 'threejs') return { units: 'mm', of: id };
    throw new Error('unexpected ' + path);
  };
  const c = createDesignController({ api, renderList: (list, sel) => lists.push({ ids: list.map((d) => d.id), sel }), onOpened: async (x) => { opened.push(x); } });
  return { c, calls, lists, opened };
}

test('open loads the four endpoints, updates the state, then shows the design', async () => {
  const { c, opened, calls } = setup();
  assert.equal(await c.open('a'), true);
  assert.equal(calls.filter((p) => p.startsWith('/api/designs/a')).length, 4);
  assert.deepEqual([c.state.id, c.state.rev, c.state.doc.of, Object.keys(c.state.views)], ['a', 2, 'a', ['front']]);
  assert.equal(opened.length, 1); assert.deepEqual([opened[0].id, opened[0].rev, opened[0].keepView, opened[0].validation.valid], ['a', 2, false, true]);
});

test('the standard (country) is sent to validate and threejs only', async () => {
  const { c, calls } = setup();
  c.state.qg = 'VN';
  await c.open('a', { keepView: true });
  assert.ok(calls.includes('/api/designs/a/validate?country=VN') && calls.includes('/api/designs/a/threejs?country=VN'));
  assert.ok(calls.includes('/api/designs/a') && calls.includes('/api/designs/a/scene'));
});

test('a load overtaken by a newer one is dropped: no state change, nothing shown', async () => {
  const { c, opened } = setup({ delay: { a: 40 } });
  const slow = c.open('a');           // the user clicks design a ...
  const fast = c.open('b');           // ... and quickly design b
  assert.equal(await fast, true); assert.equal(await slow, false);
  assert.equal(c.state.id, 'b'); assert.deepEqual(opened.map((o) => o.id), ['b']);
});

test('loadDesigns shows the list then opens the chosen design, default the first', async () => {
  const { c, lists, opened } = setup();
  await c.loadDesigns();
  assert.deepEqual(lists[0], { ids: ['a', 'b'], sel: 'a' }); assert.equal(opened[0].id, 'a');
  await c.loadDesigns('b');
  assert.deepEqual(lists[1], { ids: ['a', 'b'], sel: 'b' }); assert.equal(opened[1].id, 'b');
});

test('an empty list opens nothing', async () => {
  const { c, lists, opened } = setup({ designs: {} });
  await c.loadDesigns();
  assert.deepEqual(lists[0], { ids: [], sel: undefined }); assert.equal(opened.length, 0);
});

test('afterChange opens the design ONCE, keeping the view, then refreshes the list labels', async () => {
  const { c, lists, opened, calls } = setup();
  await c.afterChange({ id: 'b' });
  assert.equal(opened.length, 1); assert.deepEqual([opened[0].id, opened[0].keepView], ['b', true]);
  assert.equal(calls.filter((p) => p === '/api/designs/b').length, 1, 'the design is fetched once');
  assert.deepEqual(lists.at(-1), { ids: ['a', 'b'], sel: 'b' });
});

test('afterChange does not move the list selection back when the user switched design meanwhile', async () => {
  const { c, lists } = setup({ delay: { a: 40 } });
  const change = c.afterChange({ id: 'a' });         // a change of design a is being shown ...
  await c.open('b');                                 // ... and the user opens b
  await change;
  assert.equal(c.state.id, 'b'); assert.equal(lists.at(-1).sel, 'b');
});

test('refreshList only refreshes the list', async () => {
  const { c, lists, opened } = setup();
  await c.open('a');
  await c.refreshList();
  assert.deepEqual(lists.at(-1), { ids: ['a', 'b'], sel: 'a' }); assert.equal(opened.length, 1);
});
