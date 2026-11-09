import test from 'node:test';
import assert from 'node:assert/strict';
import { styleFromOptions, styleFromValue, interpretBody, describeInterpret, confirmBody, checkUpload, recognizeBody, recognizeJobBody, describeRecognition, templateIntent, mentionsReference, recognitionLines } from '../../web/assist-logic.js';

const prop = (over = {}) => ({ id: 'd1', baseRev: 4, opHash: 'h', operation: { op: 'remove', id: 'TD1' }, applicable: true, unchanged: false,
  diff: { modules: { added: [], removed: ['TD1'], changed: {} }, other: [] }, validation: { introduced: [], resolved: [] }, ...over });

test('styleFrom: options never offer the current view; values fall back to the default', () => {
  const o = styleFromOptions(['front', 'left', 'right'], 'left');
  assert.deepEqual(o.map((x) => x.value), ['', 'auto', 'none', 'front', 'right']);
  assert.equal(styleFromValue('', ['front'], 'left'), undefined);
  assert.equal(styleFromValue('auto', ['front'], 'left'), 'auto');
  assert.equal(styleFromValue('none', ['front'], 'left'), 'none');
  assert.equal(styleFromValue('front', ['front', 'left'], 'left'), 'front');
  assert.equal(styleFromValue('left', ['front', 'left'], 'left'), undefined);
  assert.equal(styleFromValue('gone', ['front'], 'left'), undefined);
});

test('interpret body trims, refuses empty text, and only sends options that are set', () => {
  assert.deepEqual(interpretBody('  xóa TD1 ', 3), { text: 'xóa TD1', baseRev: 3 });
  assert.deepEqual(interpretBody('x', 3, { scope: ['TD1'], useLlm: true }), { text: 'x', baseRev: 3, scope: ['TD1'], useLlm: true });
  assert.throws(() => interpretBody('   ', 1));
});

test('interpret answers: preview, clarify, unsupported', () => {
  const ok = describeInterpret({ status: 'ok', summary: ['Xóa TD1'], proposal: prop() });
  assert.equal(ok.kind, 'preview'); assert.equal(ok.canApply, true); assert.deepEqual(ok.lines[0], { kind: 'info', text: 'Xóa TD1' });
  assert.equal(describeInterpret({ status: 'ok', proposal: prop({ unchanged: true }) }).canApply, false);
  assert.equal(describeInterpret({ status: 'ok', proposal: prop({ applicable: false, error: { message: 'x' } }) }).canApply, false);
  assert.deepEqual(describeInterpret({ status: 'clarify', question: 'Tủ nào?', choices: ['TD1'] }), { kind: 'clarify', question: 'Tủ nào?', choices: ['TD1'] });
  assert.equal(describeInterpret({ status: 'unsupported', message: 'm', llm: 'no-key' }).llm, 'no-key');
});

test('confirm sends exactly the previewed operation with its hash', () => {
  assert.deepEqual(confirmBody(prop()), { op: { op: 'remove', id: 'TD1' }, baseRev: 4, expect: 'h' });
});

test('upload check: type and size', () => {
  assert.equal(checkUpload(null) !== null, true);
  assert.equal(checkUpload({ type: 'image/gif', size: 5 }) !== null, true);
  assert.equal(checkUpload({ type: 'image/png', size: 13 * 1048576 }) !== null, true);
  assert.equal(checkUpload({ type: 'image/jpeg', size: 1000 }), null);
  assert.deepEqual(recognizeBody('photo', 'a.jpg', 'image/jpeg', 'QQ==', 2), { source: { kind: 'photo', name: 'a.jpg', mediaType: 'image/jpeg', imageBase64: 'QQ==' }, baseRev: 2 });
  assert.throws(() => recognizeBody('video', 'a', 'b', 'c', 1));
  // the hint typed in the menu box travels with the picture (trimmed, at most 500 characters, left out when blank)
  assert.equal(recognizeBody('photo', 'a.jpg', 'image/jpeg', 'QQ==', 2, '  white   doors \n').source.note, 'white doors');
  assert.equal(recognizeBody('photo', 'a.jpg', 'image/jpeg', 'QQ==', 2, 'x'.repeat(900)).source.note.length, 500);
  for (const blank of ['', '   ', undefined, null]) assert.ok(!('note' in recognizeBody('photo', 'a.jpg', 'image/jpeg', 'QQ==', 2, blank).source));
});

test('recognition answers cover every status and flag low-confidence modules', () => {
  const draft = { modules: [{ type: 'base', wall: 'back', width: 600, confidence: 0.4, needsReview: true, label: 'x' }], rejected: [{ index: 1, reason: 'bad' }], notes: ['n'] };
  const ok = describeRecognition({ status: 'ok', draft, proposal: prop() });
  assert.equal(ok.kind, 'preview'); assert.equal(ok.lines[0].kind, 'warn'); assert.match(ok.lines[0].text, /cần kiểm tra/);
  assert.equal(ok.lines.some((l) => l.kind === 'bad' && /mục 2/.test(l.text)), true);
  assert.equal(describeRecognition({ status: 'empty', draft }).kind, 'message');
  assert.match(describeRecognition({ status: 'unavailable' }).text, /GEMINI_API_KEY/);
  const waiting = describeRecognition({ status: 'pending', job: '20261109-142100', step: 'scene' });
  assert.deepEqual([waiting.kind, waiting.job], ['pending', '20261109-142100']);
  assert.match(waiting.text, /trả lời hộp thư job 20261109-142100/);
  assert.deepEqual(recognizeJobBody(' 20261109-142100-2 ', 3), { job: '20261109-142100-2', baseRev: 3 });
  for (const bad of ['', '../x', '20261109-1', null]) assert.throws(() => recognizeJobBody(bad, 1));
  assert.equal(describeRecognition({ status: 'failed', message: 'boom' }).tone, 'bad');
});

test('template intent: a request for a run-I cabinet, with or without accents; other shapes are named; edits are not templates', () => {
  assert.deepEqual(templateIntent('tạo cho tôi tủ chữ I ở đây'), { kind: 'run-i' });
  assert.deepEqual(templateIntent('lam day tu doc canh nay'), { kind: 'run-i' });
  assert.deepEqual(templateIntent('tao tu bep chu i giong voi hinh anh tham chieu cho vi tri nay'), { kind: 'run-i' });
  assert.deepEqual(templateIntent('Tạo bếp chữ L'), { kind: 'shape', shape: 'L' });
  assert.equal(templateIntent('xoá tủ bếp chữ I'), null);
  assert.ok(mentionsReference('tao tu bep chu i giong voi hinh anh tham chieu'));
  assert.ok(mentionsReference('làm theo ảnh'));
  assert.ok(!mentionsReference('tạo tủ chữ I ở đây'));
  assert.deepEqual(templateIntent('Dựng TỦ CHỮ L quanh cột'), { kind: 'shape', shape: 'L' });
  assert.deepEqual(templateIntent('tạo tủ chữ U'), { kind: 'shape', shape: 'U' });
  assert.equal(templateIntent('xóa TD3'), null);
  assert.equal(templateIntent('TD2 rộng 800'), null);
  assert.equal(templateIntent('tủ chữ I'), null);   // no verb: not a request
});

test('recognition lines are the draft part only', () => {
  const draft = { modules: [{ type: 'base', wall: 'back', width: 600, confidence: 1, needsReview: false, label: '' }], rejected: [], notes: [] };
  const lines = recognitionLines({ status: 'ok', draft, proposal: prop() });
  assert.equal(lines.length, 1); assert.match(lines[0].text, /base/);
  assert.equal(recognitionLines({ status: 'empty', draft: { modules: [], rejected: [], notes: ['n'] } }).length, 1);
});
