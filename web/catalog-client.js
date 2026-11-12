// The catalog (kinds of business data: appliances, materials, styles...) over HTTP. The role is sent as X-Role (workshop | user): it is
// not authentication, accounts do not exist yet. Lists are cached per kind and language until a write.
import { api } from './api-client.js';

const ROLE_KEY = 'kitchen.role';
const cache = new Map();

export function role() { try { return localStorage.getItem(ROLE_KEY) || 'user'; } catch { return 'user'; } }
export function setRole(r) { try { localStorage.setItem(ROLE_KEY, r); } catch { /* ignore */ } cache.clear(); }

const call = (path, method = 'GET', body) => api(path, method, body, { 'X-Role': role() });     // ApiError carries .status and .data.code

export const kinds = (lang) => call('/api/catalog?lang=' + lang).then((d) => d.kinds);

export async function list(kind, lang) {
  const key = kind + '|' + lang + '|' + role();
  if (!cache.has(key)) cache.set(key, call(`/api/catalog/${kind}?lang=${lang}`));
  return cache.get(key);
}

const item = (kind, id) => `/api/catalog/${kind}/${encodeURIComponent(id)}`;
export async function put(kind, id, data, disabled = false) { cache.clear(); return call(item(kind, id), 'PUT', { data, disabled }); }
export async function remove(kind, id) { cache.clear(); return call(item(kind, id), 'DELETE'); }
export async function undo(kind, id) { cache.clear(); return call(item(kind, id) + '/undo', 'POST'); }
export const history = (kind, id) => call(item(kind, id) + '/history').then((d) => d.history);
export const exportLayer = () => call('/api/catalog-export');
export async function importLayer(payload) { cache.clear(); return call('/api/catalog-import', 'POST', payload); }
export const csvOf = (kind) => call(`/api/catalog-csv/${kind}`).then((d) => d.csv);
export async function importCsv(kind, csv) { cache.clear(); return call(`/api/catalog-csv/${kind}`, 'POST', { csv }); }
export const materialPreview = (text) => call('/api/material-preview?text=' + encodeURIComponent(text));
export const typePreview = (id, data) => call('/api/cabinet-type-preview', 'POST', { id, data });
export const layoutPreview = (id, data, options) => call('/api/layout-template-preview', 'POST', { id, data, options });
