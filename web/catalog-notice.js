// "The catalog has newer items" on an open design: after a design opens, ask the server what changed in the catalog since its revision was
// saved; if anything did, a line under the header says so, and "Update" previews the change and saves it as a new revision (the design
// itself does not change; its cabinets are then built with the catalog as it is now). Talks to the page only through window events.
import { api } from './api-client.js';
import { $, el } from './dom.js';
import { tx } from './i18n.js';

async function check(id, rev) {
  const box = $('catalogNotice');
  if (!box) return;
  box.replaceChildren();
  let u;
  try { u = await api(`/api/designs/${encodeURIComponent(id)}/catalog-updates?rev=${rev}`); } catch { return; }
  if (!u.updates.length) return;
  const names = u.updates.slice(0, 6).map((x) => `${x.kind} ${x.id}`).join(', ') + (u.updates.length > 6 ? ' …' : '');
  const update = el('button', { type: 'button', className: 'small', textContent: tx('ui.catalog-update'), onclick: async () => {
    update.disabled = true;
    try {
      const p = await api(`/api/designs/${encodeURIComponent(id)}/propose`, 'POST', { baseRev: rev, op: u.operation });
      await api(`/api/designs/${encodeURIComponent(id)}/ops`, 'POST', { baseRev: p.baseRev, op: u.operation, expect: p.opHash });
      box.replaceChildren();
      window.dispatchEvent(new CustomEvent('design-reload-request', { detail: { id } }));
    } catch (e) { update.disabled = false; box.append(el('span', { className: 'warn', textContent: ' ' + e.message })); }
  } });
  box.append(el('span', { textContent: tx(u.geometryChanges ? 'ui.catalog-newer-shape' : 'ui.catalog-newer', { 0: u.updates.length, 1: names }) + ' ' }), update);
}

window.addEventListener('design-opened', (ev) => { check(ev.detail.id, ev.detail.rev); });
