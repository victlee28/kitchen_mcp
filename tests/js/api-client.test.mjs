import test from 'node:test';
import assert from 'node:assert/strict';
import { request, api, ApiError, errorMessage, createStatus } from '../../web/api-client.js';

const fakeFetch = (status, body, { json = true } = {}) => {
  const calls = [];
  globalThis.fetch = async (path, opt) => { calls.push({ path, opt }); return { status, ok: status >= 200 && status < 300, json: async () => { if (!json) throw new Error('not json'); return body; } }; };
  return calls;
};

test('request returns the status and data without throwing; sends JSON only with a body', async () => {
  let calls = fakeFetch(409, { error: 'stale' });
  assert.deepEqual(await request('/x', 'POST', { a: 1 }), { status: 409, ok: false, data: { error: 'stale' } });
  assert.equal(calls[0].opt.method, 'POST'); assert.equal(calls[0].opt.headers['Content-Type'], 'application/json'); assert.equal(calls[0].opt.body, '{"a":1}');
  calls = fakeFetch(200, { v: 1 });
  assert.deepEqual(await request('/y'), { status: 200, ok: true, data: { v: 1 } });
  assert.equal(calls[0].opt.method, 'GET'); assert.deepEqual(calls[0].opt.headers, {}); assert.equal(calls[0].opt.body, undefined);
  fakeFetch(502, null, { json: false });
  assert.deepEqual(await request('/z'), { status: 502, ok: false, data: {} });
});

test('api returns data, or throws ApiError carrying status and data', async () => {
  fakeFetch(200, { id: 'd1' });
  assert.deepEqual(await api('/ok'), { id: 'd1' });
  fakeFetch(409, { error: 'Thiết kế đã đổi' });
  await assert.rejects(api('/bad', 'POST', {}), (e) => e instanceof ApiError && e.status === 409 && e.message === 'Thiết kế đã đổi' && e.data.error === 'Thiết kế đã đổi');
  fakeFetch(500, null, { json: false });
  await assert.rejects(api('/boom'), (e) => e.message === 'HTTP 500');
});

test('error message lists the offending parts', () => {
  assert.equal(errorMessage(400, { error: 'sai', part: [{ position: 'TD1', errors: 'x' }, { position: 'TD2', errors: 'y' }] }), 'sai — TD1: x; TD2: y');
  assert.equal(errorMessage(404, {}), 'HTTP 404');
});

test('run writes progress, success and failure into the status element', async () => {
  const node = { textContent: '', className: '' };
  const { setStatus, run } = createStatus(node);
  setStatus('hi', 'ok'); assert.deepEqual(node, { textContent: 'hi', className: 'status ok' });
  const seen = [];
  await run('làm gì đó', async () => { seen.push(node.textContent); });
  assert.deepEqual(seen, ['làm gì đó…']); assert.deepEqual(node, { textContent: 'Xong: làm gì đó', className: 'status ok' });
  const log = console.error; console.error = () => {};
  await run('hỏng', async () => { throw new Error('lỗi rồi'); });
  console.error = log;
  assert.deepEqual(node, { textContent: 'lỗi rồi', className: 'status warn' });
});
