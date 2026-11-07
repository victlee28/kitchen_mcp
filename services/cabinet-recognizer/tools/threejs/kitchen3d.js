// Dựng cảnh three.js từ JSON "cabinet-recognizer/0.2-draft" (bếp chữ L).
// Đơn vị JSON: mm. Cảnh: mét, Y lên.
// Gốc = góc trong giữa tường sau và tường trái tại sàn.
//   Tường sau nằm ở z = 0, tủ nhô ra +z. Module "back": x chạy theo +X.
//   Tường trái nằm ở x = 0, tủ nhô ra +x. Module "left": "x" của JSON chạy theo +Z.
export function buildKitchen(THREE, spec) {
  const S = 0.001, C = spec.common;
  const GAP = 3, FRONT = 18, INSET = 50;           // khe cánh, dày cánh, chân tủ lùi vào
  const root = new THREE.Group(); root.name = 'kitchen';
  const hasRight = spec.modules.some(m => m.wall === 'right');
  const WB = (spec.walls && spec.walls.back && (spec.walls.back.wallLength || (hasRight && spec.walls.back.runLength))) || 0;   // tường phải ở x = WB

  const mat = {
    gloss: new THREE.MeshStandardMaterial({ name: 'acrylic-white-gloss', color: 0xf4f4f2, roughness: 0.12, metalness: 0.05 }),
    carcass: new THREE.MeshStandardMaterial({ name: 'carcass-white', color: 0xe6e6e4, roughness: 0.6 }),
    wood: new THREE.MeshStandardMaterial({ name: 'laminate-dark-wood', color: 0x4a3f36, roughness: 0.7 }),
    worktop: new THREE.MeshStandardMaterial({ name: 'stone-dark', color: 0x22211f, roughness: 0.35 }),
    splash: new THREE.MeshStandardMaterial({ name: 'glass-lime', color: 0xb9c832, roughness: 0.15, emissive: 0x3a4200, emissiveIntensity: 0.25 }),
    glass: new THREE.MeshStandardMaterial({ name: 'glass-clear', color: 0xcfe3e8, roughness: 0.05, transparent: true, opacity: 0.35 }),
    darkGlass: new THREE.MeshStandardMaterial({ name: 'glass-dark', color: 0x2b2d30, roughness: 0.1 }),
    steel: new THREE.MeshStandardMaterial({ name: 'steel', color: 0xb8bcc0, roughness: 0.3, metalness: 0.8 }),
    fridge: new THREE.MeshStandardMaterial({ name: 'fridge-steel', color: 0x8d9296, roughness: 0.35, metalness: 0.6 }),
    black: new THREE.MeshStandardMaterial({ name: 'black-glass', color: 0x0d0d0f, roughness: 0.08 }),
    led: new THREE.MeshStandardMaterial({ name: 'led', color: 0xfff6c8, emissive: 0xfff2a0, emissiveIntensity: 1.5 }),
    floor: new THREE.MeshStandardMaterial({ name: 'floor-tile', color: 0xc9cbcd, roughness: 0.25 }),
    wall: new THREE.MeshStandardMaterial({ name: 'wall', color: 0xdcdcda, roughness: 0.9 }),
  };

  // Hộp theo mm trong khung "dọc tường": u = dọc tường từ góc, d = khoảng cách ra khỏi tường, y = từ sàn
  function box(parent, wall, u0, u1, y0, y1, d0, d1, material, name) {
    const g = new THREE.BoxGeometry(1, 1, 1);
    const m = new THREE.Mesh(g, material); m.name = name || '';
    const w = (u1 - u0) * S, h = (y1 - y0) * S, dd = (d1 - d0) * S;
    if (wall === 'left') { m.scale.set(dd, h, w); m.position.set((d0 + d1) / 2 * S, (y0 + y1) / 2 * S, (u0 + u1) / 2 * S); }
    else if (wall === 'right') { m.scale.set(dd, h, w); m.position.set((WB - (d0 + d1) / 2) * S, (y0 + y1) / 2 * S, (u0 + u1) / 2 * S); }
    else { m.scale.set(w, h, dd); m.position.set((u0 + u1) / 2 * S, (y0 + y1) / 2 * S, (d0 + d1) / 2 * S); }
    m.castShadow = m.receiveShadow = true;
    parent.add(m); return m;
  }
  // các tấm mặt trước chia theo phương ngang (cánh) trong khoảng [y0, y1]
  function fronts(g, wall, u0, widths, y0, y1, depth, material, name) {
    let u = u0;
    widths.forEach((w, i) => { box(g, wall, u + GAP / 2, u + w - GAP / 2, y0 + GAP / 2, y1 - GAP / 2, depth, depth + FRONT, material, `${name}-${i + 1}`); u += w; });
  }
  // các tấm chồng theo phương đứng (ngăn kéo, cánh nâng) — heights từ dưới lên hoặc từ trên xuống
  function stack(g, wall, u0, u1, yTop, heights, depth, material, name) {
    let y = yTop;
    heights.forEach((h, i) => { box(g, wall, u0 + GAP / 2, u1 - GAP / 2, y - h + GAP / 2, y - GAP / 2, depth, depth + FRONT, material, `${name}-${i + 1}`); y -= h; });
  }

  const plinth = C.plinthHeight, wt = C.worktopTop, th = C.worktopThickness;
  const modules = [];

  for (let m of spec.modules) {
    let g = new THREE.Group(); g.name = m.id;
    g.userData = { ...m };
    const wall = m.wall, u0 = m.x, u1 = m.x + (m.width || 0), D = m.depth;

    if (m.type === 'upper-corner-open-shelf') {
      // kệ góc chữ L: chân dọc tường sau 0..legBack, chân dọc tường trái 0..legLeft
      const y0 = m.y, y1 = m.y + m.height, t = 18;
      const side = m.side || 'left', legSide = m.legSide ?? m.legLeft;
      for (let i = 0; i <= m.shelves; i++) {
        const y = y0 + (m.height - t) * i / m.shelves;
        box(g, 'back', 0, m.legBack, y, y + t, 0, D, mat.wood, 'shelf-back');
        box(g, side, D, legSide, y, y + t, 0, D, mat.wood, 'shelf-side');
      }
      box(g, 'back', m.legBack - t, m.legBack, y0, y1, 0, D, mat.wood, 'side-back');
      box(g, side, legSide - t, legSide, y0, y1, 0, D, mat.wood, 'side-side');
      root.add(g); modules.push(g); continue;
    }

    const isBase = m.storey === 'base', isTall = m.storey === 'tall';
    const yb = isBase || isTall ? plinth : m.y;
    const yt = isBase ? wt - th : m.y + m.height;
    // thân tủ
    if (isBase || isTall) box(g, wall, u0, u1, 0, plinth, 0, D - INSET, mat.wood, 'plinth');
    if (m.type !== 'base-dishwasher') box(g, wall, u0, u1, yb, yt, 0, D, mat.carcass, 'carcass');

    if (m.type === 'base-dishwasher') {
      box(g, wall, u0 + 10, u1 - 10, 0, 820, 0, D + FRONT, mat.steel, 'dishwasher');
      box(g, wall, u0 + 60, u1 - 60, 700, 780, D + FRONT, D + FRONT + 2, mat.black, 'dishwasher-panel');
    } else if (m.type === 'base-oven') {
      const ovenH = 450, rest = yt - yb - ovenH;
      box(g, wall, u0 + GAP, u1 - GAP, yt - ovenH + GAP, yt - GAP, D, D + FRONT, mat.steel, 'oven');
      box(g, wall, u0 + 40, u1 - 40, yt - ovenH + 60, yt - 120, D + FRONT, D + FRONT + 2, mat.black, 'oven-window');
      stack(g, wall, u0, u1, yt - ovenH, [rest / 2, rest / 2], D, mat.gloss, 'drawer');
    } else if (m.drawers) {
      stack(g, wall, u0, u1, yt, m.drawers, D, mat.gloss, 'drawer');
    } else if (m.sections) {
      for (const s of m.sections) {
        const sy0 = s.y, sy1 = s.y + s.height;
        if (s.kind === 'plinth') continue;
        if (s.kind === 'drawer' || s.kind === 'door') box(g, wall, u0 + GAP / 2, u1 - GAP / 2, sy0 + GAP / 2, sy1 - GAP / 2, D, D + FRONT, mat.gloss, s.kind);
        if (s.kind === 'doors') fronts(g, wall, u0, s.doors, sy0, sy1, D, mat.gloss, 'door');
        if (s.kind === 'glass-doors') {
          fronts(g, wall, u0, s.doors, sy0, sy1, D, mat.glass, 'glass-door');
          for (let i = 1; i <= s.shelves; i++) { const y = sy0 + s.height * i / (s.shelves + 1); box(g, wall, u0 + 18, u1 - 18, y, y + 8, 20, D - 10, mat.glass, 'glass-shelf'); }
        }
        if (s.kind === 'appliance' && s.appliance === 'microwave') {
          box(g, wall, u0 + 60, u1 - 60, sy0 + 20, sy1 - 20, D - 10, D + 5, mat.steel, 'microwave');
          box(g, wall, u0 + 90, u1 - 200, sy0 + 60, sy1 - 60, D + 5, D + 7, mat.black, 'microwave-door');
        }
        if (s.kind === 'appliance' && s.appliance === 'fridge') {
          const fw = 910, fu = u0 + (m.width - fw) / 2;
          box(g, wall, fu, fu + fw, 10, sy1 - 20, 30, 730, mat.fridge, 'fridge');
          box(g, wall, fu + fw / 2 - 2, fu + fw / 2 + 2, 10, sy1 - 20, 730, 732, mat.black, 'fridge-split');
        }
        if (s.kind === 'open') box(g, wall, u0 + 18, u1 - 18, sy0, sy0 + 18, 0, D, mat.carcass, 'open-shelf');
      }
    } else if (m.type === 'upper-dish-rack') {
      stack(g, wall, u0, u1, yt, m.flaps || [(yt - yb) / 2, (yt - yb) / 2], D, mat.glass, 'glass-flap');
      box(g, wall, u0 + 30, u1 - 30, yb + 60, yb + 70, 40, D - 40, mat.steel, 'dish-rack-1');
      box(g, wall, u0 + 30, u1 - 30, yb + 440, yb + 450, 40, D - 40, mat.steel, 'dish-rack-2');
    } else if (m.type === 'upper-lift-up') {
      if (!m.flaps) m = { ...m, flaps: [Math.round((yt - yb) / 2)] };
      stack(g, wall, u0, u1, yt, m.flaps, D, mat.gloss, 'flap');
      box(g, wall, u0 + GAP / 2, u1 - GAP / 2, yb + GAP / 2, yt - m.flaps.reduce((a, b) => a + b, 0) - GAP / 2, D, D + FRONT, mat.gloss, 'box-frame');
      box(g, wall, u0 + 40, u1 - 40, yb + 40, yt - m.flaps.reduce((a, b) => a + b, 0) - 40, D + FRONT, D + FRONT + 2, mat.darkGlass, 'dark-glass');
    } else if (m.flaps) {
      stack(g, wall, u0, u1, yt, m.flaps, D, mat.gloss, 'flap');
    } else if (m.doors) {
      const total = m.doors.reduce((a, b) => a + b, 0);
      const atEnd = m.blindSide === 'end';                  // tủ góc khuất: phần mù nằm phía góc
      const start = m.blindWidth && !atEnd ? u1 - total : u0;
      fronts(g, wall, start, m.doors, yb, yt, D, mat.gloss, 'door');
      if (m.blindWidth) { if (atEnd) box(g, wall, u0 + total, u1, yb, yt, D - 2, D, mat.carcass, 'blind-panel');
                          else box(g, wall, u0, start, yb, yt, D - 2, D, mat.carcass, 'blind-panel'); }
    }
    if (m.applianceBelow === 'hood') {
      box(g, wall, u0 + 60, u1 - 60, yb - 90, yb, 30, D - 20, mat.steel, 'hood');
      box(g, wall, u0 + 40, u1 - 40, yb - 100, yb - 90, 30, D + 40, mat.darkGlass, 'hood-glass');
    }
    if (m.storey === 'upper') box(g, wall, u0 + 20, u1 - 20, yb - 8, yb, D - 60, D - 40, mat.led, 'led');
    root.add(g); modules.push(g);
  }

  // mặt đá + ốp tường (chạy liên tục theo dãy dưới)
  const fx = (wall) => spec.modules.filter(m => m.wall === wall && m.storey === 'base');
  const ext = (wall) => { const ms = fx(wall); return [Math.min(...ms.map(m => m.x)), Math.max(...ms.map(m => m.x + m.width))]; };
  const has = (w) => fx(w).length > 0;
  const [bA, bB] = ext('back');
  const tops = new THREE.Group(); tops.name = 'worktop';
  box(tops, 'back', 0, bB, wt - th, wt, 0, C.baseDepth + 20, mat.worktop, 'worktop-back');
  for (const sw of ['left', 'right']) if (has(sw)) { const [a, b] = ext(sw); box(tops, sw, C.baseDepth + 20, b + 20, wt - th, wt, 0, C.baseDepth + 20, mat.worktop, 'worktop-' + sw); }
  // chậu rửa & bếp nấu trên mặt đá
  const sink = spec.modules.find(m => m.type === 'base-sink');
  if (sink) box(tops, sink.wall, sink.x + 60, sink.x + sink.width - 60, wt, wt + 3, 120, 520, mat.steel, 'sink');
  const ov = spec.modules.find(m => m.type === 'base-oven');
  if (ov) box(tops, ov.wall, ov.x + 10, ov.x + ov.width - 10, wt, wt + 6, 80, 510, mat.black, 'hob');
  root.add(tops);

  const room = new THREE.Group(); room.name = 'room';
  const tallEnd = Math.max(WB, ...spec.modules.filter(m => m.wall === 'back').map(m => m.x + (m.width || 0)));
  box(room, 'back', 0, tallEnd + 1500, -20, 0, 0, 4000, mat.floor, 'floor');
  box(room, 'back', 0, tallEnd + 1500, 0, 2900, -20, 0, mat.wall, 'wall-back');
  box(room, 'left', 0, 3800, 0, 2900, -20, 0, mat.wall, 'wall-left');
  const tallStart = Math.min(bB, ...spec.modules.filter(m => m.wall === 'back' && m.storey === 'tall').map(m => m.x));
  box(room, 'back', 0, tallStart, wt, C.upperBottom, 0, 6, mat.splash, 'backsplash-back');
  for (const sw of ['left', 'right']) if (has(sw)) box(room, sw, 0, ext(sw)[1], wt, C.upperBottom, 0, 6, mat.splash, 'backsplash-' + sw);
  if (WB) box(room, 'right', 0, 3800, 0, 2900, -20, 0, mat.wall, 'wall-right');
  root.add(room);

  return { root, modules };
}
