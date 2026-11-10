"""CabinetRecognizerHttp: the HTTP adapter to the stand-alone cabinet-recognizer, its errors, the default-recognizer rule and an end-to-end
run (the real service in replay mode -> adapter -> KitchenService.recognize -> preview of ONE replace that keeps the room)."""
import base64
import dataclasses
import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "services" / "cabinet-recognizer"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVICE))

from kitchen import recognition  # noqa: E402
from kitchen.backends import BackendError  # noqa: E402
from kitchen.config import Config  # noqa: E402
from kitchen.recognizers import CabinetInboxHttp, CabinetRecognizerHttp  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

FIX = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
DATA = SERVICE / "tests" / "data"
NAME = "bep-chu-L-trang"
IMAGE = (DATA / f"{NAME}.png").read_bytes()
ANSWERS = json.loads((DATA / f"{NAME}.answers.json").read_text(encoding="utf-8"))


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def canned(status, body: bytes, seen: list | None = None):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("content-length", "0"))
            if seen is not None:
                seen.append(json.loads(self.rfile.read(n)))
            self.send_response(status)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    return H


def cfg(url, **kw) -> Config:
    return dataclasses.replace(Config.from_env({}), cabinet_recognizer_url=url, **kw)


class TestAdapter(unittest.TestCase):
    def tearDown(self):
        for s in getattr(self, "servers", []):
            s.shutdown(); s.server_close()

    def up(self, handler):
        server, url = serve(handler)
        self.servers = getattr(self, "servers", []) + [server]
        return url

    def test_sends_the_picture_and_the_cleaned_note_and_reads_the_modules(self):
        seen: list = []
        answer = {"runs": {"schema": "recognized-runs/1", "runs": [{"id": "back", "length": 1500, "modules": [
            {"id": "B1", "type": "base", "s": 900, "width": 600, "y": 0, "height": 840, "depth": 600},
            {"id": "B2", "type": "base", "s": 0, "width": 900, "y": 0, "height": 840, "depth": 600, "confidence": 0.9}]}],
            "joints": [], "common": {"material": {"countertop": "granite", "floor": "x"}}, "issues": [{"code": "type-approximated", "module": "B1", "message": "m"}]}}
        rec = CabinetRecognizerHttp(cfg(self.up(canned(200, json.dumps(answer).encode(), seen))))
        raw = rec.recognize(recognition.RecognitionInput("photo", b"\x89PNG data", "a.png", "image/png", "  white   doors "))
        self.assertEqual(seen[0], {"kind": "photo", "imageBase64": base64.b64encode(b"\x89PNG data").decode(), "note": "white doors"})
        self.assertEqual([(m["wall"], m["fromCorner"], m["width"], m.get("confidence")) for m in raw["modules"]],
                         [("back", 0.0, 600, 0.4), ("back", 600.0, 900, 0.9)], "the flat draft for review: fromCorner from the right-hand end, approximations flagged")
        self.assertEqual(raw["materials"], {"countertop": "granite"})
        self.assertEqual(raw["layout"], answer["runs"])
        with self.assertRaises(BackendError):
            CabinetRecognizerHttp(cfg(self.up(canned(200, json.dumps({"kitchen": {"spec": {"module": []}}}).encode())))).recognize(
                recognition.RecognitionInput("photo", b"\x89PNG data", "a.png", "image/png", ""))

    def test_errors_become_backend_errors_with_the_service_reason(self):
        err = json.dumps({"error": {"kind": "validation", "code": "bad-image", "message": "cannot identify"}}).encode()
        with self.assertRaises(BackendError) as ctx:
            CabinetRecognizerHttp(cfg(self.up(canned(422, err)))).recognize(recognition.RecognitionInput("photo", b"x"))
        self.assertEqual(ctx.exception.code, "generation-failed")
        self.assertIn("bad-image", str(ctx.exception))
        with self.assertRaises(BackendError) as ctx:
            CabinetRecognizerHttp(cfg(self.up(canned(502, b"<html>bad gateway</html>")))).recognize(recognition.RecognitionInput("photo", b"x"))
        self.assertEqual(ctx.exception.code, "overloaded")
        with self.assertRaises(BackendError) as ctx:
            CabinetRecognizerHttp(cfg(self.up(canned(200, b"not json")))).recognize(recognition.RecognitionInput("photo", b"x"))
        self.assertEqual(ctx.exception.code, "generation-failed")
        with self.assertRaises(BackendError) as ctx:
            CabinetRecognizerHttp(cfg(self.up(canned(200, b'{"spec": {}}')))).recognize(recognition.RecognitionInput("photo", b"x"))
        self.assertIn("no kitchen", str(ctx.exception))

    def test_unreachable_service_and_bad_url(self):
        server, url = serve(canned(200, b"{}"))
        server.shutdown(); server.server_close()                           # the port is now closed
        with self.assertRaises(BackendError) as ctx:
            CabinetRecognizerHttp(cfg(url, cabinet_recognizer_timeout=5)).recognize(recognition.RecognitionInput("photo", b"x"))
        self.assertEqual(ctx.exception.code, "overloaded")
        for bad in (None, "ftp://x", "localhost:8765"):
            with self.assertRaises(BackendError):
                CabinetRecognizerHttp(cfg(bad))

    def test_config_reads_the_environment_once(self):
        c = Config.from_env({"CABINET_RECOGNIZER_URL": " http://127.0.0.1:8765/ ", "CABINET_RECOGNIZER_TIMEOUT": "90", "KITCHEN_RECOGNIZER": "cabinet"})
        self.assertEqual((c.cabinet_recognizer_url, c.cabinet_recognizer_timeout, c.default_recognizer), ("http://127.0.0.1:8765", 90.0, "cabinet"))
        c = Config.from_env({})
        self.assertEqual((c.cabinet_recognizer_url, c.default_recognizer), (None, None))


class TestChoose(unittest.TestCase):
    def test_rules(self):
        pick = recognition.choose_recognizer
        self.assertEqual(pick(["gemini", "cabinet"], None, None), "cabinet")           # the stand-alone reader wins when both exist
        self.assertEqual(pick(["gemini", "cabinet", "inbox"], None, None), "inbox")    # no choice made: Claude Desktop by chat first
        self.assertEqual(pick(["gemini", "cabinet"], None, "gemini"), "gemini")        # the configured default beats the preference
        self.assertEqual(pick(["gemini", "cabinet"], "gemini", "cabinet"), "gemini")   # a request beats the default
        self.assertIsNone(pick(["gemini"], "cabinet", None))                           # asked for something that is not plugged in
        self.assertEqual(pick(["gemini"], None, "cabinet"), "gemini")                  # a default that is not plugged in is ignored
        self.assertEqual(pick(["mine"], None, None), "mine")                           # the only one
        self.assertIsNone(pick(["a", "b"], None, None))
        self.assertIsNone(pick([], None, None))


class TestEndToEnd(unittest.TestCase):
    """The real cabinet-recognizer HTTP service (replay mode: recorded model answers, no key) behind the adapter."""

    def setUp(self):
        from cabinet_recognizer.config import Config as RecogConfig
        from cabinet_recognizer.http_server import make_handler
        from cabinet_recognizer.vision import ReplayClient
        self.server, url = serve(make_handler(RecogConfig.from_env(), ReplayClient(ANSWERS)))
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-e2e-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.svc.recognizers["cabinet"] = CabinetRecognizerHttp(cfg(url))
        self.did = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_photo_to_preview_keeps_the_room_and_saves_nothing(self):
        before, rev = self.svc.store.get(self.did)
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": base64.b64encode(IMAGE).decode(), "name": "kitchen.png", "note": "white doors"})
        self.assertEqual((r["status"], r["recognizer"]), ("ok", "cabinet"))
        total = sum(len(run["modules"]) for run in r["layout"]["runs"])
        kinds = [o["op"] for o in r["operation"]["ops"]]
        self.assertEqual((kinds.count("remove"), kinds.count("add-run"), kinds.count("add")), (len(before.module), 2, total),
                         "no edge picked: the old cabinets go, the whole L comes by runs")
        self.assertTrue(r["draft"]["modules"])
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(len(self.svc.history(self.did)), rev)                             # nothing was written
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, rev2 = self.svc.store.get(self.did)
        self.assertEqual((rev2, len(after.module)), (rev + 1, total))
        self.assertEqual(after.model_dump(mode="json")["room"], before.model_dump(mode="json")["room"], "the design's own room is kept")
        self.assertTrue(any(m.doors for m in after.module) and any(m.frontSections for m in after.module), "doors and drawers are kept")
        back = next(run for run in after.runs if run.yaw == 0)
        self.assertEqual(back.z, 0.0, "the main run stands on the back wall of the kitchen frame")

    def test_on_a_picked_edge_the_whole_l_is_placed_by_runs_with_its_doors(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from kitchen import geometry, roomctx
        from test_floorplan import ROOM, elem, plan, rect
        did = self.svc.import_floorplan(plan(ROOM, elem("column_a", "column", "column", rect(1500, 2000, 1900, 2400), "Cot")))["id"]
        self.svc.apply(did, {"op": "add", "module": {"type": "base", "wall": "back", "fromCorner": 0, "width": 600, "y": 0, "height": 840, "depth": 550}}, 1)
        self.svc.bind_floorplan(did)
        spec, rev = self.svc.store.get(did)
        sc = geometry.compile_spec(spec)
        x, z = roomctx.for_spec(spec, sc.lsau, sc.lphai).placement.to_room(-1500.0, 1990.0)
        r = self.svc.recognize(did, {"kind": "photo", "imageBase64": base64.b64encode(IMAGE).decode()},
                               anchor={"structureId": "STRUCT-column_a", "point": {"x": x, "z": z}})
        self.assertEqual(r["status"], "ok")
        layout = r["layout"]
        self.assertEqual([run["id"] for run in layout["runs"]], ["left", "back"])
        self.assertEqual(layout["joints"], [["left", "back"]])
        total = sum(len(run["modules"]) for run in layout["runs"])
        ops = r["operation"]["ops"]
        adds = [o["module"] for o in ops if o["op"] == "add"]
        self.assertEqual(([o["op"] for o in ops].count("add-run"), len(adds)), (2, total), "both runs, every recognised cabinet: none is dropped")
        self.assertTrue(any(m.get("doors") for m in adds) and any(m.get("frontSections") for m in adds), "doors and drawers come through")
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(self.svc.store.get(did)[1], rev, "nothing is saved before apply")
        self.svc.apply(did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        after, _ = self.svc.store.get(did)
        self.assertEqual((len(after.runs), len([m for m in after.module if m.run])), (2, total))

    def test_service_down_is_a_failed_status(self):
        self.server.shutdown(); self.server.server_close()
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": base64.b64encode(IMAGE).decode()})
        self.assertEqual(r["status"], "failed")
        self.assertIn("cabinet-recognizer", r["message"])


class TestInbox(unittest.TestCase):
    """No model API: the photo opens a job, the preview waits ("pending") until the job's questions are answered, then the update button finishes it."""

    def setUp(self):
        from cabinet_recognizer.config import Config as RecogConfig
        from cabinet_recognizer.http_server import make_handler
        from cabinet_recognizer.vision import ReplayClient
        self.tmp = Path(tempfile.mkdtemp(prefix="recog-inbox-"))
        self.server, url = serve(make_handler(RecogConfig.from_env(), ReplayClient({}), self.tmp / "jobs"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.svc.recognizers.clear()
        self.svc.recognizers["inbox"] = CabinetInboxHttp(cfg(url))
        self.did = self.svc.create_from_spec(json.loads(json.dumps(FIX)))["id"]

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pending_then_ok_after_the_answers_are_written(self):
        r = self.svc.recognize(self.did, {"kind": "photo", "imageBase64": base64.b64encode(IMAGE).decode(), "note": "white doors"}, "inbox")
        self.assertEqual((r["status"], r["recognizer"], r["step"]), ("pending", "inbox", "scene"))
        job = r["job"]
        self.assertTrue(recognition.recognizer_wire.clean_job_id(job))
        again = self.svc.recognize_collect(self.did, job)
        self.assertEqual((again["status"], again["job"]), ("pending", job), "no answer yet")
        answers = self.tmp / "jobs" / job / "inbox" / "answers"
        for step, answer in ANSWERS.items():                  # what Claude Desktop does when the user asks it to answer the job
            (answers / f"{step}.json").write_text(answer if isinstance(answer, str) else json.dumps(answer), encoding="utf-8")
        done = self.svc.recognize_collect(self.did, job, r["baseRev"])
        self.assertEqual(done["status"], "ok")
        self.assertEqual([o["op"] for o in done["operation"]["ops"]].count("add-run"), 2)
        self.assertTrue(done["proposal"]["applicable"])
        self.assertEqual(len(self.svc.history(self.did)), r["baseRev"], "nothing is saved before the user applies it")

    def test_bad_job_ids_and_missing_inbox(self):
        for bad in ("", "../x", "20261109-1", None):
            with self.assertRaises(Exception) as ctx:
                self.svc.recognize_collect(self.did, bad)
            self.assertEqual(getattr(ctx.exception, "code", None), "bad-job")
        self.assertEqual(self.svc.recognize_collect(self.did, "20990101-000000")["status"], "failed", "a job the service does not know")
        self.svc.recognizers.clear()
        self.assertEqual(self.svc.recognize_collect(self.did, "20261109-142100")["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
