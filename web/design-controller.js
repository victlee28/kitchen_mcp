// Owns the design loading flow and the shared design state. No DOM here: the page shows what the controller loads through two callbacks.
//   renderList(list, selectedId)  fill the design select
//   onOpened({id, rev, spec, scene, validation, doc, keepView})  show a freshly loaded design (state is already updated)
// A load that is overtaken by a newer one (the user switched design quickly) is dropped before it touches the state or the page.

export function createDesignController({ api, renderList, onOpened }) {
  const state = { id: null, rev: null, spec: null, scene: null, doc: null, selected: null, views: {}, qg: '' };
  let openSeq = 0;

  const countryQuery = () => (state.qg ? `?country=${state.qg}` : '');

  /** Load one design and show it. Resolves true when it was shown, false when a newer load replaced it. */
  async function open(id, { keepView = false } = {}) {
    const seq = ++openSeq;
    const [d, scene, validation, doc] = await Promise.all([api(`/api/designs/${id}`), api(`/api/designs/${id}/scene`),
      api(`/api/designs/${id}/validate${countryQuery()}`), api(`/api/designs/${id}/threejs${countryQuery()}`)]);
    if (seq !== openSeq) return false;
    Object.assign(state, { id, rev: d.rev, spec: d.spec, scene, doc, views: scene.views });
    await onOpened({ id, rev: d.rev, spec: d.spec, scene, validation, doc, keepView });
    return true;
  }

  /** Reload the design list and show it with `selectId` selected (no design is opened). */
  async function refreshList(selectId = state.id) {
    const list = await api('/api/designs');
    renderList(list, selectId);
    return list;
  }

  /** The list, then the chosen design (default: the first one). */
  async function loadDesigns(selectId) {
    const list = await api('/api/designs');
    const id = selectId || (list[0] && list[0].id);
    renderList(list, id);
    if (id) await open(id);
  }

  /** After a saved change (res.id): refresh the list and the design. */
  async function afterChange(res) {
    await loadDesigns(res.id);
    await open(res.id, { keepView: true });
  }

  return { state, open, refreshList, loadDesigns, afterChange };
}
