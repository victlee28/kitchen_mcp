"""Replacing a whole cabinet system: restyled with a preset, or laid out again along its own runs; the other systems never change."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kitchen import edit, runs, system_replace as sr  # noqa: E402
from kitchen.errors import InvalidInput  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from test_systems import ISLAND, L, L_MODS, mod, spec  # noqa: E402

KITCHEN = spec([*L, {**ISLAND, "system": "furniture_003"}],
               [*L_MODS, mod("U1", "R1", 0, kind="upper"), mod("K1", "R3", 0, material="Acrylic xám đậm", doorStyle="flat"),
                mod("K2", "R3", 600, material="Acrylic xám đậm", doorStyle="flat", handle={"variant": "knob", "material": "Đồng", "length": 128})])
NEW = [{"type": "base-sink", "width": 800.0, "s": 0.0, "y": 0.0, "height": 840.0, "depth": 600.0, "name": "Tủ chậu"},
       {"type": "base", "width": 400.0, "s": 800.0, "y": 0.0, "height": 840.0, "depth": 600.0},
       {"type": "upper", "width": 600.0, "s": 0.0, "y": 1500.0, "height": 700.0, "depth": 350.0}]


class TestRestyle(unittest.TestCase):
    def test_auto_picks_a_style_unlike_the_current_one(self):
        mods = sr.members(KITCHEN, "furniture_003")
        self.assertEqual(sr.current_front(KITCHEN, mods), "Acrylic xám đậm")
        self.assertNotEqual(sr.pick_style(KITCHEN, mods, None).front, "Acrylic xám đậm")
        self.assertEqual(sr.pick_style(KITCHEN, mods, "classic-sage").id, "classic-sage")
        with self.assertRaises(InvalidInput):
            sr.pick_style(KITCHEN, mods, "no-such-style")

    def test_only_the_system_changes(self):
        mods = sr.members(KITCHEN, "furniture_003")
        style = sr.STYLE_BY_ID["classic-sage"]
        after = edit.apply_op(KITCHEN, edit.combine_ops(sr.style_ops(KITCHEN, mods, style)))
        for i in ("K1", "K2"):
            m = after.find(i)
            self.assertEqual((m.material, m.doorStyle, m.handle.variant, m.handle.material), (style.front, "frame", "knob", "Đồng thau"))
        self.assertEqual(after.find("K2").handle.length, 128, "the cabinet's own handle length stays")
        for i in ("A1", "A2", "B1", "B2", "U1"):
            self.assertEqual(after.find(i), KITCHEN.find(i))
        self.assertEqual(after.common, KITCHEN.common)

    def test_unknown_system(self):
        with self.assertRaises(InvalidInput):
            sr.members(KITCHEN, "nope")


class TestRelayout(unittest.TestCase):
    def test_slots_longest_first(self):
        slots = sr.run_slots(KITCHEN, sr.members(KITCHEN, "auto-R1"))
        self.assertEqual([(s.run, s.length) for s in slots], [("R1", 1200.0), ("R2", 1200.0)])
        self.assertIn("upper", slots[0].storeys)

    def test_island_laid_again_without_wall_cabinets_keeping_its_fronts_and_system(self):
        mods = sr.members(KITCHEN, "furniture_003")
        ops, summary = sr.relayout_ops(KITCHEN, mods, {"R3": NEW}, {})
        after = edit.apply_op(KITCHEN, edit.combine_ops(ops))
        island = [m for m in after.module if m.run == "R3"]
        self.assertEqual([m.type for m in island], ["base-sink", "base"])      # the upper is left out: the island had none
        self.assertTrue(all(m.material == "Acrylic xám đậm" and m.doorStyle == "flat" for m in island))
        self.assertEqual({(m.handle.variant, m.handle.material) for m in island}, {("knob", "Đồng")})
        self.assertIn("1 upper cabinets left out: the system had none on that storey", summary)
        self.assertEqual({runs.systems(after)[m.id] for m in island}, {"furniture_003"})
        for i in ("A1", "A2", "B1", "B2", "U1"):
            self.assertEqual(after.find(i), KITCHEN.find(i))

    def test_the_sentence_fronts_win(self):
        mods = sr.members(KITCHEN, "auto-R1")
        ops, _ = sr.relayout_ops(KITCHEN, mods, {"R1": NEW}, {"material": {"base": "Sơn kem mờ"}, "handle": {"variant": "bar"}})
        after = edit.apply_op(KITCHEN, edit.combine_ops(ops))
        r1 = [m for m in after.module if m.run == "R1"]
        self.assertEqual(sorted(m.type for m in r1), ["base", "base-sink", "upper"])       # R1 had wall cabinets: kept
        self.assertEqual({m.material for m in r1 if m.storey == "base"}, {"Sơn kem mờ"})
        self.assertFalse(any(m.run == "R2" for m in after.module))     # R2 got nothing: its old cabinets are gone with the run

    def test_cabinets_in_no_run_cannot_be_laid_again(self):
        free = spec([], [{"id": "W1", "type": "base", "wall": "back", "fromCorner": 0, "width": 600, "height": 840, "depth": 600}])
        with self.assertRaises(InvalidInput):
            sr.run_slots(free, sr.members(free, "design"))


class TestWebStyles(unittest.TestCase):
    def test_the_page_lists_the_same_presets(self):
        import re
        src = (ROOT / "web" / "menu-logic.js").read_text(encoding="utf-8")
        block = src[src.index("export const SYSTEM_STYLES"):src.index("];", src.index("export const SYSTEM_STYLES"))]
        ids = re.findall(r"\['([a-z-]+)',", block)
        self.assertEqual(ids, ["auto", *(s.id for s in sr.STYLES)])
        self.assertEqual(dict(re.findall(r"\['([a-z-]+)', '([^']+)'\]", block))["warm-oak"], sr.STYLE_BY_ID["warm-oak"].name)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sysrep-"))
        self.svc = KitchenService(self.tmp / "k.db", self.tmp / "renders")
        self.did = self.svc.create_from_spec(KITCHEN.model_dump(mode="json"))["id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_without_a_sentence_the_system_is_restyled(self):
        r = self.svc.template(self.did, {"kind": "replace-system", "system": "furniture_003"})
        self.assertEqual((r["mode"], r["style"]), ("restyle", "modern-white"))
        self.assertTrue(r["proposal"]["applicable"])
        self.assertEqual(self.svc.store.get(self.did)[1], r["baseRev"], "a preview: nothing saved")

    def test_with_a_sentence_the_island_is_laid_again(self):
        r = self.svc.template(self.did, {"kind": "replace-system", "system": "furniture_003", "prompt": "có chậu rửa, cánh khung"})
        self.assertEqual(r["mode"], "relayout")
        self.assertTrue(r["proposal"]["applicable"], r["proposal"].get("error"))
        self.svc.apply(self.did, r["operation"], r["baseRev"], "test", r["proposal"]["opHash"])
        spec, _ = self.svc.store.get(self.did)
        island = [m for m in spec.module if m.run == "R3"]
        self.assertTrue(island and all(m.storey == "base" for m in island))
        self.assertIn("base-sink", {m.type for m in island})
        self.assertEqual({m.doorStyle for m in island}, {"frame"})
        self.assertEqual(sum(m.width for m in island), 1200.0)


if __name__ == "__main__":
    unittest.main()
