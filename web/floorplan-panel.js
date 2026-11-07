// Floor-plan panel: import a plan (choosing a room when there are several) and bind the kitchen to a wall.
import { $, el } from './dom.js';

export function createFloorplanPanel({ state, api, run, setStatus, loadDesigns, openDesign }) {
  let pendingFloorplan = null;
  function showFloorplanInfo(r) {
    const ul = $('fpInfo'); ul.replaceChildren();
    const add = (t) => ul.appendChild(el('li', {}, t));
    if (r.floorplan) {
      const f = r.floorplan;
      add(`${f.roomLabel || f.roomId}: ${f.width} x ${f.depth} mm, ${f.areaM2} m2, ${f.wallCount} walls`);
      if (f.outsideElements?.length) add(`Outside the room (ignored): ${f.outsideElements.join(', ')}`);
      if (f.unattachedOpenings?.length) add(`Doors/windows not attached to a wall: ${f.unattachedOpenings.join(', ')}`);
      for (const w of f.warnings || []) add(typeof w === 'string' ? w : `${w.code}: ${w.message}`);
    }
    if (r.binding) {
      add(`Kitchen back wall = room edge ${r.binding.back} (${r.binding.source}, score ${r.binding.score})`);
      for (const w of r.binding.warnings || []) add(w);
    }
  }
  async function importFloorplan(roomId) {
    const result = await api('/api/floorplans/import', 'POST', { floorplan: pendingFloorplan, roomId: roomId || undefined });
    showFloorplanInfo(result);
    await loadDesigns(result.id);
  }
  $('floorplanFile').addEventListener('change', (e) => {
    const file = e.target.files[0]; if (!file) return;
    run('import floorplan', async () => {
      pendingFloorplan = JSON.parse(await file.text());
      const { rooms } = await api('/api/floorplans/rooms', 'POST', { floorplan: pendingFloorplan });
      if (rooms.length > 1 || rooms.some((r) => r.kind === 'region')) {
        const sel = $('fpRoom'); sel.replaceChildren(...rooms.map((r) => el('option', { value: r.id }, `${r.kind === 'region' ? '[area] ' : ''}${r.label || r.id} (${r.id})`)));
        $('fpRoomRow').hidden = false; $('fpImport').hidden = false;
        setStatus(`The plan offers ${rooms.length} places to import (rooms and wall-bounded areas): choose one and import`);
        return;
      }
      $('fpRoomRow').hidden = true; $('fpImport').hidden = true;
      await importFloorplan(rooms[0]?.id);
    });
  });
  $('fpImport').addEventListener('click', () => run('import floorplan', () => importFloorplan($('fpRoom').value)));
  $('fpBind').addEventListener('click', () => {
    if (!state.id) return;
    run('place kitchen', async () => { const r = await api(`/api/designs/${state.id}/floorplan-bind`, 'POST', { rev: state.rev }); showFloorplanInfo(r); await openDesign(state.id, true); });
  });
}
