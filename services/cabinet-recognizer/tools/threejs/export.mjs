// node tools/threejs/export.mjs spec.json scene.three.json   (cần: npm i three@0.160.0)
import * as THREE from 'three';
import fs from 'fs';
import { buildKitchen } from './kitchen3d.js';
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const { root, modules } = buildKitchen(THREE, spec);
const scene = new THREE.Scene(); scene.name = spec.name || 'kitchen'; scene.add(root);
fs.writeFileSync(process.argv[3], JSON.stringify(scene.toJSON()));
console.log('modules', modules.length);
