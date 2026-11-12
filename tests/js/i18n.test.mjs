// The web's wording (stage 3.5): every Vietnamese text of the scripts lives in data/i18n; the bundled table matches the data.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { bundle } from './gen-i18n.mjs';
import { t } from '../../web/i18n.js';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const VI = /[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]/i;

test('web/i18n-vi.js is the bundle of data/i18n/vi.json (run node tests/js/gen-i18n.mjs)', () => {
  assert.equal(readFileSync(path.join(ROOT, 'web', 'i18n-vi.js'), 'utf8'), bundle());
});

test('every ui.* key has English words', () => {
  const vi = JSON.parse(readFileSync(path.join(ROOT, 'data', 'i18n', 'vi.json'), 'utf8'));
  const en = JSON.parse(readFileSync(path.join(ROOT, 'data', 'i18n', 'en.json'), 'utf8'));
  assert.deepEqual(Object.keys(vi).filter((k) => !(k in en)), []);
});

test('t words a key with its values; the bundled Vietnamese is used with no server', () => {
  assert.equal(t('ui.loi'), 'Lỗi {0}');
  assert.equal(t('ui.loi', { 0: 409 }), 'Lỗi 409');
});

test('no Vietnamese string left in the scripts (comments aside)', () => {
  const allowed = new Set(['i18n.js', 'i18n-vi.js', 'scene-loader.js']);
  for (const f of readdirSync(path.join(ROOT, 'web')).filter((x) => x.endsWith('.js') && !allowed.has(x))) {
    const code = readFileSync(path.join(ROOT, 'web', f), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
    const strings = code.match(/'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g) || [];
    assert.deepEqual(strings.filter((s) => VI.test(s)), [], f);
  }
});
