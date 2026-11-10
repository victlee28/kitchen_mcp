// Render ảnh "chụp" (beauty) từ JSON three.js ngay trong trình duyệt — không cần API AI.
// Vật liệu PBR + ánh sáng trong tài liệu + môi trường phòng (RoomEnvironment) cho phản xạ, đổ bóng mềm, tone mapping ACES.
// Camera lấy từ doc.cameras: cùng vị trí / fov / tỉ lệ với ảnh điều khiển (nét, depth, mask), nên ảnh khớp mask từng pixel.
import * as THREE from 'three';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { buildKitchen } from './scene-loader.js';

export const viewOf = (cameraId) => cameraId.replace(/^CAM-/, '');

// Đèn bổ sung khi tài liệu chỉ có ánh sáng tối thiểu: nắng xiên từ phía phòng + đèn trần
function fillLights(scene, bounds, opts) {
  const c = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
  const sun = new THREE.DirectionalLight(0xfff1dc, opts.sun ?? 2.2);
  sun.position.set(c.x - size.x * 0.6, c.y + size.y * 1.5 + 2, c.z + size.z * 1.4 + 2);
  sun.target.position.copy(c);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const r = Math.max(size.x, size.z) * 0.9 + 1;
  Object.assign(sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 0.1, far: 40 });
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02; sun.shadow.radius = 4;
  scene.add(sun, sun.target);
  return sun;
}

/**
 * Render mọi camera (hoặc views) của tài liệu. Trả [{camId, view, name, width, height, dataUrl}].
 * opts: width, height (mặc định 1280×960 = cỡ ảnh điều khiển), views (mảng view id), exposure, envIntensity, extraLights.
 */
export async function renderDoc(doc, opts = {}) {
  const W = opts.width || 1280, H = opts.height || 960;
  const canvas = opts.canvas || document.createElement('canvas');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = opts.exposure ?? doc.renderSettings?.exposure ?? 1.0;
  renderer.shadowMap.enabled = doc.renderSettings?.shadows !== false;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(doc.renderSettings?.backgroundColor || '#f4f1eb');
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  if ('environmentIntensity' in scene) scene.environmentIntensity = opts.envIntensity ?? 0.35;

  const k = buildKitchen(doc, THREE, { RectAreaLightUniformsLib, edges: false, opaqueWalls: true });
  scene.add(k.root);
  k.root.traverse((o) => {
    if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
    if (o.isHemisphereLight || o.isAmbientLight) o.intensity *= opts.ambientScale ?? 0.45; // để bóng đổ và khối rõ hơn
  });
  const bounds = new THREE.Box3().setFromObject(k.root);
  if (opts.extraLights !== false) fillLights(scene, bounds, opts);

  const want = opts.views ? new Set(opts.views) : null;
  const out = [];
  for (const [cameraId, c] of Object.entries(k.cameras)) {
    const view = viewOf(cameraId);
    if (want && !want.has(view) && !want.has(cameraId)) continue;
    const camera = new THREE.PerspectiveCamera(c.fov, W / H, c.near, c.far);
    camera.up.set(...c.up);
    camera.position.set(...c.position);
    camera.lookAt(new THREE.Vector3(...c.target));
    camera.updateProjectionMatrix();
    const hidden = [];      // structures standing between this camera and the cabinets (walls, stairs, furniture) are left out of its picture
    if (c.hide?.length) { const h = new Set(c.hide); k.root.traverse((o) => { if (o.visible && h.has(o.userData?.structureId)) { o.visible = false; hidden.push(o); } }); }
    renderer.render(scene, camera);
    for (const o of hidden) o.visible = true;
    out.push({ cameraId, view, name: c.name, width: W, height: H, dataUrl: canvas.toDataURL('image/png') });
    if (opts.onProgress) await opts.onProgress(out[out.length - 1], out.length);
    await new Promise((r) => setTimeout(r, 0)); // nhường luồng giao diện
  }
  pmrem.dispose(); renderer.dispose();
  return out;
}
