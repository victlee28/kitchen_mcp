"""service.interpret: a sentence becomes a previewed operation; nothing is saved until apply(expect=opHash)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen.service import KitchenService  # noqa: E402
from kitchen.store import ConflictError  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))


class TestInterpret(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="interpret-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]
        self.spec, self.rev = self.svc.store.get(self.did)
        self.first = next(m for m in self.spec.module if m.storey == "base" and m.wall == "back")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ok_returns_proposal_and_saves_nothing(self):
        r = self.svc.interpret(self.did, f"xóa tủ {self.first.id}")
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(r["proposal"]["baseRev"], self.rev)
        self.assertEqual(len(self.svc.history(self.did)), 1)

    def test_confirm_with_op_hash(self):
        r = self.svc.interpret(self.did, f"{self.first.id} rộng 700")
        out = self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        self.assertEqual(out["revision"] if "revision" in out else self.svc.store.get(self.did)[1], self.rev + 1)
        self.assertEqual(self.svc.store.get(self.did)[0].find(self.first.id).width, 700)

    def test_selection_is_the_target_and_scope(self):
        r = self.svc.interpret(self.did, "đổi cánh kính", scope=[self.first.id])
        self.assertEqual(r["operation"]["id"], self.first.id)
        self.assertEqual(r["proposal"]["outsideScope"], [])

    def test_clarify_has_no_proposal(self):
        r = self.svc.interpret(self.did, "xóa tủ")
        self.assertEqual(r["status"], "clarify")
        self.assertNotIn("proposal", r)

    def test_stale_revision_is_refused(self):
        with self.assertRaises(ConflictError):
            self.svc.interpret(self.did, f"xóa {self.first.id}", base_revision=self.rev + 5)

    def test_llm_is_off_unless_asked_and_keyless_is_skipped(self):
        r = self.svc.interpret(self.did, "hôm nay trời đẹp")
        self.assertEqual(r["status"], "unsupported")
        self.assertNotIn("llm", r)
        r = self.svc.interpret(self.did, "hôm nay trời đẹp", use_llm=True)
        self.assertEqual(r["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
