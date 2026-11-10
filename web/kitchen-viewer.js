// The 3D view: three.js scene, camera, render loop, picking by click and right click. It knows nothing of the design state, the popup or the API:
// the page tells it what to show (setDocument / setSelected / setViews / setView) and hears what was picked (onPick / onContext).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { buildKitchen } from './scene-loader.js';
import { dragChange, floorPoint, isClick, pickTarget, sceneToMm } from './menu-logic.js';

/**
 * opts: { container, moduleIds() -> string[] | null (null: nothing to pick yet), extraPickables() -> Object3D[],
 *         onSceneBuilt({structures, structurePickables}), onPick({kind:'module'|'structure', id} | null, {x, y}, menuTarget | null),
 *         onContext(target | null, {x, y}) }   target: see menu-logic.pickTarget; target.point is in millimetres.
 */
export function createViewer(opts) {
  const { container } = opts;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(devicePixelRatio);
  container.append(renderer.domElement);
  const scene3 = new THREE.Scene();
  scene3.background = new THREE.Color(0xf4f1eb);
  // môi trường phòng cho phản xạ: vật liệu kim loại (inox tủ lạnh, tay nắm) không bị đen
  scene3.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
  if ('environmentIntensity' in scene3) scene3.environmentIntensity = 0.5;
  renderer.shadowMap.enabled = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  const root = new THREE.Group(); scene3.add(root);
  const raycaster = new THREE.Raycaster(); const pointer = new THREE.Vector2();
  let meshes = []; let doc = null; let views = {}; let hiddenByView = []; let selected = null;

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene3, camera); })();

  // ---- overlay: the line of a run being drawn, and the handles of the selected cabinet's run (never part of the kitchen document)
  const overlay = new THREE.Group(); scene3.add(overlay);
  const guideGroup = new THREE.Group(); const handleGroup = new THREE.Group(); overlay.add(guideGroup, handleGroup);
  const overlayMat = new THREE.MeshBasicMaterial({ color: 0x2f6bff, depthTest: false, transparent: true, opacity: 0.9 });
  const moveMat = new THREE.MeshBasicMaterial({ color: 0xff8a1f, depthTest: false, transparent: true, opacity: 0.9 });
  const unit = () => ({ mm: 0.001, cm: 0.01, m: 1 }[doc?.units || 'mm']);        // scene units per millimetre
  let byModule = new Map(); let guide = null; let handleAxes = null; let drag = null; let suppressClick = false;

  function dot(x, z) { const m = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12), overlayMat); m.position.set(x, 0.03, z); m.renderOrder = 10; return m; }
  function bar(a, b) {
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    const m = new THREE.Mesh(new THREE.BoxGeometry(Math.max(len, 0.001), 0.015, 0.03), overlayMat);
    m.position.set((a.x + b.x) / 2, 0.02, (a.z + b.z) / 2); m.rotation.y = Math.atan2(-(b.z - a.z), b.x - a.x); m.renderOrder = 10;
    return m;
  }
  function drawGuide(to) {
    guideGroup.clear();
    if (!guide) return;
    const k = unit(); const a = { x: guide.from.x * k, z: guide.from.z * k };
    guideGroup.add(dot(a.x, a.z));
    if (to) guideGroup.add(bar(a, to), dot(to.x, to.z));
  }
  function floorAt(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    return floorPoint(raycaster.ray.origin, raycaster.ray.direction);
  }
  // Three handles in front of the run of the selected cabinet: its two ends (drag along the run) and its middle (drag the whole run).
  function refreshHandles() {
    handleGroup.clear(); handleAxes = null;
    const ids = typeof selected === 'string' && opts.runModules ? opts.runModules(selected) : null;      // a group shows no run handles
    const groups = (ids || []).map((id) => byModule.get(id)).filter((g) => g && g.userData.width > 0);
    if (!groups.length) return;
    scene3.updateMatrixWorld(true);
    const k = unit(); const q = new THREE.Quaternion(); const p0 = new THREE.Vector3();
    groups[0].getWorldPosition(p0); groups[0].getWorldQuaternion(q);
    const u = new THREE.Vector3(1, 0, 0).applyQuaternion(q).setY(0).normalize(), n = new THREE.Vector3(0, 0, 1).applyQuaternion(q).setY(0).normalize();
    let s0 = Infinity, s1 = -Infinity, depth = 0; const p = new THREE.Vector3();
    for (const g of groups) {
      const at = g.getWorldPosition(p).sub(p0).dot(u);
      s0 = Math.min(s0, at); s1 = Math.max(s1, at + g.userData.width * k); depth = Math.max(depth, g.userData.depth * k);
    }
    const front = depth + 0.18;
    for (const [name, s, mat] of [['start', s0, overlayMat], ['end', s1, overlayMat], ['move', (s0 + s1) / 2, moveMat]]) {
      const m = new THREE.Mesh(name === 'move' ? new THREE.BoxGeometry(0.14, 0.14, 0.14) : new THREE.SphereGeometry(0.08, 20, 14), mat);
      m.position.copy(p0).addScaledVector(u, s).addScaledVector(n, front).setY(0.09);
      m.renderOrder = 11; m.userData = { handle: name, home: m.position.clone() };
      handleGroup.add(m);
    }
    handleAxes = { u, n };
  }
  renderer.domElement.addEventListener('pointerdown', (ev) => {       // capture: before the orbit controls start turning the camera
    if (ev.button !== 0 || ev.ctrlKey || !handleGroup.children.length) return;
    const at = floorAt(ev);
    const hit = raycaster.intersectObjects(handleGroup.children, false)[0];
    if (!hit || !at) return;
    drag = { mesh: hit.object, from: at, d: { x: 0, z: 0 } };
    controls.enabled = false; renderer.domElement.style.cursor = 'grabbing';
  }, true);
  renderer.domElement.addEventListener('pointermove', (ev) => {
    if (drag) {
      const at = floorAt(ev); if (!at) return;
      drag.d = { x: at.x - drag.from.x, z: at.z - drag.from.z };
      const { u } = handleAxes; const home = drag.mesh.userData.home;
      if (drag.mesh.userData.handle === 'move') drag.mesh.position.set(home.x + drag.d.x, home.y, home.z + drag.d.z);
      else drag.mesh.position.copy(home).addScaledVector(u, drag.d.x * u.x + drag.d.z * u.z);       // an end slides along its run only
      return;
    }
    if (guide && !guide.to) { const at = floorAt(ev); if (at) { drawGuide(at); opts.onGuide?.(Math.hypot(at.x / unit() - guide.from.x, at.z / unit() - guide.from.z)); } }
  });
  window.addEventListener('pointerup', (ev) => {
    if (!drag) return;
    const { u, n } = handleAxes; const k = unit(); const d = drag; drag = null;
    controls.enabled = true; renderer.domElement.style.cursor = ''; suppressClick = true; setTimeout(() => { suppressClick = false; }, 80);   // released outside the view: no click follows
    d.mesh.position.copy(d.mesh.userData.home);
    const change = dragChange(d.mesh.userData.handle, (d.d.x * u.x + d.d.z * u.z) / k, (d.d.x * n.x + d.d.z * n.z) / k);
    if (change && typeof selected === 'string') opts.onRunDrag?.({ module: selected, ...change }, { x: ev.clientX, y: ev.clientY });
  });

  // a Shift-selected group lights only its role's parts: doors (glass ones too), drawer fronts, handles, or all three
  const ROLE_PARTS = { door: ['door'], drawer: ['drawer'], handle: ['handle'], all: ['door', 'drawer', 'handle'] };
  const inRole = (part, role) => (ROLE_PARTS[role] || []).includes(part);
  const selMats = new WeakMap();
  const SEL_TINT = new THREE.Color(0x2f6bff);
  function highlight() {
    for (const m of meshes) {
      const sel = typeof selected === 'string' ? m.userData.module === selected : !!selected && selected.modules.includes(m.userData.module) && inRole(m.userData.role, selected.role);
      if (!m.userData.baseMat) m.userData.baseMat = m.material;
      if (sel) {
        if (!selMats.has(m.userData.baseMat)) {
          const c = m.userData.baseMat.clone(); c.color?.lerp(SEL_TINT, 0.45); c.emissive = SEL_TINT.clone(); c.emissiveIntensity = 0.25; selMats.set(m.userData.baseMat, c);   // tint the colour too: emissive alone vanishes on white fronts
        }
        m.material = selMats.get(m.userData.baseMat);
      } else m.material = m.userData.baseMat;
    }
  }

  const hitsAt = (ev) => {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    return raycaster.intersectObjects([...meshes, ...opts.extraPickables()], false);
  };

  // left click: the nearest thing under the pointer wins: a cabinet module or a visible floorplan element
  renderer.domElement.addEventListener('click', (ev) => {
    if (suppressClick) { suppressClick = false; return; }      // the release of a handle drag is not a click on what lies under it
    if (ev.shiftKey && opts.onShiftPick) { opts.onShiftPick(contextTarget(ev)); return; }   // Shift: the same role in the same tier of the same system
    const ids = opts.moduleIds() || [];
    const hit = hitsAt(ev).find((h) => h.object.userData.structureId || (h.object.userData.module && ids.includes(h.object.userData.module)));
    const at = { x: ev.clientX, y: ev.clientY };
    const menuTarget = contextTarget(ev);     // what a right click here would open the menu on (null = empty space)
    if (hit?.object.userData.structureId) opts.onPick({ kind: 'structure', id: hit.object.userData.structureId }, at, menuTarget);
    else if (hit) opts.onPick({ kind: 'module', id: hit.object.userData.module }, at, menuTarget);
    else opts.onPick(null, at, null);
  });

  function contextTarget(ev) {
    const ids = opts.moduleIds();
    if (!ids) return null;
    const target = pickTarget(hitsAt(ev), ids);
    if (target?.point) target.point = sceneToMm(target.point, doc?.units);
    if (target) return target;
    const onFloor = floorPoint(raycaster.ray.origin, raycaster.ray.direction);      // nothing under the pointer: the floor, where a run can be drawn
    return onFloor ? { kind: 'floor', id: 'floor', point: sceneToMm(onFloor, doc?.units) } : null;
  }

  // context menu: opens on the release of a right click (or Ctrl+click) that did not move. Windows fires `contextmenu` on release but
  // Linux/macOS on press, so the event itself cannot tell a click from the start of a camera drag (right-drag pans).
  let lastDown = null;
  renderer.domElement.addEventListener('pointerdown', (ev) => { lastDown = { x: ev.clientX, y: ev.clientY, t: performance.now(), button: ev.button, ctrl: ev.ctrlKey }; });
  renderer.domElement.addEventListener('contextmenu', (ev) => ev.preventDefault());
  renderer.domElement.addEventListener('pointerup', (ev) => {
    const d = lastDown; lastDown = null;
    const ids = opts.moduleIds();
    if (!d || !(d.button === 2 || (d.button === 0 && d.ctrl)) || !isClick(d, { x: ev.clientX, y: ev.clientY, t: performance.now() }) || !ids) return;
    opts.onContext(contextTarget(ev), { x: ev.clientX, y: ev.clientY });
  });

  return {
    THREE,
    /** Build the scene from a three.js scene document (/api/designs/<id>/threejs). */
    setDocument(next) {
      doc = next;
      root.clear(); hiddenByView = [];
      const k = buildKitchen(doc, THREE, { RectAreaLightUniformsLib });
      root.add(k.root);
      meshes = k.pickables; byModule = k.byModule;
      opts.onSceneBuilt(k);
      highlight(); refreshHandles(); drawGuide(guide?.to ? { x: guide.to.x * unit(), z: guide.to.z * unit() } : null);
    },
    /** One module (its id), a Shift-selected group ({ modules, role }), or nothing. */
    setSelected(sel) { selected = sel || null; highlight(); refreshHandles(); },
    /** Whether the view shows a part of `role` (door / drawer / handle / all) on `module`. */
    hasRole(module, role) { return meshes.some((m) => m.userData.module === module && inRole(m.userData.role, role)); },
    /** The line of a run being drawn: `from` (mm) alone follows the pointer, with `to` it is fixed; null removes it. */
    setGuide(from, to = null) {
      guide = from ? { from, to } : null;
      drawGuide(guide?.to ? { x: to.x * unit(), z: to.z * unit() } : null);
    },
    setViews(next) { views = next || {}; },
    /** Move the camera to the named view (ignored when there is none). */
    setView(key) {
      const v = views[key]; if (!v) return;
      // structures standing between this camera and the cabinets (walls, columns, furniture) are hidden for this view only
      const hide = new Set(v.hide || []);
      for (const o of hiddenByView) o.visible = true;
      hiddenByView = [];
      if (hide.size) root.traverse((o) => { if (o.userData && hide.has(o.userData.structureId) && o.visible) { o.visible = false; hiddenByView.push(o); } });
      camera.position.set(...v.position); camera.fov = v.verticalFov; camera.updateProjectionMatrix();
      controls.target.set(...v.lookAt); controls.update();
    },
  };
}
