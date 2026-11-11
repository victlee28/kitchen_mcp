// HTTP to the server, the status line and the "run an action" wrapper. No DOM lookups here: the status element is passed in.

export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.name = 'ApiError'; this.status = status; this.data = data; }
}

/** Never throws on HTTP errors: {status, ok, data} (data is {} when the body is not JSON). Use for flows that branch on the status (409 = stale). */
export async function request(path, method = 'GET', body, headers = {}) {
  const opt = { method, headers: { ...headers } };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  return { status: r.status, ok: r.ok, data };
}

/** The message of a failed response: the server's `error`, plus the offending parts when it lists them. */
export function errorMessage(status, data) {
  const detail = data?.part ? ' — ' + data.part.map((x) => `${x.position}: ${x.errors}`).join('; ') : '';
  return (data?.error || `HTTP ${status}`) + detail;
}

/** The data of a successful response; throws ApiError (with .status and .data) otherwise. */
export async function api(path, method = 'GET', body, headers = {}) {
  const { status, ok, data } = await request(path, method, body, headers);
  if (!ok) throw new ApiError(errorMessage(status, data), status, data);
  return data;
}

/** setStatus(msg, kind) writes into `statusEl`; run(label, fn) shows "label…", then "Xong: label" or the error. */
export function createStatus(statusEl) {
  const setStatus = (msg, kind = '') => { statusEl.textContent = msg; statusEl.className = 'status ' + kind; };
  const run = async (label, fn) => {
    setStatus(label + '…');
    try { await fn(); setStatus('Xong: ' + label, 'ok'); } catch (e) { console.error(e); setStatus(e.message, 'warn'); }
  };
  return { setStatus, run };
}
