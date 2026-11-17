import test from 'node:test';
import assert from 'node:assert/strict';
import { opensOrSaves, replacesWithDoor, joinsRuns, styleFromOptions, styleFromValue, interpretBody, describeInterpret, confirmBody, checkUpload, recognizeBody, recognizeJobBody, anchorFor, photoOpeningHeadline, describeRecognition, templateIntent, mentionsReference, recognitionLines, commandPlace, facesForTarget, commandBody, answerCard, replyBody, keepAnswers, inboxNews, describeCommandAnswer } from '../../web/assist-logic.js';

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
  const anchor = anchorFor({ kind: 'structure', id: 'STRUCT-column_a', point: { x: 1200, z: 3400, y: 5 } });
  assert.deepEqual(anchor, { structureId: 'STRUCT-column_a', point: { x: 1200, z: 3400 } });
  for (const t of [null, { kind: 'module', id: 'TD1' }, { kind: 'structure', id: 'STRUCT-a' }, { kind: 'structure', id: 'STRUCT-a', point: { x: 'a', z: 1 } }]) assert.equal(anchorFor(t), null);
  assert.deepEqual(recognizeBody('photo', 'a', 'image/png', 'QQ==', 2, '', anchor).anchor, anchor);
  assert.ok(!('mode' in recognizeBody('photo', 'a', 'image/png', 'QQ==', 2, '', anchor, 'add')), 'add is the default and is not sent');
  assert.equal(recognizeBody('photo', 'a', 'image/png', 'QQ==', 2, '', anchor, 'replace').mode, 'replace');
  assert.deepEqual(recognizeJobBody('20261109-142100', 3, anchor, 'replace'), { job: '20261109-142100', baseRev: 3, anchor, mode: 'replace' });
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
  assert.deepEqual(templateIntent('tạo tủ bếp có tủ lạnh, mặt đá đen, tủ dưới xanh rêu'), { kind: 'run-i', described: true });
  assert.deepEqual(templateIntent('thiết kế tủ lạnh và tủ nóc ở đây'), { kind: 'run-i', described: true });
  assert.equal(templateIntent('cánh kính cho tủ trên'), null);
  assert.equal(templateIntent('thêm tủ trên cho tôi'), null);
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

test('door, window and save sentences go to the server first', () => {
  for (const t of ['tạo cửa đi ở vị trí này', 'thay bằng cửa sổ 1200x1400', 'lưu vào database', 'add a window']) assert.equal(opensOrSaves(t), true, t);
  for (const t of ['thêm tủ dưới', 'sơn trắng']) assert.equal(opensOrSaves(t), false, t);
  assert.equal(replacesWithDoor('thay thế vật đang chọn bằng cửa đi'), true);
  assert.equal(replacesWithDoor('tạo cửa đi ở vị trí này'), false);
});

test('"nối góc" joins two runs', () => {
  for (const t of ['nối góc', 'nối dãy này với dãy kia', 'join the runs']) assert.equal(joinsRuns(t), true, t);
  for (const t of ['nối dài tủ', 'tạo cửa đi']) assert.equal(joinsRuns(t), false, t);
});

test('command inbox: what was clicked, the body sent, the answers shown', () => {
  assert.deepEqual(commandPlace({ kind: 'part', id: 'TD1', part: 'door', point: { x: 1, z: 2 } }, 'Cánh · TD1'),
    { kind: 'part', id: 'TD1', part: 'door', point: { x: 1, z: 2 }, module: 'TD1', title: 'Cánh · TD1' });
  assert.deepEqual(commandPlace({ kind: 'structure', id: 'STRUCT-opening_002', point: { x: 5, z: 6 } }),
    { kind: 'structure', id: 'opening_002', point: { x: 5, z: 6 }, structureId: 'opening_002' });
  assert.deepEqual(commandPlace({ kind: 'group', id: 'G', group: { modules: ['TD1', 'TD2'] } }, '', ['wall_1#inside']),
    { kind: 'group', id: 'G', module: 'TD1', modules: ['TD1', 'TD2'], surfaces: ['wall_1#inside'] });
  assert.deepEqual(commandPlace(null), {});
  assert.deepEqual(commandBody('  xóa TD3 ', 4, { kind: 'module' }, 'vi'), { text: 'xóa TD3', place: { kind: 'module' }, baseRev: 4, lang: 'vi' });
  assert.throws(() => commandBody('  ', 4, {}, 'vi'));
  const list = [{ id: 'a', status: 'pending' }, { id: 'b', status: 'done', text: 'xóa TD3', reply: 'Đã xóa', revision: 5 }, { id: 'c', status: 'failed', text: 'x' }, { id: 'z', status: 'done' }];
  const { waiting, news } = inboxNews(list, ['a', 'b', 'c']);
  assert.deepEqual(waiting.map((c) => c.id), ['a']);
  assert.deepEqual(news.map((c) => c.id), ['b', 'c'], 'only the commands this page sent');
  const done = describeCommandAnswer(list[1], 4);
  assert.equal(done.tone, 'ok'); assert.equal(done.reload, true); assert.match(done.text, /Đã xóa/);
  assert.equal(describeCommandAnswer(list[1], 5).reload, false, 'already on that revision');
  assert.equal(describeCommandAnswer(list[2], 4).tone, 'bad');
  assert.equal(describeCommandAnswer({ id: 'q', status: 'question', text: 'x', reply: 'Tủ nào?' }, 4).tone, 'warn');
});

test('a picture of a door: anchored on a placed opening too, and the preview says which opening it replaces or fills', () => {
  assert.deepEqual(anchorFor({ kind: 'opening', id: 'OP1', point: { x: 0, z: 1962.5 } }), { structureId: 'OP1', point: { x: 0, z: 1962.5 } });
  const replace = photoOpeningHeadline({ mode: 'opening', operation: { op: 'update-opening', id: 'OP1', changes: { width: 3920, height: 2200 } } });
  assert.match(replace, /OP1/); assert.match(replace, /3920/); assert.match(replace, /2200/);
  const hole = photoOpeningHeadline({ mode: 'opening', operation: { op: 'add-opening', opening: { sourceElement: 'opening_004', width: 3920, height: 2200 } } });
  assert.match(hole, /opening_004/);
  assert.notEqual(photoOpeningHeadline({ mode: 'opening', operation: { op: 'add-opening', opening: { width: 900, height: 2200 } } }), hole);
});

test('an unsure door: the answer offers types to pick, and the pick goes back in the request', () => {
  const d = describeRecognition({ status: 'question', choices: [{ openingType: 'door-sliding-4', label: { vi: 'Cửa đi trượt bốn cánh', en: 'Four-panel sliding door' } },
    { openingType: 'x-type' }] }, 'en');
  assert.equal(d.kind, 'choices');
  assert.deepEqual(d.choices, [{ type: 'door-sliding-4', label: 'Four-panel sliding door' }, { type: 'x-type', label: 'x-type' }]);
  assert.equal(recognizeJobBody('20261117-095352', 3, null, 'add', 'door-sliding-4').openingType, 'door-sliding-4');
  assert.equal('openingType' in recognizeJobBody('20261117-095352', 3), false);
  assert.equal(recognizeBody('photo', 'a.png', 'image/png', 'QQ==', 1, '', null, 'add', 'door-swing-2').openingType, 'door-swing-2');
});

// the picked wall faces go with a right-click sentence on them or on their wall, not with one on anything else
{
  const picked = ['wall_006#inside', 'wall_007#inside'];
  assert.deepEqual(facesForTarget({ kind: 'structure', id: 'STRUCT-wall_006', surface: 'wall_006#inside' }, picked), picked);
  assert.deepEqual(facesForTarget({ kind: 'structure', id: 'STRUCT-wall_006' }, picked), picked, 'the wall body, not a face');
  assert.deepEqual(facesForTarget({ kind: 'structure', id: 'wall_007' }, picked), picked);
  assert.deepEqual(facesForTarget({ kind: 'structure', id: 'STRUCT-wall_009' }, picked), [], 'another wall');
  assert.deepEqual(facesForTarget({ kind: 'module', id: 'TD1' }, picked), []);
  assert.deepEqual(facesForTarget({ kind: 'structure', id: 'STRUCT-wall_006' }, []), []);
  assert.deepEqual(facesForTarget(null, picked), []);
  assert.deepEqual(commandPlace({ kind: 'structure', id: 'STRUCT-wall_006', point: { x: 1, z: 2 } }, 'T', facesForTarget({ kind: 'structure', id: 'STRUCT-wall_006' }, picked)).surfaces, picked);
}

// Claude's answer kept in the command box: its reply, its choices and an undo while the design is still at the change
{
  const done = { id: 'c1', designId: 'd', text: 'cửa 4 cánh', status: 'done', reply: 'Đã lắp cửa trượt', revision: 2, fromRev: 1, choices: ['Cửa xếp 4 cánh', '', 3] };
  const card = answerCard(done, 2);
  assert.equal(card.undoTo, 1);
  assert.deepEqual(card.choices, ['Cửa xếp 4 cánh']);
  assert.equal(card.reply, 'Đã lắp cửa trượt');
  assert.equal(card.tone, 'ok');
  assert.equal(answerCard(done, 3).undoTo, null, 'something changed since: no undo');
  assert.equal(answerCard({ ...done, fromRev: undefined }, 2).undoTo, 1, 'the revision before the change');
  const asked = answerCard({ id: 'c2', designId: 'd', text: 'tủ', status: 'question', reply: 'Sâu bao nhiêu?', choices: ['600', '350'] }, 5);
  assert.equal(asked.undoTo, null);
  assert.equal(asked.tone, 'warn');
  assert.deepEqual(replyBody(' 600 ', 5, 'c2', 'vi'), { text: '600', place: {}, baseRev: 5, lang: 'vi', replyTo: 'c2' });
  assert.throws(() => replyBody('  ', 5, 'c2', 'vi'));
  const kept = keepAnswers([{ id: 'a', designId: 'd' }, { id: 'b', designId: 'e' }], [{ id: 'c', designId: 'd' }, { id: 'a', designId: 'd', status: 'done' }], 2);
  assert.deepEqual(kept.map((k) => k.id), ['b', 'c', 'a']);
  assert.equal(kept.find((k) => k.id === 'a').status, 'done', 'the newer record of the same command');
  assert.deepEqual(keepAnswers([], [1, 2, 3].map((i) => ({ id: `x${i}`, designId: 'd' })), 2).map((k) => k.id), ['x2', 'x3']);
}
