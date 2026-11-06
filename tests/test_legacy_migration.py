"""Migration of legacy Vietnamese-keyed data to the English schema."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kitchen import legacy, migrations
from kitchen.store import Store

ROOT = Path(__file__).resolve().parents[1]
OLD_SCHEMA = """
CREATE TABLE designs (id TEXT PRIMARY KEY, ten TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE revisions (design_id TEXT NOT NULL, rev INTEGER NOT NULL, spec_json TEXT NOT NULL,
  thao_tac TEXT NOT NULL, nguon TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (design_id, rev));
"""


class LegacyMigrationTest(unittest.TestCase):
    def test_convert_matches_current_fixture(self):
        old = json.loads((ROOT / "tests" / "data" / "legacy-bep-chu-L.json").read_text(encoding="utf-8"))
        new = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy.convert_spec(old), new)

    def test_convert_is_idempotent(self):
        new = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy.convert(new), new)

    def test_threejs_fixture_is_stable(self):
        data = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.threejs.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy.convert(data), data)

    def test_database_migration(self):
        old = json.loads((ROOT / "tests" / "data" / "legacy-bep-chu-L.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.executescript(OLD_SCHEMA)
            conn.execute("INSERT INTO designs(id, ten) VALUES('d1', 'Bếp L')")
            conn.execute("INSERT INTO revisions(design_id, rev, spec_json, thao_tac, nguon) VALUES('d1', 1, ?, ?, 'spec')",
                         (json.dumps(old, ensure_ascii=False), json.dumps({"op": "chung", "changes": {}})))
            conn.commit()
            conn.close()
            store = Store(path)
            with store._conn() as c:
                design_cols = [r[1] for r in c.execute("PRAGMA table_info(designs)")]
                revision_cols = [r[1] for r in c.execute("PRAGMA table_info(revisions)")]
                spec_json, operation = c.execute("SELECT spec_json, operation FROM revisions").fetchone()
                version = c.execute("PRAGMA user_version").fetchone()[0]
            self.assertIn("name", design_cols)
            self.assertNotIn("ten", design_cols)
            self.assertEqual(revision_cols[3:5], ["operation", "source"])
            self.assertEqual(json.loads(spec_json), legacy.convert_spec(old))
            self.assertEqual(json.loads(operation), {"op": "common", "changes": {}})
            self.assertEqual(version, migrations.LATEST)
            Store(path)  # second open is a no-op

    def test_renders_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            view = root / "d1" / "rev1" / "tuong-sau"
            view.mkdir(parents=True)
            (view / "camera.json").write_text(json.dumps({"id": "CAM-tuong-sau"}), encoding="utf-8")
            (view / "anh-1-anh-goc.png").write_bytes(b"x")
            legacy.migrate_renders(root)
            new_view = root / "d1" / "rev1" / "back-wall"
            self.assertTrue((new_view / "image-1-base-image.png").exists())
            self.assertEqual(json.loads((new_view / "camera.json").read_text(encoding="utf-8")), {"id": "CAM-back-wall"})
            self.assertEqual(legacy.migrate_renders(root), 0)


if __name__ == "__main__":
    unittest.main()
