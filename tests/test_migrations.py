"""Versioned DB migrations: fresh, upgrade with a backup, a failing step rolls back, a newer database is refused."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import migrations  # noqa: E402
from kitchen.store import Store  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))


def _version(path):
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def _tables(path):
    c = sqlite3.connect(path)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def _old_db(path, user_version):
    """A database as an earlier release left it: baseline tables without the jurisdiction columns, a design inside."""
    c = sqlite3.connect(path)
    c.executescript(migrations.BASELINE)
    c.execute("INSERT INTO designs(id, name) VALUES('d1', 'Bep cu')")
    c.execute("INSERT INTO revisions(design_id, rev, spec_json, operation) VALUES('d1', 1, '{}', 'create')")
    c.execute(f"PRAGMA user_version = {user_version}")
    c.commit()
    c.close()


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="mig-"))
        self.db = self.dir / "k.db"

    def backups(self):
        return sorted(self.dir.glob("k.db.bak-*"))

    def test_a_new_database_is_created_at_the_latest_version_without_a_backup(self):
        st = Store(self.db)
        self.assertEqual(st.migration["to"], migrations.LATEST)
        self.assertEqual(st.migration["applied"], [s.name for s in migrations.STEPS])
        self.assertIsNone(st.migration["backup"])
        self.assertEqual(_version(self.db), migrations.LATEST)
        self.assertTrue({"designs", "revisions", "image_jobs", "knowledge", "floorplans"} <= _tables(self.db))
        self.assertEqual(self.backups(), [])

    def test_opening_again_does_nothing(self):
        Store(self.db)
        st = Store(self.db)
        self.assertEqual(st.migration["applied"], [])
        self.assertEqual(self.backups(), [])

    def test_an_older_database_is_upgraded_keeps_its_data_and_gets_a_backup(self):
        _old_db(self.db, 1)
        st = Store(self.db)
        self.assertEqual(st.migration["from"], 1)
        self.assertEqual(st.migration["applied"], ["baseline-tables", "knowledge-jurisdiction"])
        self.assertEqual(_version(self.db), migrations.LATEST)
        c = sqlite3.connect(self.db)
        self.assertIn("region", {r[1] for r in c.execute("PRAGMA table_info(knowledge)")})
        self.assertEqual(c.execute("SELECT name FROM designs").fetchall(), [("Bep cu",)])
        c.close()
        (bak,) = self.backups()
        self.assertEqual(st.migration["backup"], str(bak))
        self.assertEqual(_version(bak), 1)
        c = sqlite3.connect(bak)
        self.assertNotIn("region", {r[1] for r in c.execute("PRAGMA table_info(knowledge)")}, "the copy is the state before migrating")
        self.assertEqual(c.execute("SELECT count(*) FROM revisions").fetchone()[0], 1)
        c.close()

    def test_a_failing_step_rolls_back_and_leaves_the_version_alone(self):
        _old_db(self.db, 1)
        Store(self.db)                                                 # now at LATEST
        n = migrations.LATEST

        def add_column_then_fail(conn):
            conn.execute("ALTER TABLE designs ADD COLUMN note TEXT")
            raise RuntimeError("boom")
        steps = migrations.STEPS + [migrations.Step(n + 1, "bad", add_column_then_fail)]
        conn = sqlite3.connect(self.db)
        with self.assertRaises(migrations.MigrationError) as cm:
            migrations.run(conn, self.db, steps)
        conn.close()
        self.assertIn("bad", str(cm.exception))
        self.assertEqual(_version(self.db), n)
        c = sqlite3.connect(self.db)
        self.assertNotIn("note", {r[1] for r in c.execute("PRAGMA table_info(designs)")}, "the half-applied change was rolled back")
        c.close()
        self.assertEqual(len(self.backups()), 2, "one from the upgrade, one before the failed run")

    def test_a_later_step_applies_after_the_earlier_ones(self):
        Store(self.db)
        n = migrations.LATEST
        steps = migrations.STEPS + [migrations.Step(n + 1, "note", lambda c: c.execute("ALTER TABLE designs ADD COLUMN note TEXT"))]
        conn = sqlite3.connect(self.db)
        out = migrations.run(conn, self.db, steps)
        conn.close()
        self.assertEqual((out["from"], out["to"], out["applied"]), (n, n + 1, ["note"]))
        self.assertEqual(_version(self.db), n + 1)

    def test_a_database_from_a_newer_release_is_refused_untouched(self):
        Store(self.db)
        c = sqlite3.connect(self.db)
        c.execute("PRAGMA user_version = 99")
        c.commit()
        c.close()
        with self.assertRaises(migrations.MigrationError):
            Store(self.db)
        self.assertEqual(_version(self.db), 99)
        self.assertEqual(self.backups(), [])

    def test_steps_are_numbered_without_gaps(self):
        self.assertEqual([s.version for s in migrations.STEPS], list(range(1, migrations.LATEST + 1)))


if __name__ == "__main__":
    unittest.main()
