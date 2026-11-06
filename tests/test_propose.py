"""Previewing a design operation: nothing is saved, the diff and the validation delta are right, stale and bad requests are refused."""
import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import proposal  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.store import ConflictError  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
NEW = "Laminate xanh rêu mờ"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="propose-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]
        self.spec, self.rev = self.svc.store.get(self.did)
        self.first = next(m for m in self.spec.module if m.storey == "base" and m.wall == "back")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def revisions(self):
        return len(self.svc.history(self.did))


class TestPropose(Base):
    def test_a_preview_saves_nothing(self):
        before = self.revisions()
        p = self.svc.propose(self.did, {"op": "update", "id": self.first.id, "changes": {"material": NEW}}, self.rev)
        self.assertTrue(p["applicable"])
        self.assertEqual((self.revisions(), self.svc.store.get(self.did)[1]), (before, self.rev))
        self.assertEqual(p["baseRev"], self.rev)

    def test_material_change_lists_only_that_module(self):
        p = self.svc.propose(self.did, {"op": "update", "id": self.first.id, "changes": {"material": NEW}}, self.rev, scope=[self.first.id])
        self.assertEqual(p["affectedModules"], [self.first.id])
        self.assertEqual(p["outsideScope"], [])
        self.assertEqual(p["diff"]["modules"]["changed"][self.first.id], [{"field": "material", "old": self.first.material, "new": NEW}])
        self.assertEqual(p["diff"]["other"], [])
        self.assertFalse(p["unchanged"])
        self.assertFalse(p["validation"]["introducesErrors"])

    def test_removing_with_closed_gap_moves_neighbours_and_reports_them_outside_scope(self):
        p = self.svc.propose(self.did, {"op": "remove", "id": self.first.id, "closeGap": True}, self.rev, scope=[self.first.id])
        self.assertEqual(p["diff"]["modules"]["removed"], [self.first.id])
        self.assertEqual(p["moduleCount"], {"before": len(self.spec.module), "after": len(self.spec.module) - 1})
        self.assertTrue(p["outsideScope"], "neighbours slide when the gap closes")
        self.assertTrue(all(any(c["field"] == "fromCorner" for c in p["diff"]["modules"]["changed"][m]) for m in p["outsideScope"]
                            if m in p["diff"]["modules"]["changed"]))
        kept = self.svc.propose(self.did, {"op": "remove", "id": self.first.id, "closeGap": False}, self.rev, scope=[self.first.id])
        self.assertEqual(kept["outsideScope"], [], "without closing the gap only the target changes")

    def test_a_common_change_is_reported_under_other(self):
        p = self.svc.propose(self.did, {"op": "common", "changes": {"material": {**self.spec.common.material, "base": NEW}}}, self.rev)
        self.assertTrue(any(e["path"] == "common.material.base" and e["new"] == NEW for e in p["diff"]["other"]))

    def test_an_operation_that_changes_nothing_is_flagged(self):
        p = self.svc.propose(self.did, {"op": "update", "id": self.first.id, "changes": {"material": self.first.material}}, self.rev)
        self.assertTrue(p["unchanged"])

    def test_validation_delta_lists_new_errors(self):
        long_ = self.first.width + 5000
        p = self.svc.propose(self.did, {"op": "update", "id": self.first.id, "changes": {"width": long_}, "closeGap": False}, self.rev)
        self.assertTrue(p["applicable"])
        self.assertTrue(p["validation"]["introduced"])
        self.assertTrue(p["validation"]["introducesErrors"])
        self.assertEqual(self.svc.store.get(self.did)[1], self.rev, "a failing preview still saves nothing")

    def test_stale_base_revision_is_a_conflict(self):
        self.svc.apply(self.did, {"op": "update", "id": self.first.id, "changes": {"material": NEW}}, self.rev, "test")
        with self.assertRaises(ConflictError):
            self.svc.propose(self.did, {"op": "remove", "id": self.first.id}, self.rev)
        again = self.svc.propose(self.did, {"op": "remove", "id": self.first.id}, None)
        self.assertEqual(again["baseRev"], self.rev + 1)

    def test_unsupported_or_wrong_operations_are_reported_not_raised(self):
        for op in ({"op": "update", "id": "NOPE", "changes": {}}, {"op": "teleport"}, {"op": "update", "id": self.first.id, "changes": {"width": "wide"}}):
            p = self.svc.propose(self.did, op, self.rev)
            self.assertFalse(p["applicable"], op)
            self.assertTrue(p["error"]["message"], op)
        with self.assertRaises(KeyError):
            self.svc.propose("missing-design", {"op": "remove", "id": "x"})

    def test_confirming_the_proposed_op_gives_the_previewed_result(self):
        op = {"op": "update", "id": self.first.id, "changes": {"material": NEW}}
        p = self.svc.propose(self.did, op, self.rev)
        done = self.svc.apply(self.did, p["operation"], p["baseRev"], "web")
        self.assertEqual(done["rev"], self.rev + 1)
        self.assertEqual(self.svc.store.get(self.did)[0].find(self.first.id).material, NEW)
        self.assertEqual(self.svc.propose(self.did, op, done["rev"])["unchanged"], True)


class TestDiffUnits(unittest.TestCase):
    def test_validation_delta_matches_issues_by_rule_module_and_text(self):
        e = {"rule": "R", "severity": "error", "module": ["A"], "content": "x"}
        w = {"rule": "S", "severity": "warning", "module": [], "content": "y"}
        d = proposal.validation_delta({"valid": True, "issues": [w]}, {"valid": False, "issues": [e]})
        self.assertEqual((d["introduced"], d["resolved"], d["introducesErrors"]), ([e], [w], True))


class TestProposeHttp(Base):
    def setUp(self):
        super().setUp()
        import web_server
        self.srv = web_server.make_server(0, self.svc)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def post(self, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("POST", f"/api/designs/{self.did}/propose", body=json.dumps(body), headers={"Host": f"localhost:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        return r.status, data

    def test_route(self):
        op = {"op": "update", "id": self.first.id, "changes": {"material": NEW}}
        st, d = self.post({"op": op, "baseRev": self.rev, "scope": [self.first.id]})
        self.assertEqual((st, d["applicable"], d["affectedModules"]), (200, True, [self.first.id]))
        self.assertEqual(self.revisions(), 1)
        self.assertEqual(self.post({"op": op, "baseRev": self.rev + 7})[0], 409)
        self.assertEqual(self.post({"baseRev": self.rev})[0], 400)
        self.assertEqual(self.post({"op": op, "scope": "TD1"})[0], 400)
        st, d = self.post({"op": {"op": "remove", "id": "NOPE"}, "baseRev": self.rev})
        self.assertEqual((st, d["applicable"]), (200, False))


if __name__ == "__main__":
    unittest.main()
