// Style & moulding panel: profile pickers, profile preview canvas and the apply button.
import { $, el } from './dom.js';
import { moldingsOp, styleHasMoldings } from './design-logic.js';

export function createMoldingPanel({ state, api, run, afterChange }) {
  // ---------------- phong cách & phào
  let profiles = {};
  async function loadProfiles() {
    profiles = await api('/api/molding-profiles');
    for (const [sel, variant] of [['pCrownProf', 'crown'], ['pBaseProf', 'base']]) {
      $(sel).replaceChildren(...Object.values(profiles).filter((p) => p.variant === variant).map((p) => el('option', { value: p.id, textContent: `${p.name} (${p.height}×${p.overhang})` })));
    }
    $('pCrownProf').value = 'classic-crown-layered'; $('pBaseProf').value = 'classic-base';
    $('pCrownProf').addEventListener('change', drawProfile); drawProfile();
  }
  function drawProfile() {
    const p = profiles[$('pCrownProf').value]; const cv = $('pPreview'); const g = cv.getContext('2d');
    g.clearRect(0, 0, cv.width, cv.height); if (!p) return;
    const us = p.points.map((q) => q[0]), vs = p.points.map((q) => q[1]);
    const k = Math.min((cv.width - 10) / (Math.max(...us) - Math.min(...us)), (cv.height - 10) / (Math.max(...vs) - Math.min(...vs)));
    g.beginPath();
    p.points.forEach(([u, v], i) => { const x = 5 + (u - Math.min(...us)) * k, y = cv.height - 5 - (v - Math.min(...vs)) * k; i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.closePath(); g.fillStyle = '#c8a273'; g.fill(); g.strokeStyle = '#3a3630'; g.stroke();
  }
  function syncMoldingPanel() {
    const ms = state.spec.moldings || [];
    const crown = ms.find((m) => m.variant === 'crown'), base = ms.find((m) => m.variant === 'base');
    $('pStyle').value = state.spec.style || 'Modern';
    $('pCrown').checked = !!crown?.enabled; $('pBase').checked = !!base?.enabled;
    if (crown) $('pCrownProf').value = crown.profile; if (base) $('pBaseProf').value = base.profile;
    if (crown || base) $('pEnd').value = (crown || base).openEnd; drawProfile();
  }
  $('pStyle').addEventListener('change', () => { const c = styleHasMoldings($('pStyle').value); $('pCrown').checked = c; $('pBase').checked = c; });
  $('pApply').addEventListener('click', () => {
    if (!state.id) return;
    const op = moldingsOp(state.spec, { crown: $('pCrown').checked, base: $('pBase').checked, crownProfile: $('pCrownProf').value, baseProfile: $('pBaseProf').value, openEnd: $('pEnd').value, style: $('pStyle').value });
    run('áp dụng phào', async () => afterChange(await api(`/api/designs/${state.id}/ops`, 'POST',
      { baseRev: state.rev, op })));
  });
  return { loadProfiles, syncMoldingPanel };
}
