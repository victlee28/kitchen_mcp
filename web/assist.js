// Free-command box and photo/drawing recognition: both end in a PREVIEW; nothing is saved until the user presses Áp dụng.
import { $, el } from './dom.js';
import { request } from './api-client.js';
import { interpretBody, describeInterpret, confirmBody, checkUpload, recognizeBody, describeRecognition } from './assist-logic.js';

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = () => reject(new Error('Không đọc được tệp'));
    r.readAsDataURL(file);
  });
}

export function createAssist(ctx) {
  const out = $('assistResult');
  let busy = false;
  const clear = () => out.replaceChildren();
  const post = (path, body) => request(`/api/designs/${ctx.getState().id}/${path}`, 'POST', body);
  const guard = async (label, fn) => {
    if (busy) return; busy = true; ctx.setStatus(label + '…');
    try { await fn(); } catch (e) { ctx.setStatus(e.message, 'warn'); } finally { busy = false; }
  };
  const showLines = (lines) => el('ul', { class: 'ctx-preview' }, ...lines.map((l) => el('li', { class: l.kind }, l.text)));

  function showPreview(d) {
    const apply = el('button', { type: 'button', class: d.introducesErrors ? 'danger' : 'primary', onclick: () => confirm(d) }, d.introducesErrors ? 'Vẫn áp dụng' : 'Áp dụng');
    if (!d.canApply) apply.disabled = true;
    out.replaceChildren(...d.summary.map((s) => el('p', { class: 'muted small' }, s)), showLines(d.lines),
      el('div', { class: 'row' }, apply, el('button', { type: 'button', class: 'ghost', onclick: clear }, 'Hủy')));
  }
  function showMessage(text, tone, lines = []) {
    out.replaceChildren(el('p', { class: `ctx-msg ${tone || ''}` }, text), showLines(lines));
  }
  async function confirm(d) {
    await guard('Áp dụng', async () => {
      const { id } = ctx.getState();
      const { status, data } = await post('ops', confirmBody(d.proposal));
      if (status === 409) return showMessage('Thiết kế đã thay đổi từ lúc xem trước. Hãy chạy lại lệnh.', 'warn');
      if (!data || data.error) return showMessage(data?.error || `Lỗi ${status}`, 'bad');
      clear(); await ctx.afterChange(data); ctx.setStatus(`Đã áp dụng: rev ${data.rev}`, 'ok'); void id;
    });
  }

  function showResult(d) {
    if (d.kind === 'preview') return showPreview(d);
    if (d.kind === 'clarify') {
      return out.replaceChildren(el('p', { class: 'ctx-msg warn' }, d.question),
        el('div', { class: 'chips' }, ...d.choices.map((c) => el('button', { type: 'button', class: 'ghost small', onclick: () => { $('cmdText').value = `${$('cmdText').value.trim()} ${c}`; $('cmdText').focus(); } }, c))));
    }
    showMessage(d.message + (d.llm ? ` (LLM: ${d.llm})` : ''), 'warn');
  }

  async function interpret() {
    const { rev, selected } = ctx.getState();
    let body;
    try { body = interpretBody($('cmdText').value, rev, { scope: selected ? [selected] : undefined, useLlm: $('cmdLlm').checked }); } catch (e) { return ctx.setStatus(e.message, 'warn'); }
    await guard('Đọc câu lệnh', async () => {
      const { status, data } = await post('interpret', body);
      if (status === 409) return showMessage('Thiết kế đã thay đổi. Tải lại rồi chạy lại.', 'warn');
      if (!data || data.error) return showMessage(data?.error || `Lỗi ${status}`, 'bad');
      showResult(describeInterpret(data)); ctx.setStatus('Xem trước câu lệnh (chưa lưu)', 'ok');
    });
  }

  async function recognize() {
    const file = $('recFile').files[0]; const bad = checkUpload(file);
    if (bad) return ctx.setStatus(bad, 'warn');
    await guard('Nhận diện ảnh', async () => {
      const body = recognizeBody($('recKind').value, file.name, file.type, await toBase64(file), ctx.getState().rev);
      const { status, data } = await post('recognize', body);
      if (status === 409) return showMessage('Thiết kế đã thay đổi. Tải lại rồi nhận diện lại.', 'warn');
      if (!data || data.error) return showMessage(data?.error || `Lỗi ${status}`, 'bad');
      const d = describeRecognition(data);
      if (d.kind === 'preview') showPreview(d); else showMessage(d.text, d.tone, d.lines);
      ctx.setStatus('Đã nhận diện (bản xem trước, chưa lưu)', d.kind === 'preview' ? 'ok' : 'warn');
    });
  }

  $('cmdGo').addEventListener('click', interpret);
  $('cmdText').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); interpret(); } });
  $('recGo').addEventListener('click', recognize);
  window.addEventListener('design-opened', clear);
  return { clear };
}
