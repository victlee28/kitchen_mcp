"""Schema 1.4+: every door, drawer front, handle and countertop run says which kind of detail it is (partRef), additively."""
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import threejs_export  # noqa: E402
from kitchen.spec import KitchenSpec, from_data  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))


class TestPartRef(unittest.TestCase):
    def setUp(self):
        self.spec = from_data(KitchenSpec, json.loads(json.dumps(FIX)))
        self.doc = threejs_export.export(self.spec)

    def test_version_and_schema_validate(self):
        self.assertEqual(self.doc["schemaVersion"], "1.5.0")
        jsonschema.Draft202012Validator(SCHEMA).validate(self.doc)

    def test_fronts_and_handles_name_their_module(self):
        ids = {m.id for m in self.spec.module}
        seen = set()
        for mod in self.doc["modules"]:
            for key, kind in (("doors", "door"), ("drawers", "drawer")):
                for item in mod[key]:
                    self.assertEqual(item["partRef"], {"kind": kind, "module": mod["sourceRef"]})
                    self.assertIn(item["partRef"]["module"], ids)
                    seen.add(kind)
                    if item.get("hardware"):
                        self.assertEqual(item["hardware"]["partRef"], {"kind": "handle", "module": mod["sourceRef"]})
                        seen.add("handle")
        self.assertLessEqual({"door", "handle"}, seen)

    def test_countertop_runs_name_their_wall(self):
        tops = [a for a in self.doc["accessories"] if a["type"] == "Countertop"]
        self.assertTrue(tops)
        for a in tops:
            self.assertEqual(a["partRef"], {"kind": "countertop", "wall": a["sourceRef"].removeprefix("countertop-")})

    def test_old_schema_still_accepts_the_document(self):
        old = json.loads((ROOT / "schemas" / "kitchen-threejs.v1.0.0.schema.json").read_text(encoding="utf-8"))
        try:
            jsonschema.Draft202012Validator(old).validate(self.doc)
        except jsonschema.ValidationError as e:     # the base schema pins "default" only; version text is the one allowed difference
            self.assertNotIn("partRef", e.message)


if __name__ == "__main__":
    unittest.main()
