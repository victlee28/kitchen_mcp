"""Handle settings per storey / module: resolution, geometry, three.js export, and design edits from the image editor."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import edit, geometry, geometry_edit, handles, threejs_export  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import dump_spec, effective_handle, load_spec  # noqa: E402

FIX = ROOT / "fixtures" / "l-shaped-kitchen.json"
VIEW = "original-angle"


def _spec():
    return load_spec(json.loads(FIX.read_text(encoding="utf-8")))


def _handles_by_storey(spec):
    storey = {m.id: m.storey for m in spec.module}
    out: dict[str, list[str]] = {}
    for p in geometry.compile_spec(spec).parts:
        if p.type == "handle":
            out.setdefault(storey[p.module], []).append(p.id)
    return out


class TestResolution(unittest.TestCase):
    def test_order_module_over_storey_over_common(self):
        spec = _spec()
        base = spec.common.handle
        self.assertEqual(effective_handle(spec.common, spec.find("TT1")), base)
        spec = edit.apply_op(spec, {"op": "common", "changes": {"handleByStorey": {"upper": {"material": "Đồng thau"}}}})
        self.assertEqual(effective_handle(spec.common, spec.find("TT1")).material, "Đồng thau")
        self.assertEqual(effective_handle(spec.common, spec.find("TD1")).material, base.material)
        spec = edit.apply_op(spec, {"op": "update", "id": "TT1", "changes": {"handle": {"variant": "knob"}}})
        h = effective_handle(spec.common, spec.find("TT1"))
        self.assertEqual((h.variant, h.material), ("knob", "Đồng thau"), "fields merge level by level")
        self.assertEqual(effective_handle(spec.common, spec.find("TT3")).variant, base.variant)

    def test_default_spec_dump_has_no_new_keys_and_round_trips(self):
        spec = _spec()
        d = dump_spec(spec)
        self.assertNotIn("handleByStorey", d["common"])
        self.assertTrue(all("handle" not in m for m in d["module"]))
        spec = edit.apply_op(spec, {"op": "update", "id": "TD1", "changes": {"handle": {"material": "Inox"}}})
        again = load_spec(dump_spec(spec))
        self.assertEqual(effective_handle(again.common, again.find("TD1")).material, "Inox")

    def test_unknown_storey_rejected(self):
        with self.assertRaises(ValueError):
            edit.apply_op(_spec(), {"op": "common", "changes": {"handleByStorey": {"attic": {"variant": "none"}}}})


class TestGeometryAndExport(unittest.TestCase):
    def test_storey_override_changes_geometry(self):
        spec = _spec()
        before = _handles_by_storey(spec)
        spec = edit.apply_op(spec, {"op": "common", "changes": {"handleByStorey": {"upper": {"variant": "none"}}}})
        after = _handles_by_storey(spec)
        self.assertNotIn("upper", after)
        self.assertEqual(after["base"], before["base"])
        self.assertEqual(after["loft"], before["loft"], "loft is its own storey")

    def test_threejs_uses_module_handle_material(self):
        import jsonschema
        spec = edit.apply_op(_spec(), {"op": "update", "id": "TD1", "changes": {"handle": {"material": "Đồng thau"}}})
        doc = threejs_export.export(spec, "thu", 1)
        for f in ("kitchen-threejs.v1.0.0.schema.json", "kitchen-threejs.schema.json"):
            v = jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / f).read_text(encoding="utf-8")))
            self.assertEqual([e.message for e in v.iter_errors(doc)][:2], [])
        self.assertEqual(threejs_export.integrity(doc), [])
        found: dict[str, str] = {}

        def walk(x):
            if isinstance(x, dict):
                if "hardware" in x and isinstance(x["hardware"], dict) and x["hardware"].get("sourceRef"):
                    found[x["hardware"]["sourceRef"]] = x["hardware"]["materialId"]
                for y in x.values():
                    walk(y)
            elif isinstance(x, list):
                for y in x:
                    walk(y)
        walk(doc)
        td1 = {v for k, v in found.items() if k.startswith("TD1-handle")}
        self.assertEqual(td1, {"MAT-HANDLE-TD1"})
        self.assertEqual({v for k, v in found.items() if k.startswith("TT1-handle")}, {"MAT-HANDLE"})

    def test_handle_style_edit_resets_overrides(self):
        spec = edit.apply_op(_spec(), {"op": "common", "changes": {"handleByStorey": {"upper": {"variant": "none", "material": "Inox"}}}})
        spec = edit.apply_op(spec, {"op": "update", "id": "TD1", "changes": {"handle": {"length": 300}}})
        ops, _, _ = geometry_edit.build_ops(spec, [{"type": "handle", "variant": "knob"}])
        new = edit.apply_op(spec, edit.combine_ops(ops))
        self.assertEqual({effective_handle(new.common, m).variant for m in new.module}, {"knob"})
        self.assertEqual(effective_handle(new.common, new.find("TT1")).material, "Inox", "material overrides are kept")
        self.assertEqual(effective_handle(new.common, new.find("TD1")).length, new.common.handle.length)


class TestDesignOps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="handles-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        self.svc.images.ensure_render(self.did, None, VIEW, 640, 480)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self, layer, material="Đồng thau"):
        return self.svc.images.create(self.did, VIEW, layer, material=material, mode="design", backend="recolor")

    def test_catalogue_has_storey_and_parent(self):
        spec, _ = self.svc.store.get(self.did)
        cat = {x["id"]: x for x in __import__("kitchen.layers", fromlist=["x"]).catalogue(spec, geometry.compile_spec(spec))}
        h = cat["TD1-handle-1"]
        self.assertEqual((h["storey"], cat[h["parent"]]["type"]), ("base", "door"))

    def test_partial_module_selection_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self._job("TD1-handle-1")
        self.assertIn("TD1", str(cm.exception))

    def test_module_group_writes_module_override(self):
        j = self._job("handle:TD1")
        task = j["request"]["tasks"][0]
        self.assertEqual(set(task["targetParts"]), {"TD1-handle-1", "TD1-handle-2"})
        self.svc.images.accept(j["id"])
        spec, _ = self.svc.store.get(self.did)
        self.assertEqual(spec.find("TD1").handle.material, "Đồng thau")
        self.assertEqual(effective_handle(spec.common, spec.find("TD1")).material, "Đồng thau")
        self.assertEqual(effective_handle(spec.common, spec.find("TT1")).material, spec.common.handle.material)

    def test_all_handles_clears_lower_overrides(self):
        spec, rev = self.svc.store.get(self.did)
        self.svc.apply(self.did, {"op": "update", "id": "TD1", "changes": {"handle": {"material": "Inox"}}}, rev, "test")
        j = self._job("type:handle", "Đồng thau")
        self.assertEqual(len(j["request"]["tasks"][0]["targetParts"]), 22)
        self.svc.images.accept(j["id"])
        spec, _ = self.svc.store.get(self.did)
        self.assertEqual(spec.common.handle.material, "Đồng thau")
        self.assertIsNone(spec.find("TD1").handle)
        self.assertEqual({effective_handle(spec.common, m).material for m in spec.module}, {"Đồng thau"})

    def test_whole_storey_uses_storey_override(self):
        spec, _ = self.svc.store.get(self.did)
        scene = geometry.compile_spec(spec)
        by = _handles_by_storey(spec)
        op, scope = handles.material_ops(spec, scene, by["upper"], "Đồng thau")
        new = edit.apply_op(spec, op)
        self.assertEqual(new.common.handleByStorey["upper"].material, "Đồng thau")
        self.assertIn("upper", scope)
        for m in new.module:
            want = "Đồng thau" if m.storey == "upper" else spec.common.handle.material
            self.assertEqual(effective_handle(new.common, m).material, want, m.id)
        self.assertEqual(new.common.handle.material, spec.common.handle.material)


if __name__ == "__main__":
    unittest.main()


class TestMultiSelect(unittest.TestCase):
    """Tier groups and ad-hoc `parts:` layers used by Ctrl/Shift selection in the image editor."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="multisel-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(json.loads(FIX.read_text(encoding="utf-8")))["id"]
        self.svc.images.ensure_render(self.did, None, VIEW, 640, 480)
        from kitchen import layers
        spec, _ = self.svc.store.get(self.did)
        self.spec, self.layers = spec, layers
        self.scene = geometry.compile_spec(spec)
        self.cat = {x["id"]: x for x in layers.catalogue(spec, self.scene)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tier_groups(self):
        by = _handles_by_storey(self.spec)
        n_base, n_upper = len(by.get("base", [])), len(by.get("upper", [])) + len(by.get("loft", []))
        self.assertEqual(len(self.cat["tier:base:handle"]["component"]), n_base)
        self.assertEqual(len(self.cat["tier:upper:handle"]["component"]), n_upper)
        doors = self.cat["tier:upper:door"]["component"]
        self.assertTrue(all(self.cat[i]["type"] in ("door", "glass-door") for i in doors))

    def test_parts_layer(self):
        cat = list(self.cat.values())
        _, ids = self.layers.resolve(cat, "parts:TD1-handle-1,TD1-handle-2")
        self.assertEqual(ids, ["TD1-handle-1", "TD1-handle-2"])
        with self.assertRaises(ValueError):
            self.layers.resolve(cat, "parts:TD1-handle-1,TD1-door-1")
        with self.assertRaises(KeyError):
            self.layers.resolve(cat, "parts:nope-1")

    def test_quick_job_many_handles_is_one_task(self):
        ids = self.cat["type:handle"]["component"]
        j = self.svc.images.create(self.did, VIEW, "parts:" + ",".join(ids), material="Đồng thau", mode="quick", backend="recolor")
        tasks = j["request"]["tasks"]
        self.assertEqual((len(tasks), len(tasks[0]["targetParts"])), (1, len(ids)))

    def test_design_mode_parts_equal_module_group(self):
        j = self.svc.images.create(self.did, VIEW, "parts:TD1-handle-1,TD1-handle-2", material="Đồng thau", mode="design", backend="recolor")
        self.assertIn("TD1", json.dumps(j["request"], ensure_ascii=False))
        self.svc.images.accept(j["id"])
        spec, _ = self.svc.store.get(self.did)
        self.assertEqual(spec.find("TD1").handle.material, "Đồng thau")

    def test_pick_radius_finds_handle_nearby(self):
        from kitchen import imaging
        d = self.svc.images.ensure_render(self.did, None, VIEW)[3]
        hid = "TD1-handle-1"
        spot = next(((x, y) for y in range(0, 480) for x in range(0, 640) if (q := imaging.pick(d, x, y, 0)) and q["id"] == hid), None)
        self.assertIsNotNone(spot, "tay nắm phải hiện trong ảnh")
        x, y = spot
        for dx in (-3, 3):  # bấm lệch vài điểm ảnh vẫn trúng tay nắm
            self.assertEqual(imaging.pick(d, x + dx, y, 5)["id"], hid)
        self.assertIn(hid, self.svc.images.pick(self.did, VIEW, x + 3, y, radius=5)["layers"])


class TestSelectionJs(unittest.TestCase):
    def test_helpers(self):
        import shutil as sh
        import subprocess
        node = sh.which("node")
        if not node:
            self.skipTest("không có Node.js")
        script = r"""
const m = await import(process.argv[1]);
const L = [
 {id:'D1',variant:'part',type:'door',storey:'base'},{id:'H1',variant:'part',type:'handle',storey:'base',parent:'D1'},
 {id:'D2',variant:'part',type:'drawer',storey:'base'},{id:'H2',variant:'part',type:'handle',storey:'base',parent:'D2'},
 {id:'U1',variant:'part',type:'glass-door',storey:'loft'},{id:'UH',variant:'part',type:'handle',storey:'loft',parent:'U1'},
 {id:'N1',variant:'part',type:'door',storey:'base'},
 {id:'grp',variant:'group',type:'handle',component:['H1','H2']}];
const P = m.partIndex(L); const out = {};
out.shift = [m.shiftGroupId(P.get('H1')), m.shiftGroupId(P.get('U1')), m.shiftGroupId(P.get('UH')), m.shiftGroupId(P.get('D2'))];
out.ctrlSame = m.ctrlIds('handle', P.get('H2'), L);
out.ctrlDoor = m.ctrlIds('handle', P.get('D1'), L);
out.ctrlNoHandle = m.ctrlIds('handle', P.get('N1'), L);
out.ctrlHandleForDoor = m.ctrlIds('door', P.get('H1'), L);
out.ctrlMixed = m.ctrlIds('door', P.get('D2'), L);
out.toggle = [m.toggleIds(['a'], ['b','c']), m.toggleIds(['a','b'], ['b'])];
out.layerFor = [m.layerIdFor(['H2','H1'], L), m.layerIdFor(['H1'], L)];
out.part = m.partitionByType(['D1','H1','N1','H2'], P).map(g => g.join());
out.target = [m.targetFor(['H1']), m.targetFor(['H1','H2'])];
out.label = m.targetLabel('parts:H1,H2', L);
console.log(JSON.stringify(out));
"""
        out = subprocess.run([node, "--input-type=module", "-e", script, (ROOT / "web" / "selection.js").as_uri()], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        o = json.loads(out.stdout)
        self.assertEqual(o["shift"], ["tier:base:handle", "tier:upper:door", "tier:upper:handle", "tier:base:drawer"])
        self.assertEqual(o["ctrlSame"], {"ids": ["H2"]})
        self.assertEqual(o["ctrlDoor"], {"ids": ["H1"]})
        self.assertIn("error", o["ctrlNoHandle"])
        self.assertEqual(o["ctrlHandleForDoor"], {"ids": ["D1"]})
        self.assertIn("error", o["ctrlMixed"])
        self.assertEqual(o["toggle"], [["a", "b", "c"], ["a"]])
        self.assertEqual(o["layerFor"], ["grp", "H1"])
        self.assertEqual(o["part"], ["D1,N1", "H1,H2"])
        self.assertEqual(o["target"], ["H1", "parts:H1,H2"])
        self.assertEqual(o["label"], "2 × tay nắm")
