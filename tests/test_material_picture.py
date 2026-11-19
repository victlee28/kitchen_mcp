"""A material taken from a reference picture (18/11/2026): "ốp tường bằng vật liệu trong ảnh tham chiếu" sent with a picture. The picture is
kept with the inbox command, the AI looks at it, keeps it as a material sample and names the material; the 3D export lays the picture on
every surface of that name."""
import base64
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image  # noqa: E402

from kitchen import edit, threejs_export  # noqa: E402
from kitchen.errors import InvalidInput, NotFound  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from test_inbox_worker import Scripted, last_tool_result, op_hash  # noqa: E402


def png(color=(200, 180, 150), size=(40, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def picture(data: bytes) -> dict:
    return {"name": "marble.png", "type": "image/png", "data": base64.b64encode(data).decode()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "r")
        self.did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]

    def command(self, data=None, text="ốp tường bằng vật liệu trong ảnh tham chiếu cho tôi"):
        place = {"kind": "part", "part": "door", "id": "TD1", "module": "TD1", "modules": ["TD1", "TD3"]}
        return self.svc.command_put(self.did, text, place, 1, "vi", None, picture(data or png()))


class TestInboxPicture(Base):
    def test_the_picture_is_kept_beside_the_command(self):
        rec = self.command()
        att = rec["attachment"]
        self.assertEqual((att["mime"], att["name"], att["file"]), ("image/png", "marble.png", f"{rec['id']}.png"))
        data, mime, _ = self.svc.command_picture(rec["id"])
        self.assertEqual((data, mime), (png(), "image/png"))

    def test_a_reply_is_about_the_same_picture(self):
        rec = self.command()
        self.svc.commands.take(rec["id"], "claude")
        self.svc.commands.answer(rec["id"], "question", "Ốp mặt nào?", None, ["Mặt trong"])
        reply = self.svc.command_put(self.did, "Mặt trong", None, 1, "vi", rec["id"])
        self.assertEqual(reply["attachment"]["file"], rec["attachment"]["file"])

    def test_only_small_pictures_of_known_types(self):
        with self.assertRaises(InvalidInput):
            self.svc.command_put(self.did, "ốp tường", None, 1, "vi", None, {"name": "a.gif", "type": "image/gif", "data": "R0lG"})
        with self.assertRaises(InvalidInput):
            self.svc.command_put(self.did, "ốp tường", None, 1, "vi", None, {"name": "a.png", "type": "image/png", "data": "not base64!"})
        plain = self.svc.command_put(self.did, "xóa TD1", None, 1, "vi")
        with self.assertRaises(NotFound):
            self.svc.command_picture(plain["id"])


class TestSample(Base):
    def test_kept_once_with_its_average_colour(self):
        rec = self.command(png((200, 180, 150)))
        got = self.svc.material_sample(self.did, rec["id"])
        self.assertRegex(got["sample"], r"^smp-[0-9a-f]{16}$")
        self.assertEqual(got["color"], "#c8b496")
        self.assertEqual(self.svc.material_sample_file(got["sample"]).read_bytes(), png((200, 180, 150)))
        self.assertEqual(self.svc.material_sample(self.did, rec["id"])["sample"], got["sample"])
        with self.assertRaises(NotFound):
            self.svc.material_sample_file("smp-../../etc")

    def test_the_operation_names_it_and_the_export_lays_it_on_those_surfaces(self):
        rec = self.command()
        s = self.svc.material_sample(self.did, rec["id"])
        name = "Đá marble kem"
        op = {"op": "multi", "ops": [{"op": "material-sample", "name": name, "sample": s["sample"], "color": s["color"]},
                                     {"op": "update", "id": "TD1", "changes": {"material": name}},
                                     {"op": "surface-material", "surfaces": ["wall_back#inside"], "material": name}]}
        spec, _ = self.svc.store.get(self.did)
        try:
            after = edit.apply_op(spec, op)
        except InvalidInput:                      # this design's back wall has another id: the module part is enough
            op["ops"] = op["ops"][:2]
            after = edit.apply_op(spec, op)
        self.assertEqual(after.materialSamples, {name: {"sample": s["sample"], "color": s["color"]}})
        doc = threejs_export.export(after, "t", 1)
        hit = [m for m in doc["materials"] if m["name"] == name]
        self.assertTrue(hit)
        self.assertTrue(all(m["map"] == f"/api/material-samples/{s['sample']}" and m["color"] == s["color"] for m in hit))
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "kitchen-threejs.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)][:3], [])
        forgot = edit.apply_op(after, {"op": "material-sample", "name": name, "sample": None})
        self.assertIsNone(forgot.materialSamples)

    def test_bad_samples_are_refused(self):
        spec, _ = self.svc.store.get(self.did)
        for op in ({"op": "material-sample", "name": "x", "sample": "../x"}, {"op": "material-sample", "name": "", "sample": "smp-0123456789abcdef"},
                   {"op": "material-sample", "name": "x", "sample": "smp-0123456789abcdef", "color": "red"}):
            with self.assertRaises(InvalidInput):
                edit.apply_op(spec, op)


class TestMcp(Base):
    def test_claude_sees_the_picture_and_keeps_it(self):
        import server
        server._svc = self.svc
        self.addCleanup(setattr, server, "_svc", None)
        rec = self.command()
        seen = server.get_command_picture(rec["id"])
        self.assertEqual(seen[1]["mime"], "image/png")
        self.assertEqual(type(seen[0]).__name__, "Image")
        self.assertIn("sample", server.material_sample(self.did, rec["id"]))
        self.assertIn("get_command_picture", {f.__name__ for f in server.TOOLS})


class TestWorker(Base):
    def test_the_worker_model_gets_the_picture_and_saves_the_material(self):
        from dataclasses import replace
        rec = self.command()
        self.svc.models.config = replace(self.svc.models.config, llm_provider="anthropic", llm_model="m", anthropic_api_key="a")

        def ops(body):
            s = last_tool_result(body)
            assert s is not None
            name = "Đá marble kem"
            return ("propose_change", {"op": {"op": "multi", "ops": [
                {"op": "material-sample", "name": name, "sample": s["sample"], "color": s["color"]},
                {"op": "update", "id": "TD1", "changes": {"material": name}},
                {"op": "update", "id": "TD3", "changes": {"material": name}}]}})
        self.svc.models.transport = Scripted("anthropic", [("material_sample", {}), ops,
                                                           lambda body: ("apply_change", {"expect": op_hash(last_tool_result(body))}),
                                                           ("answer", {"status": "done", "reply": "Đã ốp đá marble kem cho TD1, TD3"})])
        worker = self.svc.inbox_worker()
        took = self.svc.commands.take(rec["id"], "worker")
        done = worker.handle(took)
        assert done is not None
        self.assertEqual(done["status"], "done")
        first = self.svc.models.transport.bodies[0]
        self.assertIn('"type": "image"', json.dumps(first))
        spec, _ = self.svc.store.get(self.did)
        self.assertEqual({m.id: getattr(m, "material", None) for m in spec.module if m.id in ("TD1", "TD3")}, {"TD1": "Đá marble kem", "TD3": "Đá marble kem"})
        self.assertIn("Đá marble kem", spec.materialSamples or {})


if __name__ == "__main__":
    unittest.main()
