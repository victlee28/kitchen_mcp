// The question panel: when Claude (or the background model) stops on a command and asks the user how to go on, the question comes up on
// its own, with numbered choices to click (or keys 1-9), a line for another answer, and "Later" (it stays in the right-click menu).
// One question at a time, oldest first. The page decides what an answer does (onAnswer posts it as a reply to the command).
import { el } from './dom.js';
import { tx } from './i18n.js';
import { pickByKey } from './assist-logic.js';

/** onAnswer(card, text) -> Promise<string|null> (an error to show, or null when sent). */
export function createAskPanel({ host = document.body, onAnswer }) {
  const node = el('div', { class: 'ask-panel', role: 'dialog', 'aria-live': 'polite' }); node.hidden = true; node.tabIndex = -1; host.append(node);
  let queue = []; let busy = false; let note = '';

  async function answer(text) {
    const card = queue[0]; if (!card || busy) return;
    if (!String(text || '').trim()) { note = tx('ui.ask.empty'); return render(); }
    busy = true; note = ''; render();
    let error = null;
    try { error = await onAnswer(card, String(text).trim()); } catch (e) { error = e.message; }
    busy = false;
    if (error) { note = error; return render(); }
    queue = queue.slice(1); render();
  }
  function later() { queue = queue.slice(1); note = ''; render(); }

  let shown = null;            // the question on screen: a new one coming in behind it keeps what is typed and where the focus is
  function render() {
    const card = queue[0];
    const same = card && card.id === shown; const typed = same ? node.querySelector('.ask-other')?.value || '' : '';
    const wasIn = node.contains(document.activeElement); const focusIn = same && wasIn && document.activeElement.className === 'ask-other';
    shown = card?.id ?? null;
    node.hidden = !card; node.replaceChildren(); if (!card) return;
    const other = el('input', { type: 'text', class: 'ask-other', placeholder: tx('ui.ask.other'), disabled: busy, value: typed,
      onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); answer(other.value); } } });
    node.append(
      el('div', { class: 'ask-head' }, el('b', {}, tx('ui.ask.title')), queue.length > 1 ? el('span', { class: 'ask-count' }, tx('ui.ask.count', { 0: 1, 1: queue.length })) : '',
        el('button', { type: 'button', class: 'ctx-x', title: tx('ui.ask.later-title'), onclick: later }, '×')),
      el('p', { class: 'ask-about' }, tx('ui.ask.about', { 0: card.text })),
      el('p', { class: 'ask-question' }, card.reply),
      el('div', { class: 'ask-options' }, ...card.choices.map((c, i) => el('button', { type: 'button', class: 'ask-option', disabled: busy, onclick: () => answer(c) },
        el('span', { class: 'ask-key' }, String(i + 1)), el('span', {}, c)))),
      el('div', { class: 'ask-row' }, other, el('button', { type: 'button', class: 'primary small', disabled: busy, onclick: () => answer(other.value) }, tx('ui.ask.send'))),
      ...(note ? [el('p', { class: 'ctx-msg bad', role: 'alert' }, note)] : busy ? [el('p', { class: 'ctx-msg' }, tx('ui.ask.sending'))] : []),
      el('div', { class: 'ask-foot' }, el('button', { type: 'button', class: 'ghost small', disabled: busy, onclick: later }, tx('ui.ask.later'))));
    if (focusIn) other.focus(); else if (!same || wasIn) (card.choices.length ? node.querySelector('.ask-option:not([disabled])') || node : other)?.focus();
  }

  node.addEventListener('keydown', (e) => {
    if (e.target instanceof HTMLInputElement) return;
    if (e.key === 'Escape') { e.stopPropagation(); return later(); }
    const c = pickByKey(e.key, queue[0]?.choices || []);
    if (c) { e.preventDefault(); answer(c); }
  });

  return {
    /** Questions to put to the user (answer cards with status "question"); ones already queued are not asked twice. */
    ask(cards) {
      const fresh = cards.filter((c) => c.status === 'question' && !queue.some((q) => q.id === c.id));
      if (!fresh.length) return;
      queue = [...queue, ...fresh]; render();
    },
    /** A question answered or dropped elsewhere (the right-click menu): taken off the panel. */
    forget(id) { const was = queue[0]?.id; queue = queue.filter((q) => q.id !== id); if (was === id) note = ''; render(); },
    /** Another design opened: only its questions stay (an answer goes to the design on screen). */
    only(designId) { queue = queue.filter((q) => q.designId === designId); render(); },
    get open() { return !node.hidden; },
  };
}
