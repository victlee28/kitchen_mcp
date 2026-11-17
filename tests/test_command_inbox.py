"""The command inbox: right-click sentences sent to Claude (``kitchen.menu_commands``, ``kitchen.command_inbox``), the service methods,
the HTTP routes and the MCP tools Claude answers them with."""
from __future__ import annotations

import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import menu_commands as mc  # noqa: E402
from kitchen.command_inbox import CommandInbox  # noqa: E402
from kitchen.errors import InvalidInput, NotFound  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

NOW = "2026-11-16T08:00:00Z"
CID = "20261116-150000-a1b2"


class TestRecords(unittest.TestCase):
    def test_a_new_command_keeps_only_what_the_menu_may_say(self):
        place = {"kind": "module", "id": "TD1", "part": "door", "point": {"x": -1500.123, "z": -50}, "module": "TD1",
                 "modules": ["TD1", "TD2", "../../x"], "title": "  Module TD1 ", "extra": "dropped", "structureId": "bad id!"}
        r = mc.new_record(CID, "d1", "  đổi cánh sang kính  ", place, 3, "vi", NOW)
        self.assertEqual(r, {"id": CID, "designId": "d1", "text": "đổi cánh sang kính", "baseRev": 3, "lang": "vi", "createdAt": NOW,
                             "status": "pending", "place": {"kind": "module", "part": "door", "id": "TD1", "module": "TD1",
                                                            "point": {"x": -1500.1, "z": -50.0}, "modules": ["TD1", "TD2"],
                                                            "title": "Module TD1"}})

    def test_picked_wall_faces_are_kept(self):
        r = mc.new_record(CID, "d1", "sơn vàng", {"kind": "structure", "id": "wall_011", "surfaces": ["wall_011#inside", "WALL-BACK#inside",
                                                                                                 "bad#", "x y#inside", 5]}, 9, "vi", NOW)
        self.assertEqual(r["place"]["surfaces"], ["wall_011#inside", "WALL-BACK#inside"])

    def test_bad_input_is_refused(self):
        for text, code in (("   ", "command-empty"), ("x" * 501, "command-too-long")):
            with self.assertRaises(InvalidInput) as e:
                mc.new_record(CID, "d1", text, {}, None, "vi", NOW)
            self.assertEqual(e.exception.code, code)
        for bad in ("../etc", "20261116-150000", 5):
            with self.assertRaises(InvalidInput):
                mc.clean_id(bad)
        self.assertEqual(mc.new_record(CID, "d1", "x", None, -1, "fr", NOW)["baseRev"], None)

    def test_answers(self):
        r = mc.new_record(CID, "d1", "xóa TD3", {}, 3, "vi", NOW)
        done = mc.answered(r, "done", " Đã xóa TD3 ", 4, NOW)
        self.assertEqual((done["status"], done["reply"], done["revision"]), ("done", "Đã xóa TD3", 4))
        with self.assertRaises(InvalidInput) as e:
            mc.answered(done, "done", "again", 5, NOW)
        self.assertEqual(e.exception.code, "command-closed")
        with self.assertRaises(InvalidInput):
            mc.answered(r, "dropped", "", None, NOW)               # only the user drops
        asked = mc.answered(r, "question", "Tủ nào?", None, NOW)
        self.assertEqual(mc.answered(asked, "done", "ok", 4, NOW)["status"], "done", "a question can still be answered")
        self.assertEqual(mc.dropped(r, NOW)["status"], "dropped")
        self.assertEqual(mc.dropped(done, NOW)["status"], "done", "an answered command stays as it was")

    def test_choices_and_the_revision_before(self):
        r = mc.new_record(CID, "d1", "tạo cửa đi 4 cánh", {}, 1, "vi", NOW)
        done = mc.answered(r, "done", "Đã lắp cửa trượt 4 cánh", 2, NOW, ["Cửa xếp 4 cánh", " Cửa xếp 4 cánh ", "", 7, "x" * 300], 1)
        self.assertEqual((done["choices"], done["fromRev"]), (["Cửa xếp 4 cánh", "x" * 160], 1))
        asked = mc.answered(r, "question", "Sâu bao nhiêu?", None, NOW, ["600 mm", "350 mm"], 1)
        self.assertEqual(asked["choices"], ["600 mm", "350 mm"])
        self.assertNotIn("fromRev", asked, "only a done change has a revision to go back to")
        self.assertNotIn("choices", mc.answered(r, "failed", "không", None, NOW))

    def test_a_reply_to_an_answer(self):
        asked = mc.answered(mc.new_record(CID, "d1", "tạo hệ tủ", {"kind": "structure", "id": "furniture_021"}, 3, "vi", NOW),
                            "question", "Sâu 600 hay 350?", None, NOW, ["600", "350"])
        reply = mc.new_record("20261116-150100-c3d4", "d1", "600", None, 3, "vi", NOW, asked)
        self.assertEqual(reply["replyTo"], CID)
        self.assertEqual(reply["context"], {"text": "tạo hệ tủ", "reply": "Sâu 600 hay 350?", "status": "question"})
        self.assertEqual(reply["place"], {"kind": "structure", "id": "furniture_021"}, "the answered command's place when none is given")
        after = mc.followed(asked, reply["id"])
        self.assertEqual((after["status"], after["followUp"]), ("replied", reply["id"]))
        done = mc.answered(mc.new_record(CID, "d1", "x", {}, 3, "vi", NOW), "done", "ok", 4, NOW)
        self.assertEqual(mc.followed(done, reply["id"])["status"], "done", "a done change stays done")
        for answering, code in ((mc.new_record(CID, "d1", "x", {}, 3, "vi", NOW), "command-reply-open"), ({**asked, "designId": "d2"}, "command-reply-design")):
            with self.assertRaises(InvalidInput) as e:
                mc.new_record("20261116-150100-c3d4", "d1", "600", None, 3, "vi", NOW, answering)
            self.assertEqual(e.exception.code, code)


class TestInboxFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = CommandInbox(self.tmp / "inbox", lambda: NOW)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_put_list_answer_drop(self):
        a = self.inbox.put("d1", "xóa TD3", {"kind": "module", "id": "TD3"}, 2, "vi")
        b = self.inbox.put("d2", "tạo cửa sổ", {"kind": "floor", "point": {"x": 1, "z": 2}}, 5, "vi")
        self.assertTrue((self.tmp / "inbox" / f"{a['id']}.json").exists())
        self.assertEqual([r["id"] for r in self.inbox.list("pending")], sorted([a["id"], b["id"]]))
        self.assertEqual([r["id"] for r in self.inbox.list(design_id="d2")], [b["id"]])
        self.inbox.answer(a["id"], "done", "Đã xóa TD3", 3)
        self.assertEqual(self.inbox.get(a["id"])["revision"], 3)
        self.assertEqual([r["id"] for r in self.inbox.list("pending")], [b["id"]])
        self.assertEqual(self.inbox.drop(b["id"])["status"], "dropped")
        self.assertEqual(self.inbox.list("pending"), [])
        with self.assertRaises(NotFound):
            self.inbox.get("20261116-000000-zzzz")
        with self.assertRaises(InvalidInput):
            self.inbox.get("../kitchen")
        self.assertEqual(CommandInbox(self.tmp / "none", lambda: NOW).list(), [])


class TestServiceHttpMcp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_inbox_lives_beside_the_database(self):
        rec = self.svc.command_put(self.did, "xóa TD1", {"kind": "module", "id": "TD1"}, 1, "vi")
        self.assertTrue((self.tmp / "command-inbox" / f"{rec['id']}.json").exists())
        self.assertEqual(self.svc.command_mode(), "inbox")
        with self.assertRaises(KeyError):
            self.svc.command_put("no-such-design", "xóa TD1", {}, 1, "vi")

    def test_http_routes(self):
        import web_server
        srv = web_server.make_server(0, self.svc)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def req(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            c.request(method, path, body=None if body is None else json.dumps(body),
                      headers={"Host": f"localhost:{port}", **({"Content-Type": "application/json"} if body is not None else {})})
            r = c.getresponse()
            data = json.loads(r.read() or b"{}")
            c.close()
            return r.status, data
        try:
            st, rec = req("POST", f"/api/designs/{self.did}/command", {"text": "đổi cánh TD1 sang kính", "baseRev": 1,
                                                                       "place": {"kind": "module", "id": "TD1"}, "lang": "vi"})
            self.assertEqual((st, rec["status"], rec["place"]), (201, "pending", {"kind": "module", "id": "TD1"}))
            st, listed = req("GET", f"/api/command-inbox?design={self.did}&status=pending")
            self.assertEqual((st, listed["mode"], [c["id"] for c in listed["commands"]]), (200, "inbox", [rec["id"]]))
            self.assertEqual(req("GET", f"/api/command-inbox/{rec['id']}")[1]["text"], "đổi cánh TD1 sang kính")
            self.assertEqual(req("POST", f"/api/command-inbox/{rec['id']}/drop", {})[1]["status"], "dropped")
            self.assertEqual(req("POST", f"/api/designs/{self.did}/command", {"text": " "})[0], 400)
            self.assertEqual(req("GET", "/api/command-inbox/20261116-000000-zzzz")[0], 404)
            st, ask = req("POST", f"/api/designs/{self.did}/command", {"text": "đổi màu", "baseRev": 1, "place": {"kind": "module", "id": "TD1"}})
            self.svc.command_answer(ask["id"], "question", "Màu nào?", None, ["trắng", "đen"])
            st, back = req("POST", f"/api/designs/{self.did}/command", {"text": "trắng", "baseRev": 1, "replyTo": ask["id"]})
            self.assertEqual((st, back["replyTo"], back["context"]["reply"], back["place"]), (201, ask["id"], "Màu nào?", {"kind": "module", "id": "TD1"}))
            self.assertEqual(req("GET", f"/api/command-inbox/{ask['id']}")[1]["status"], "replied")
            self.assertEqual(req("POST", f"/api/designs/{self.did}/command", {"text": "x", "replyTo": "../etc"})[0], 400)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_claude_reads_carries_out_and_answers_by_mcp(self):
        import server
        server._svc = self.svc
        try:
            rec = self.svc.command_put(self.did, "tạo cửa sổ", {"kind": "floor", "point": {"x": -1500, "z": -50}}, 1, "vi")
            (seen,) = server.list_menu_commands()["commands"]
            self.assertEqual(seen["id"], rec["id"])
            said = server.opening_command(self.did, seen["text"], seen["place"], seen["baseRev"])
            self.assertEqual((said["status"], said["operation"]["opening"]["sill"]), ("ok", 900.0))
            applied = server.apply_change(self.did, said["baseRev"], said["operation"], said["proposal"]["opHash"])
            with self.assertRaises(Exception):
                server.apply_change(self.did, applied["rev"], {"op": "remove", "id": "TD1"}, "not-the-preview")
            done = server.answer_menu_command(rec["id"], "done", "Đã thêm cửa sổ cách sàn 900", applied["rev"],
                                              ["Cửa sổ cách sàn 1100"], said["baseRev"])
            self.assertEqual((done["status"], done["revision"], done["fromRev"], done["choices"]),
                             ("done", applied["rev"], said["baseRev"], ["Cửa sổ cách sàn 1100"]))
            self.assertEqual(server.list_menu_commands()["commands"], [])
            self.assertEqual(server.get_menu_command(rec["id"])["reply"], "Đã thêm cửa sổ cách sàn 900")
        finally:
            server._svc = None


if __name__ == "__main__":
    unittest.main()
