// Dựng scene three.js từ tài liệu "Complete Kitchen Three.js Scene Schema" (v1.0/v1.1).
// Quy ước: positionAnchor = bottom_back_left; vật con theo hệ cục bộ của cha; góc xoay theo độ (rotation.unit).
// Dùng: const k = buildKitchen(doc, THREE, { RectAreaLightUniformsLib }); scene.add(k.root);
// opts.edges=false: không vẽ đường viền; opts.opaqueWalls=true: tường đặc (ảnh chụp), mặc định tường mờ để dễ sửa.
const SCALE = { mm: 0.001, cm: 0.01, m: 1 };

export function buildKitchen(doc, THREE, opts = {}) {
  const s = SCALE[doc.units || 'mm'];
  if (doc.coordinateSystem?.positionAnchor && doc.coordinateSystem.positionAnchor !== 'bottom_back_left') {
    console.warn('[scene-loader] chỉ hỗ trợ đầy đủ positionAnchor=bottom_back_left');
  }
  const mats = new Map();
  for (const m of doc.materials || []) mats.set(m.id, makeMaterial(m, THREE));
  const fallback = new THREE.MeshStandardMaterial({ color: 0xcccccc });
  const material_text = (id) => mats.get(id) || fallback;
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x3a3630 });
  const root = new THREE.Group(); root.name = doc.metadata?.projectName || 'Kitchen';
  const byModule = new Map(); const pickables = [];

  const rad = (r) => (r?.unit === 'rad' ? 1 : Math.PI / 180);
  function place(obj, tf) {
    if (!tf) return obj;
    obj.position.set(tf.position.x * s, tf.position.y * s, tf.position.z * s);
    const k = rad(tf.rotation);
    obj.rotation.set((tf.rotation?.x || 0) * k, (tf.rotation?.y || 0) * k, (tf.rotation?.z || 0) * k);
    if (tf.scale) obj.scale.set(tf.scale.x, tf.scale.y, tf.scale.z);
    return obj;
  }
  // hộp với anchor ở góc dưới-sau-trái: Group đặt tại anchor, Mesh lệch nửa kích thước
  const drawEdges = opts.edges !== false;
  function box(d, material, tf, info = {}, edges = drawEdges) {
    const g = place(new THREE.Group(), tf);
    const geo = new THREE.BoxGeometry(d.width * s, d.height * s, d.depth * s);
    const mesh = new THREE.Mesh(geo, material);
    mesh.position.set(d.width * s / 2, d.height * s / 2, d.depth * s / 2);
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.userData = info;
    if (edges) mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat));
    g.add(mesh);
    return { group: g, mesh };
  }

  // phòng
  const room = new THREE.Group(); room.name = 'room'; root.add(room);
  for (const w of doc.room?.walls || []) {
    const a = w.start, b = w.end;
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    const n = w.interiorNormal || { x: 0, y: 0, z: 1 };
    const wallMat = material_text(w.materialId).clone();
    if (!opts.opaqueWalls) { wallMat.transparent = true; wallMat.opacity = 0.35; }
    const geo = new THREE.BoxGeometry(len * s, w.height * s, w.thickness * s);
    const mesh = new THREE.Mesh(geo, wallMat);
    const ang = Math.atan2(-(b.z - a.z), b.x - a.x);
    mesh.rotation.y = ang;
    mesh.position.set(((a.x + b.x) / 2 - n.x * w.thickness / 2) * s, w.height * s / 2, ((a.z + b.z) / 2 - n.z * w.thickness / 2) * s);
    mesh.userData = { type: 'wall', wallId: w.id }; mesh.receiveShadow = true;
    room.add(mesh);
  }
  if (doc.room?.dimensions) {
    const d = doc.room.dimensions;
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(d.width * s + 2, d.depth * s + 2), material_text(doc.room.floor?.materialId));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(-d.width * s / 2, 0, d.depth * s / 2);
    floor.receiveShadow = true; floor.userData = { type: 'floor' };
    room.add(floor);
  }

  // module
  for (const m of doc.modules || []) {
    if (m.visible === false) continue;
    const g = place(new THREE.Group(), m.transform);
    g.name = m.id; g.userData = { module: m.sourceRef || m.id, moduleId: m.id };
    const info = { module: m.sourceRef || m.id };
    for (const p of m.parts || []) {
      const { group, mesh } = box(p.dimensions, material_text(p.materialId), p.transform, { ...info, role: p.role, semanticClass: p.semanticClass });
      g.add(group); pickables.push(mesh);
    }
    for (const d of [...(m.doors || []), ...(m.drawers || [])]) {
      const { group, mesh } = box(d.dimensions, material_text(d.materialId), d.transform, { ...info, role: d.hingeSide ? 'door' : 'drawer' });
      if (d.openingAngle && d.hingeSide) openDoor(group, d, s);
      const h = d.hardware;
      if (h && h.transform) {
        const hd = h.dimensions || { width: 12, height: 160, depth: 30 };
        group.add(box(hd, material_text(h.materialId), h.transform, { ...info, role: 'handle' }, false).group);
      }
      g.add(group); pickables.push(mesh);
    }
    root.add(g); byModule.set(info.module, g);
  }
  // phào: quét mặt cắt (assets[assetId].parameters.profile) dọc path, vát góc ở đỉnh giữa
  const assetById = new Map((doc.assets || []).map((a) => [a.id, a]));
  for (const dec of doc.decorations || []) {
    const profile = assetById.get(dec.assetId)?.parameters?.profile;
    if (!dec.path?.points || !profile) continue;
    const mesh = sweepMesh(profile, dec.path.points, THREE, s, material_text(dec.materialId));
    mesh.userData = { module: dec.sourceRef || dec.id, role: dec.type, semanticClass: 'molding' };
    const g = place(new THREE.Group(), dec.transform);
    g.name = dec.id; g.add(mesh); root.add(g); pickables.push(mesh);
  }
  // thiết bị, phụ kiện, trang trí dạng hộp
  for (const a of [...(doc.appliances || []), ...(doc.accessories || []), ...(doc.decorations || []).filter((d) => !d.path)]) {
    if (!a.dimensions) continue;
    const { group, mesh } = box(a.dimensions, material_text(a.materialId), a.transform, { module: a.sourceRef || a.id, role: a.type });
    group.name = a.id; root.add(group); pickables.push(mesh);
  }

  // đèn
  const lights = [];
  if (opts.RectAreaLightUniformsLib && (doc.lighting || []).some((l) => l.type === 'RectAreaLight')) opts.RectAreaLightUniformsLib.init();
  for (const l of doc.lighting || []) {
    const color = new THREE.Color(l.color);
    let light;
    switch (l.type) {
      case 'AmbientLight': light = new THREE.AmbientLight(color, l.intensity); break;
      case 'HemisphereLight': light = new THREE.HemisphereLight(color, new THREE.Color(l.groundColor || '#444444'), l.intensity); break;
      case 'DirectionalLight': light = new THREE.DirectionalLight(color, l.intensity); break;
      case 'PointLight': light = new THREE.PointLight(color, l.intensity, (l.distance || 0) * s, l.decay ?? 2); break;
      case 'SpotLight': light = new THREE.SpotLight(color, l.intensity, (l.distance || 0) * s, ((l.angle ?? 45) * Math.PI) / 180, l.penumbra ?? 0, l.decay ?? 2); break;
      case 'RectAreaLight':
        if (!opts.RectAreaLightUniformsLib) continue; // cần addon RectAreaLightUniformsLib
        light = new THREE.RectAreaLight(color, l.intensity, (l.width || 100) * s, (l.height || 20) * s); break;
      default: continue;
    }
    if (l.position) light.position.set(l.position.x * s, l.position.y * s, l.position.z * s);
    if (l.target) {
      const t = new THREE.Vector3(l.target.x * s, l.target.y * s, l.target.z * s);
      if (light.target) { light.target.position.copy(t); root.add(light.target); } else light.lookAt(t);
    }
    if (l.castShadow && 'castShadow' in light) light.castShadow = true;
    light.name = l.id; root.add(light); lights.push(light);
  }

  // camera: trả cấu hình (mét) để app tự áp
  const cameras = {};
  for (const c of doc.cameras || []) {
    cameras[c.id] = { name: c.name || c.id, fov: c.fov, near: (c.near || 50) * s, far: (c.far || 50000) * s,
      position: [c.position.x * s, c.position.y * s, c.position.z * s], target: [c.target.x * s, c.target.y * s, c.target.z * s],
      up: c.up ? [c.up.x, c.up.y, c.up.z] : [0, 1, 0] };
  }
  return { root, lights, cameras, byModule, pickables };
}

// Vòng đỉnh tại mỗi đỉnh đường chạy — cùng thuật toán với kitchen/moldings.py sweep_rings (test so khớp).
// points: [{x,y,z}] (y của điểm đầu là cao độ đường chạy); profile: [[u, v]]; trả [[[x,y,z]...]...] cùng đơn vị với đầu vào.
export function sweepRings(profile, points) {
  const P = points.map((p) => [p.x, p.z]); const y = points[0].y;
  const ns = [];
  for (let i = 0; i + 1 < P.length; i++) {
    const dx = P[i + 1][0] - P[i][0], dz = P[i + 1][1] - P[i][1], L = Math.hypot(dx, dz);
    const t = [dx / L, dz / L]; ns.push([t[1], -t[0]]);
  }
  return P.map((p, i) => {
    let m;
    if (i === 0) m = ns[0];
    else if (i === P.length - 1) m = ns[ns.length - 1];
    else {
      const a = ns[i - 1], b = ns[i], k = 1 + a[0] * b[0] + a[1] * b[1];
      m = k > 1e-6 ? [(a[0] + b[0]) / k, (a[1] + b[1]) / k] : b;
    }
    return profile.map(([u, v]) => [p[0] + m[0] * u, y + v, p[1] + m[1] * u]);
  });
}

function sweepMesh(profile, points, THREE, s, material) {
  const rings = sweepRings(profile, points), n = profile.length;
  const pos = []; const idx = [];
  for (const r of rings) for (const v of r) pos.push(v[0] * s, v[1] * s, v[2] * s);
  for (let k = 0; k + 1 < rings.length; k++) {
    for (let j = 0; j < n; j++) {
      const a = k * n + j, b = k * n + ((j + 1) % n), c = (k + 1) * n + ((j + 1) % n), d = (k + 1) * n + j;
      idx.push(a, b, c, a, c, d);
    }
  }
  const tris = THREE.ShapeUtils ? THREE.ShapeUtils.triangulateShape(profile.map(([u, v]) => new THREE.Vector2(u, v)), []) : [];
  const last = (rings.length - 1) * n;
  for (const [a, b, c] of tris) idx.push(c, b, a, last + a, last + b, last + c);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  const m2 = material.clone(); m2.side = THREE.DoubleSide;
  const mesh = new THREE.Mesh(geo, m2);
  mesh.castShadow = mesh.receiveShadow = true;
  if (THREE.EdgesGeometry) mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 20), new THREE.LineBasicMaterial({ color: 0x3a3630 })));
  return mesh;
}

function makeMaterial(m, THREE) {
  const Type = THREE[m.threeMaterialType] || THREE.MeshStandardMaterial;
  const p = { color: new THREE.Color(m.color.slice(0, 7)) };
  if (Type !== THREE.MeshBasicMaterial) Object.assign(p, { roughness: m.roughness ?? 0.5, metalness: m.metalness ?? 0 });
  if (m.opacity !== undefined && m.opacity < 1) Object.assign(p, { opacity: m.opacity, transparent: true });
  if (m.transparent) p.transparent = true;
  if (Type === THREE.MeshPhysicalMaterial) Object.assign(p, { transmission: m.transmission ?? 0, ior: m.ior ?? 1.5, clearcoat: m.clearcoat ?? 0 });
  if (m.side) p.side = THREE[m.side];
  if (m.emissive) Object.assign(p, { emissive: new THREE.Color(m.emissive), emissiveIntensity: m.emissiveIntensity ?? 1 });
  if (Type === THREE.MeshPhongMaterial) { delete p.roughness; delete p.metalness; }
  const material_text = new Type(p);
  if (m.map) {
    const tex = new THREE.TextureLoader().load(m.map);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    const r = m.textureRepeat || (m.repeat ? { u: m.repeat.x, v: m.repeat.y } : null);
    if (r) tex.repeat.set(r.u, r.v);
    if (m.textureRotation) tex.rotation = (m.textureRotation * Math.PI) / 180;
    material_text.map = tex;
  }
  material_text.name = m.id;
  return material_text;
}

// mở cánh quanh cạnh bản lề (dùng cho minh họa)
function openDoor(group, d, s) {
  const a = (d.openingAngle * Math.PI) / 180, w = d.dimensions.width * s, h = d.dimensions.height * s;
  const pivot = { Left: [0, 0], Right: [w, 0], Top: [0, h], Bottom: [0, 0] }[d.hingeSide] || [0, 0];
  const mesh = group.children[0];
  const holder = new (mesh.parent.constructor)();
  holder.position.set(pivot[0], pivot[1], d.dimensions.depth * s);
  group.add(holder);
  mesh.position.x -= pivot[0]; mesh.position.y -= pivot[1]; mesh.position.z -= d.dimensions.depth * s;
  holder.add(mesh);
  if (d.hingeSide === 'Left') holder.rotation.y = -a; else if (d.hingeSide === 'Right') holder.rotation.y = a;
  else if (d.hingeSide === 'Top') holder.rotation.x = -a; else holder.rotation.x = a;
}
