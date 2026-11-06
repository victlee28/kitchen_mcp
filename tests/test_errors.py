"""Typed errors (R14): kind and code are stable, builtin compatibility holds, the HTTP adapter maps kind to status in one place."""
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

import web_server  # noqa: E402
from kitchen import errors  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.store import ConflictError  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))


class TestErrorTypes(unittest.TestCase):
    def test_kinds_codes_and_messages(self):
        cases = [(errors.InvalidInput("m"), "validation", "invalid-input", 400), (errors.Conflict("m"), "conflict", "conflict", 409),
                 (errors.NotFound("m"), "not-found", "not-found", 404), (errors.Unsupported("m"), "unsupported", "unsupported", 400),
                 (errors.Infrastructure("m"), "infrastructure", "infrastructure", 502)]
        for e, kind, code, status in cases:
            self.assertEqual((e.kind, e.code, errors.kind_of(e), errors.http_status(e)), (kind, code, kind, status))
            self.assertEqual(e.to_dict(), {"kind": kind, "code": code, "message": "m"})
        self.assertEqual(set(errors.KINDS), {c[1] for c in cases})
        self.assertEqual(errors.NotFound("m", code="design-not-found").code, "design-not-found")

    def test_str_has_no_keyerror_quotes_and_builtins_still_catch(self):
        e = errors.NotFound("Design 'x' was not found")
        self.assertEqual(str(e), "Design 'x' was not found")
        with self.assertRaises(KeyError):
            raise e
        with self.assertRaises(ValueError):
            raise errors.InvalidInput("bad")
        with self.assertRaises(ValueError):
            raise errors.Unsupported("no")

    def test_builtins_the_core_still_raises_are_classified_and_unknowns_are_not(self):
        self.assertEqual(errors.kind_of(KeyError("k")), "not-found")
        self.assertEqual(errors.kind_of(FileNotFoundError("f")), "not-found")
        self.assertEqual(errors.kind_of(ValueError("v")), "validation")
        self.assertIsNone(errors.kind_of(RuntimeError("bug")))
        self.assertIsNone(errors.http_status(ZeroDivisionError()))

    def test_store_conflict_is_a_conflict_with_its_own_code(self):
        e = ConflictError("stale")
        self.assertIsInstance(e, errors.Conflict)
        self.assertEqual((e.kind, e.code), ("conflict", "revision-conflict"))


class TestErrorsEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="err-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "r")
        self.did = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]
        self.srv = web_server.make_server(0, self.svc)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Host": f"localhost:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        return r.status, data

    def test_service_raises_typed_errors_with_stable_codes(self):
        with self.assertRaises(errors.NotFound) as cm:
            self.svc.store.get("no-such-design")
        self.assertEqual(cm.exception.code, "design-not-found")
        rev = self.svc.store.get(self.did)[1]
        mid = self.svc.store.get(self.did)[0].module[0].id
        op = {"op": "update", "id": mid, "changes": {"material": "A"}}
        self.svc.apply(self.did, op, rev, "t")
        with self.assertRaises(errors.Conflict) as cm:
            self.svc.apply(self.did, op, rev, "t")                                # rev is now stale
        self.assertEqual(cm.exception.code, "revision-conflict")
        with self.assertRaises(errors.InvalidInput) as cm:
            self.svc.apply(self.did, op, rev + 1, "t", "0" * 16)
        self.assertEqual(cm.exception.code, "operation-differs-from-preview")
        with self.assertRaises(errors.NotFound) as cm:
            self.svc.apply(self.did, {"op": "update", "id": "NOPE", "changes": {}}, rev + 1, "t")
        self.assertEqual(cm.exception.code, "module-not-found")

    def test_http_maps_kind_to_status_and_returns_the_code(self):
        st, body = self.call("GET", "/api/designs/no-such-design")
        self.assertEqual((st, body["code"]), (404, "design-not-found"))
        st, body = self.call("POST", f"/api/designs/{self.did}/ops", {"baseRev": 999, "op": {"op": "common", "changes": {}}})
        self.assertEqual((st, body["code"]), (409, "revision-conflict"))
        st, body = self.call("POST", f"/api/designs/{self.did}/ops", {"baseRev": self.svc.store.get(self.did)[1], "op": {"op": "common", "changes": {}}, "expect": "0" * 16})
        self.assertEqual((st, body["code"]), (400, "operation-differs-from-preview"))
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
