"""Schema 1.5: runs[] groups, runId / localTransform per module, and the browser loader builds the same world positions with or without them."""
import copy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import threejs_export  # noqa: E402
from kitchen.spec import Opening  # noqa: E402
from test_run_invariants import _run_spec, _spec  # noqa: E402

SCHEMA = json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))


class TestRunExport(unittest.TestCase):
    def test_runs_are_exported_and_valid(self):
        for yaw in (0, 30, 120, 270):
            with self.subTest(yaw=yaw):
                doc = threejs_export.export(_run_spec(yaw))
                self.assertEqual(doc["schemaVersion"], "1.7.0")
                jsonschema.Draft202012Validator(SCHEMA).validate(doc)
                self.assertEqual(threejs_export.integrity(doc), [])
                self.assertEqual([r["id"] for r in doc["runs"]], ["RUN-R1", "RUN-R2", "RUN-R3"], "the free run, then the back and right walls' runs")
                run = doc["runs"][0]
                self.assertEqual(run["modules"], ["MOD-TD91", "MOD-TU93", "MOD-TD92"])
                self.assertAlmostEqual(run["transform"]["rotation"]["y"], yaw if yaw <= 180 else yaw, delta=1e-3)
                for mod in doc["modules"]:
                    if mod["sourceRef"] in ("TD91", "TD92", "TU93"):
                        self.assertEqual(mod["placement"]["runId"], "RUN-R1")
                    else:
                        self.assertIn(mod["placement"]["runId"], ("RUN-R2", "RUN-R3"))
                    self.assertIn("localTransform", mod)

    def test_every_cabinet_stands_in_a_run(self):
        from test_run_invariants import _spec
        doc = threejs_export.export(_spec(extra=False))
        self.assertTrue(doc["runs"])
        self.assertTrue(all(m["placement"].get("runId") for m in doc["modules"]))

    def test_authored_door_is_exported_and_rendered(self):
        spec = _spec(extra=False)
        spec.openings = [Opening.model_validate({
            "id": "OP1", "kind": "door", "openingType": "door-swing-1", "wallAxis": {"id": "back"}, "center": 524, "width": 748,
            "height": 2100, "sill": 0, "source": "human",
            "leaves": [{"cols": [0, 1], "rows": [0, 1], "operation": "swing", "hinge": {"axis": "v", "index": 0}, "side": "-", "active": True}],
        })]
        doc = threejs_export.export(spec)
        jsonschema.Draft202012Validator(SCHEMA).validate(doc)
        wall = next(item for item in doc["room"]["walls"] if item["id"] == "WALL-BACK")
        door = next(item for item in wall["openings"] if item["id"] == "OP1")
        self.assertEqual((door["width"], door["offset"]), (748, 100))           # 524 - 374 - 50 (half the right wall) from the corner
        self.assertTrue(all(b["z0"] < b["z1"] for b in door["frame"] + door["leaves"]))

        node = shutil.which("node")
        if not node:
            self.skipTest("no Node.js")
        script = ("const THREE = await import(process.argv[1]); const L = await import(process.argv[2]);"
                  "const d = JSON.parse((await import('node:fs')).readFileSync(0, 'utf8'));"
                  "const k = L.buildKitchen(d, THREE, {edges: false});"
                  "const door = k.root.getObjectByName('OP1');"
                  "console.log(JSON.stringify({found: !!door, meshes: door?.children.filter(x => x.isMesh).length || 0}));")
        three = ROOT / "web" / "vendor" / "three" / "build" / "three.module.js"
        if not three.exists():
            three = ROOT / "web" / "vendor" / "three" / "build" / "three.module.min.js"
        out = subprocess.run([node, "--input-type=module", "-e", script, three.as_uri(), (ROOT / "web" / "scene-loader.js").as_uri()],
                             input=json.dumps(doc), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        rendered = json.loads(out.stdout)
        self.assertTrue(rendered["found"])
        self.assertEqual(rendered["meshes"], len(door["frame"]) + len(door["leaves"]))

    def test_countertop_names_its_run(self):
        doc = threejs_export.export(_run_spec(30))
        tops = [a for a in doc["accessories"] if a["type"] == "Countertop" and a["partRef"].get("run") == "R1"]
        self.assertEqual(len(tops), 1)
        self.assertAlmostEqual(tops[0]["transform"]["rotation"]["y"], 30, delta=1e-3)

    def test_loader_world_positions_agree_with_and_without_groups(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("no Node.js")
        doc = threejs_export.export(_run_spec(120))
        flat = copy.deepcopy(doc)
        flat.pop("runs")
        for m in flat["modules"]:
            m["placement"].pop("runId", None)
            m.pop("localTransform", None)
        script = ("const THREE = await import(process.argv[1]); const L = await import(process.argv[2]); const docs = JSON.parse((await import('node:fs')).readFileSync(0, 'utf8'));"
                  "const out = docs.map(d => { const k = L.buildKitchen(d, THREE, {edges: false}); k.root.updateMatrixWorld(true);"
                  "  const r = {}; for (const [id, g] of k.byModule) { const p = new THREE.Vector3(); g.getWorldPosition(p);"
                  "    const q = new THREE.Quaternion(); g.getWorldQuaternion(q); const e = new THREE.Euler().setFromQuaternion(q, 'YXZ');"
                  "    r[id] = [p.x, p.y, p.z, e.y]; } return r; });"
                  "console.log(JSON.stringify(out));")
        three = (ROOT / "web" / "vendor" / "three" / "build" / "three.module.js")
        if not three.exists():
            three = ROOT / "web" / "vendor" / "three" / "build" / "three.module.min.js"
        out = subprocess.run([node, "--input-type=module", "-e", script, three.as_uri(), (ROOT / "web" / "scene-loader.js").as_uri()],
                             input=json.dumps([doc, flat]), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        grouped, plain = json.loads(out.stdout)
        self.assertEqual(sorted(grouped), sorted(plain))
        self.assertIn("TD91", grouped)
        for key in grouped:
            for a, b in zip(grouped[key], plain[key]):
                self.assertAlmostEqual(a, b, delta=2e-4, msg=key)


if __name__ == "__main__":
    unittest.main()
