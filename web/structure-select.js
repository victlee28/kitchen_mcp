// Select, inspect, hide and isolate the elements that an imported floorplan adds to the scene (room.structures).
// The viewer owns the camera and the click; this module owns what is selected and shown.
import { tOr, tx } from './i18n.js';
const kindLabel = (k) => tOr(`ui.structure.kind.${k}`, k);   // data/i18n; a kind with no wording shows its id
const EMPTY = { entries: new Map() };

export function createStructureSelector({ THREE, els, onSelect, onChange }) {
  let entries = EMPTY.entries; let pickables = [];
  let selected = null; let tint = true; const hiddenKinds = new Set(); const hiddenIds = new Set();
  const selMats = new WeakMap();

  const meshOf = (m) => m.userData?.structureId;
  const bbox = (rec) => {
    const xs = rec.outline.map((p) => p.x), zs = rec.outline.map((p) => p.z);
    return { w: Math.max(...xs) - Math.min(...xs), d: Math.max(...zs) - Math.min(...zs) };
  };
  const isShown = (id) => { const e = entries.get(id); return !!e && !hiddenIds.has(id) && !hiddenKinds.has(e.record.kind); };

  function paint() {
    for (const [id, e] of entries) {
      const shown = isShown(id);
      for (const o of e.parts) o.visible = shown;
      for (const m of e.meshes) {
        const lit = id === selected && tint;
        if (m.userData.surfaceId) {            // a wall face: lit with its wall only when the wall itself was chosen; otherwise its own light stays
          if (lit && !m.userData.structLit) { m.userData.structBase = m.material; m.material = tinted(m.material); m.userData.structLit = true; }
          else if (!lit && m.userData.structLit) { m.material = m.userData.structBase; m.userData.structLit = false; }
          continue;
        }
        if (!m.userData.baseMat) m.userData.baseMat = m.material;
        m.material = lit ? tinted(m.userData.baseMat) : m.userData.baseMat;
      }
    }
  }

  function tinted(base) {
    if (!selMats.has(base)) {
      const c = base.clone(); c.emissive = new THREE.Color(0xff8a1f); c.emissiveIntensity = 0.55; c.transparent = false; c.opacity = 1; selMats.set(base, c);
    }
    return selMats.get(base);
  }

  function describe(rec) {
    const { w, d } = bbox(rec);
    const rows = [['Element', rec.label || rec.sourceElement], ['Kind', rec.kind + (rec.tag && rec.tag !== rec.kind ? ` (${rec.tag})` : '')], ['Source id', rec.sourceElement],
      ['Footprint', `${Math.round(w)} x ${Math.round(d)} mm`], ['Base / height', `${Math.round(rec.base || 0)} / ${Math.round(rec.height)} mm (${rec.heightSource})`],
      ['Relation to room', rec.membership]];
    if (rec.steps) rows.push(['Steps', String(rec.steps)]);
    return rows;
  }

  function render() {
    const has = entries.size > 0;
    els.section.hidden = !has;
    if (!has) return;
    const kinds = [...new Set([...entries.values()].map((e) => e.record.kind))];
    els.kinds.replaceChildren(...kinds.map((k) => {
      const n = [...entries.values()].filter((e) => e.record.kind === k).length;
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = !hiddenKinds.has(k);
      cb.addEventListener('change', () => { cb.checked ? hiddenKinds.delete(k) : hiddenKinds.add(k); if (selected && !isShown(selected)) selected = null; refresh(); });
      const lab = document.createElement('label'); lab.className = 'kind'; lab.append(cb, ` ${kindLabel(k)} (${n})`);
      return lab;
    }));
    const items = [...entries.values()].map((e) => e.record).sort((a, b) => a.kind.localeCompare(b.kind) || String(a.label || a.sourceElement).localeCompare(String(b.label || b.sourceElement)));
    els.list.replaceChildren(...items.map((r) => {
      const li = document.createElement('li'); li.dataset.id = r.id;
      li.className = (r.id === selected ? 'sel ' : '') + (isShown(r.id) ? '' : 'off');
      li.textContent = `${r.label || r.sourceElement} · ${r.kind}`;
      li.addEventListener('click', () => select(r.id));
      return li;
    }));
    const rec = selected && entries.get(selected)?.record;
    els.detail.hidden = !rec;
    if (rec) {
      els.detail.replaceChildren(...describe(rec).map(([k, v]) => { const li = document.createElement('li'); li.textContent = `${k}: ${v}`; return li; }));
    }
    els.actions.hidden = !rec;
    els.hide.textContent = rec && hiddenIds.has(rec.id) ? tx('ui.structure.show') : tx('ui.structure.hide');
    els.showAll.hidden = !(hiddenIds.size || hiddenKinds.size);
  }

  function refresh() { paint(); render(); onChange?.(); }
  /** `quiet`: the wall was reached through one of its faces, so the face is lit, not the whole wall. */
  function select(id, { quiet = false } = {}) {
    selected = id && isShown(id) ? id : null; tint = !quiet;
    refresh();
    if (selected) onSelect?.(selected);
  }

  const hideSelected = () => { if (!selected) return; hiddenIds.has(selected) ? hiddenIds.delete(selected) : hiddenIds.add(selected); if (!isShown(selected)) selected = null; refresh(); };
  const isolateSelected = () => {
    if (!selected) return;
    hiddenIds.clear(); hiddenKinds.clear();
    for (const id of entries.keys()) if (id !== selected) hiddenIds.add(id);
    refresh();
  };
  const showAll = () => { hiddenIds.clear(); hiddenKinds.clear(); refresh(); };
  els.hide.addEventListener('click', hideSelected);
  els.isolate.addEventListener('click', isolateSelected);
  els.showAll.addEventListener('click', showAll);

  return {
    /** New scene: keep the selection and hidden items that still exist. */
    setScene(structures, picks) {
      entries = structures || EMPTY.entries; pickables = picks || [];
      for (const id of [...hiddenIds]) if (!entries.has(id)) hiddenIds.delete(id);
      if (selected && !entries.has(selected)) selected = null;
      refresh();
    },
    /** Visible structure meshes the pointer can hit. */
    pickables: () => pickables.filter((m) => m.visible),
    idOf: meshOf,
    hideSelected, isolateSelected, showAll,
    select, clear() { if (selected) { selected = null; refresh(); } },
    get selected() { return selected; },
  };
}
