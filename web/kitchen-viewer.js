// The 3D view: three.js scene, camera, render loop, picking by click and right click. It knows nothing of the design state, the popup or the API:
// the page tells it what to show (setDocument / setSelected / setViews / setView) and hears what was picked (onPick / onContext).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { buildKitchen } from './scene-loader.js';
import { isClick, pickTarget, sceneToMm } from './menu-logic.js';

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
  let meshes = []; let doc = null; let views = {}; let selected = null;

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene3, camera); })();

  const selMats = new WeakMap();
  function highlight() {
    for (const m of meshes) {
      const sel = selected && m.userData.module === selected;
      if (!m.userData.baseMat) m.userData.baseMat = m.material;
      if (sel) {
        if (!selMats.has(m.userData.baseMat)) {
          const c = m.userData.baseMat.clone(); c.emissive = new THREE.Color(0x2f6bff); c.emissiveIntensity = 0.35; selMats.set(m.userData.baseMat, c);
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
    return target;
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
      root.clear();
      const k = buildKitchen(doc, THREE, { RectAreaLightUniformsLib });
      root.add(k.root);
      meshes = k.pickables;
      opts.onSceneBuilt(k);
      highlight();
    },
    setSelected(id) { selected = id || null; highlight(); },
    setViews(next) { views = next || {}; },
    /** Move the camera to the named view (ignored when there is none). */
    setView(key) {
      const v = views[key]; if (!v) return;
      camera.position.set(...v.position); camera.fov = v.verticalFov; camera.updateProjectionMatrix();
      controls.target.set(...v.lookAt); controls.update();
    },
  };
}
