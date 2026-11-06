"""Two processes share one database: a live process's running jobs are not declared dead by the other, a dead one's are."""
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen.service import KitchenService  # noqa: E402
from kitchen.store import Store  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))


def _job(did, jid, status="running"):
    return {"id": jid, "design_id": did, "rev": 1, "view": "perspective", "render_key": "k", "kind": "material", "mode": "quick", "target": None,
            "backend": "recolor", "status": status, "request": {}}


class TestJobOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="own-"))
        self.db = self.tmp / "k.db"
        self.a = KitchenService(self.db, self.tmp / "r")
        self.did = self.a.create_from_spec(json.loads(json.dumps(FIX)))["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self, jid):
        c = sqlite3.connect(self.db)
        try:
            return c.execute("SELECT status, owner, heartbeat_at FROM image_jobs WHERE id=?", (jid,)).fetchone()
        finally:
            c.close()

    def test_a_running_job_records_its_owner_and_a_fresh_heartbeat(self):
        self.a.store.create_job(_job(self.did, "j1"))
        st, owner, beat = self.raw("j1")
        self.assertEqual((st, owner), ("running", self.a.store.owner))
        self.assertLess(time.time() - beat, 5)
        self.a.store.create_job(_job(self.did, "j2", "awaiting-send"))
        self.assertEqual(self.raw("j2")[1:], (None, None))
        self.a.store.update_job("j2", "running")
        self.assertEqual(self.raw("j2")[1], self.a.store.owner)

    def test_a_second_process_starting_does_not_interrupt_live_jobs(self):
        self.a.store.create_job(_job(self.did, "j1"))
        b = KitchenService(self.db, self.tmp / "r")             # opens the same database, as the web server and the MCP server do
        self.assertNotEqual(b.store.owner, self.a.store.owner)
        self.assertEqual(b.images.get("j1")["status"], "running")
        self.assertEqual([j["status"] for j in b.images.list(self.did)], ["running"])

    def test_a_silent_owner_is_declared_dead_by_the_other_process(self):
        self.a.store.create_job(_job(self.did, "j1"))
        c = sqlite3.connect(self.db)
        c.execute("UPDATE image_jobs SET heartbeat_at=? WHERE id='j1'", (time.time() - 3600,))
        c.commit()
        c.close()
        b = KitchenService(self.db, self.tmp / "r")             # starting b already reaps it
        job = b.images.get("j1")
        self.assertEqual(job["status"], "error:interrupted")
        self.assertIn("stopped", job["error"])

    def test_jobs_from_before_the_upgrade_have_no_heartbeat_and_count_as_dead(self):
        self.a.store.create_job(_job(self.did, "j1"))
        c = sqlite3.connect(self.db)
        c.execute("UPDATE image_jobs SET owner=NULL, heartbeat_at=NULL WHERE id='j1'")
        c.commit()
        c.close()
        self.assertEqual(self.a.store.mark_stale_jobs(), 1)

    def test_the_heartbeat_keeps_a_long_job_alive_and_stops_when_it_ends(self):
        Store.HEARTBEAT_S, Store.STALE_AFTER_S = 0.05, 0.4
        self.addCleanup(lambda: (setattr(Store, "HEARTBEAT_S", 10.0), setattr(Store, "STALE_AFTER_S", 45.0)))
        self.a.store.create_job(_job(self.did, "j1"))
        time.sleep(1.0)                                         # more than twice the stale limit
        self.assertEqual(self.a.store.mark_stale_jobs(), 0)
        self.assertEqual(self.raw("j1")[0], "running")
        self.a.store.update_job("j1", "needs-review")
        time.sleep(0.4)
        self.assertIsNone(self.a.store._beat, "no running jobs left: the heartbeat thread ended")
        self.a.store.update_job("j1", "running")                # a later job starts it again
        self.assertIsNotNone(self.a.store._beat)


if __name__ == "__main__":
    unittest.main()
