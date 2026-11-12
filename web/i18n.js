// Wording in the user's language (vi | en): the tables come from the server (GET /api/i18n, files data/i18n/*.json).
// t(key, params) gives the text; a key with no text shows the key itself, so a missing translation is visible, not silent.
// The Vietnamese table is also bundled (i18n-vi.js, generated from data/i18n/vi.json by tests/js/gen-i18n.mjs) so the pure modules
// word themselves with no server (node tests) and before the language is loaded. In a page, this module loads the chosen language
// before any module that imports it runs (top-level await), so labels built when a module loads are already in that language.

import { api } from './api-client.js';
import VI from './i18n-vi.js';

const KEY = 'kitchen.lang';
let table = { ...VI };
let current = 'vi';

export function lang() { return current; }

/** Load the table of `wanted` (default: the language kept in the browser, else vi). */
export async function loadLang(wanted) {
  let pick = wanted;
  if (!pick) { try { pick = localStorage.getItem(KEY) || 'vi'; } catch { pick = 'vi'; } }
  const data = await api('/api/i18n?lang=' + encodeURIComponent(pick));
  table = { ...VI, ...(data.messages || {}) };
  current = data.lang || 'vi';
  try { localStorage.setItem(KEY, current); } catch { /* storage may be unavailable */ }
  document.documentElement.lang = current;
  return current;
}

export function t(key, params = {}) {
  const template = table[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
}

/** The same as `t`, under a name no local variable of the pages uses (they often name a task or a text `t`). */
export const tx = (key, params) => t(key, params);

/** `t(key)`, or `fallback` when the table has no text for the key. */
export function tOr(key, fallback) { return key in table ? t(key) : fallback; }

/** The name of an appliance type (cooktop, sink...) in the current language. */
export const applianceName = (type) => tOr(`appliance.type.${type}`, type || '');

/** The text of a localised value {vi, en} (a plain string is the same in every language). */
export function pick(value) {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return '';
  return value[current] || value.vi || Object.values(value)[0] || '';
}

/** Fill every element carrying data-i18n="key" (its text) and data-i18n-attr="title:key;placeholder:key" (attributes) under `root`. */
export function translate(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-attr]').forEach((el) => {
    for (const pair of el.dataset.i18nAttr.split(';')) { const [attr, key] = pair.split(':'); if (attr && key) el.setAttribute(attr, t(key)); }
  });
}

/** A <select> that switches the language and calls onChange after the new table is loaded. */
export function languagePicker(onChange) {
  const sel = document.createElement('select');
  sel.title = 'Language / Ngôn ngữ';
  for (const [code, name] of [['vi', 'Tiếng Việt'], ['en', 'English']]) sel.add(new Option(name, code, false, code === current));
  sel.addEventListener('change', async () => { await loadLang(sel.value); onChange?.(); });
  return sel;
}

if (typeof document !== 'undefined') {
  try { await loadLang(); } catch { /* no server: the bundled Vietnamese */ }
  if (current !== 'vi') translate();          // the static texts of the page (index.html, render.html are written in Vietnamese)
}
