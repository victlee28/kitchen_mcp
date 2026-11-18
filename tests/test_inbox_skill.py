"""The kitchen-inbox skill (18/11/2026): the inbox procedure lives in data/skills/kitchen-inbox in the open Agent Skills format; the
background worker takes it as instructions (the prompt-text fallback when it is missing), MCP agents get it from list_menu_commands /
get_inbox_skill, so changing the AI model needs no new explanation."""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import skills  # noqa: E402
from kitchen.errors import NotFound  # noqa: E402
from kitchen.inbox_worker import TOOLS as WORKER_TOOLS  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

DATA = ROOT / "data"
SKILL_DIR = DATA / "skills" / "kitchen-inbox"


class TestSkillFile(unittest.TestCase):
    def test_front_matter_follows_the_standard(self):
        meta, body = skills.parse((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], SKILL_DIR.name)
        self.assertRegex(meta["name"], skills.NAME)
        self.assertTrue(0 < len(meta["description"]) <= skills.MAX_DESCRIPTION)
        self.assertFalse(body.startswith("---"))
        self.assertIn("# Kitchen design: the command inbox", body)

    def test_every_tool_it_names_exists(self):
        import server
        known = {f.__name__ for f in server.TOOLS} | {t.name for t in WORKER_TOOLS}
        texts = [(SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")] + [p.read_text(encoding="utf-8") for p in (SKILL_DIR / "references").glob("*.md")]
        named = set()
        for text in texts:
            named |= set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text))
        tools_like = {n for n in named if n.split("_")[0] in {"list", "get", "start", "answer", "apply", "propose", "interpret", "opening", "render", "auto", "update", "revert", "design"}}
        self.assertTrue(tools_like, "the skill names no tools")
        self.assertEqual(sorted(tools_like - known), [])

    def test_text_is_english(self):
        for path in [SKILL_DIR / "SKILL.md", *(SKILL_DIR / "references").glob("*.md")]:
            text = path.read_text(encoding="utf-8")
            prose = re.sub(r'"[^"\n]*"|`[^`\n]*`|\([^)\n]*"[^)\n]*\)', "", text)        # quoted user sentences may be Vietnamese
            self.assertFalse(re.search(r"[ạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹđ]", prose), path.name)


class TestLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, text: str) -> Path:
        path = self.tmp / "skills" / "demo" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_skill_is_none(self):
        self.assertIsNone(skills.load("demo", self.tmp))

    def test_body_without_front_matter_and_reloaded_after_an_edit(self):
        path = self.write("---\nname: demo\ndescription: \"Do a thing.\"\n---\n\nStep one.\n")
        first = skills.load("demo", self.tmp)
        assert first is not None
        self.assertEqual((first.name, first.description, first.body, first.references), ("demo", "Do a thing.", "Step one.\n", ()))
        path.write_text("---\nname: demo\ndescription: Do a thing.\n---\nStep two.\n", encoding="utf-8")
        second = skills.load("demo", self.tmp)
        assert second is not None
        self.assertEqual(second.body, "Step two.\n")
        self.assertNotEqual(first.version, second.version)

    def test_references_are_files_of_the_folder_only(self):
        self.write("---\nname: demo\ndescription: x\n---\nbody\n")
        (self.tmp / "skills" / "demo" / "references").mkdir()
        (self.tmp / "skills" / "demo" / "references" / "ops.md").write_text("ops", encoding="utf-8")
        loaded = skills.load("demo", self.tmp)
        assert loaded is not None
        self.assertEqual(loaded.references, ("ops.md",))
        self.assertEqual(skills.reference("demo", "ops.md", self.tmp), "ops")
        for bad in ("../SKILL.md", "x/ops.md", "ops.txt", ".hidden.md", "nope.md"):
            self.assertIsNone(skills.reference("demo", bad, self.tmp), bad)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")

    def test_worker_instructions_are_the_skill_with_its_references(self):
        text = self.svc.inbox_instructions()
        self.assertIn("# Kitchen design: the command inbox", text)
        self.assertIn("# references/ops.md", text)
        self.assertIn("# references/checks.md", text)
        self.assertNotIn("name: kitchen-inbox", text)
        self.assertIs(self.svc.inbox_worker().instructions.__func__, KitchenService.inbox_instructions)

    def test_without_the_skill_the_worker_falls_back_to_prompt_text(self):
        data = self.tmp / "data"
        shutil.copytree(DATA, data, ignore=shutil.ignore_patterns("skills"))
        svc = KitchenService(self.tmp / "k2.db", self.tmp / "renders2", data_dir=data)
        from kitchen.prompts import photo as prompt_texts
        self.assertEqual(svc.inbox_instructions(), prompt_texts.text("inbox-worker", svc.catalog()))
        with self.assertRaises(NotFound):
            svc.inbox_skill()

    def test_skill_and_reference_by_name(self):
        got = self.svc.inbox_skill()
        self.assertEqual((got["name"], sorted(got["references"])), ("kitchen-inbox", ["checks.md", "ops.md"]))
        ops = self.svc.inbox_skill("ops.md")
        self.assertEqual((ops["reference"], ops["version"]), ("ops.md", got["version"]))
        with self.assertRaises(NotFound):
            self.svc.inbox_skill("../SKILL.md")


class TestMcp(unittest.TestCase):
    def setUp(self):
        import server
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.server = server
        server._svc = self.svc
        self.addCleanup(setattr, server, "_svc", None)

    def test_the_list_carries_the_skill_and_its_text_only_with_work_to_do(self):
        empty = self.server.list_menu_commands()
        self.assertEqual((empty["skill"]["name"], "text" in empty["skill"]), ("kitchen-inbox", False))
        from kitchen.intent import KitchenTemplate
        did = self.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3600}), "t")["id"]
        self.svc.command_put(did, "xóa TD1", {"kind": "module", "id": "TD1"}, 1, "vi")
        pending = self.server.list_menu_commands()
        self.assertEqual(len(pending["commands"]), 1)
        self.assertEqual(pending["skill"]["version"], self.svc.inbox_skill()["version"])
        self.assertIn("# Kitchen design: the command inbox", pending["skill"]["text"])
        self.assertNotIn("text", self.server.list_menu_commands("done")["skill"])

    def test_get_inbox_skill_tool(self):
        self.assertIn("get_inbox_skill", {f.__name__ for f in self.server.TOOLS})
        self.assertIn("ops.md", self.server.get_inbox_skill()["references"])
        self.assertIn('"op"', self.server.get_inbox_skill("ops.md")["text"])
        with self.assertRaises(Exception):
            self.server.get_inbox_skill("missing.md")


if __name__ == "__main__":
    unittest.main()
