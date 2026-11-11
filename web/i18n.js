// Wording in the user's language (vi | en): the tables come from the server (GET /api/i18n, files data/i18n/*.json).
// t(key, params) gives the text; a key with no text shows the key itself, so a missing translation is visible, not silent.

import { api } from './api-client.js';

const KEY = 'kitchen.lang';
let table = {};
let current = 'vi';

export function lang() { return current; }

/** Load the table of `wanted` (default: the language kept in the browser, else vi). */
export async function loadLang(wanted) {
  let pick = wanted;
  if (!pick) { try { pick = localStorage.getItem(KEY) || 'vi'; } catch { pick = 'vi'; } }
  const data = await api('/api/i18n?lang=' + encodeURIComponent(pick));
  table = data.messages || {};
  current = data.lang || 'vi';
  try { localStorage.setItem(KEY, current); } catch { /* storage may be unavailable */ }
  document.documentElement.lang = current;
  return current;
}

export function t(key, params = {}) {
  const template = table[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
}

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

/** Fill every element carrying data-i18n="key" (its text) under `root`. */
export function translate(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
}

/** A <select> that switches the language and calls onChange after the new table is loaded. */
export function languagePicker(onChange) {
  const sel = document.createElement('select');
  sel.title = 'Language / Ngôn ngữ';
  for (const [code, name] of [['vi', 'Tiếng Việt'], ['en', 'English']]) sel.add(new Option(name, code, false, code === current));
  sel.addEventListener('change', async () => { await loadLang(sel.value); onChange?.(); });
  return sel;
}
