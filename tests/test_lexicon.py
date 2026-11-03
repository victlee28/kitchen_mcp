"""Prompt vocabulary: styles, layouts, door styles, materials with scope, backsplash, metals — matching, scope, status, and what reaches
the spec, the 3D geometry, the Three.js file and the image prompt."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen import geometry, intent, layers, lexicon, threejs_export  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402
from kitchen.spec import dump_spec  # noqa: E402


def lex(text):
    return lexicon.interpret(text)


def status_of(res, term_part):
    return [i["status"] for i in res.items if term_part in i["term"] or term_part in i["canonical"]]


class TestMatching(unittest.TestCase):
    def test_accent_variants_give_the_same_result(self):
        a = lex("bếp chữ L, tủ dưới veneer óc chó, mặt bàn quartz trắng, tay nắm đồng thau xước, phong cách tân cổ điển").updates
        b = lex("bep chu L, tu duoi veneer oc cho, mat ban quartz trang, tay nam dong thau xuoc, phong cach tan co dien").updates
        self.assertEqual(a, b)
        self.assertEqual((a["style"], a["geometry_edit"]), ("Neoclassical", "L"))

    def test_longest_phrase_wins(self):
        self.assertEqual(lex("tân cổ điển").updates["style"], "Neoclassical")
        self.assertEqual(lex("cổ điển").updates["style"], "Classic")
        self.assertEqual(len(lex("đảo thác đá").items), 1, "one phrase, one item (not island + waterfall)")

    def test_weak_words_do_not_fire_on_other_words(self):
        for text in ("kệ mở cánh tủ", "đèn thả trên bàn", "kèm tủ lạnh", "đã có tủ", "bê tông mài", "mở rộng bếp"):
            u = lex(text).updates
            self.assertNotIn("material", u, text)
            self.assertNotIn("handleMaterial", u, text)

    def test_fold_keeps_length(self):
        s = "Tủ Bếp Đẹp Ốp Đá Xương Cá, 2,4m"
        self.assertEqual(len(lexicon.fold(s)), len(lexicon._nfc(s)))


class TestStyles(unittest.TestCase):
    def test_each_style_term(self):
        cases = {"modern": ("Modern", []), "hiện đại": ("Modern", []), "minimalist": ("Minimalist", []), "tối giản": ("Minimalist", []),
                 "Scandinavian": ("Minimalist", ["Scandinavian"]), "bắc âu": ("Minimalist", ["Scandinavian"]),
                 "Japandi": ("Minimalist", ["Japandi"]), "wabi-sabi": ("Minimalist", ["Japandi"]),
                 "industrial": ("Industrial", []), "công nghiệp": ("Industrial", []),
                 "farmhouse": (None, ["Farmhouse"]), "nông trại": (None, ["Farmhouse"]), "phong cách đồng quê": (None, ["Country"]),
                 "classic": ("Classic", []), "neo-classic": ("Neoclassical", []), "transitional": ("Transitional", []),
                 "mid-century": ("Modern", ["Mid-Century Modern"]), "luxury": (None, ["Luxury"]), "sang trọng": (None, ["Luxury"])}
        for text, (style, tags) in cases.items():
            u = lex(text).updates
            self.assertEqual((u.get("style"), u.get("styleTags", [])), (style, tags), text)

    def test_tag_only_style_does_not_change_geometry_style_or_moldings(self):
        spec = intent.from_template(intent.parse_prompt("bếp farmhouse sang trọng dài 3m")[0])
        self.assertEqual((spec.style, spec.styleTags), ("Modern", ["Farmhouse", "Luxury"]))
        self.assertFalse(spec.moldings and any(m.enabled for m in spec.moldings))

    def test_style_does_not_imply_materials(self):
        self.assertNotIn("material", lex("phong cách Japandi").updates)


class TestLayoutAndStructure(unittest.TestCase):
    def test_island_peninsula_and_open_shelf_are_built(self):
        for text, key in (("bếp có đảo bếp", "island"), ("waterfall island", "island"), ("peninsula kitchen", "peninsula"), ("kệ mở", "openShelf")):
            res = lex(text)
            self.assertTrue(res.updates.get(key), text)
            self.assertNotIn("geometry_edit", res.updates, "a feature never changes the I/L/U layout by itself")
            self.assertEqual({i["status"] for i in res.items}, {"built"}, text)

    def test_waterfall_edge_goes_to_the_image_prompt_only(self):
        self.assertTrue(any("waterfall" in h for h in lex("đảo thác đá").updates["aiHints"]))

    def test_supported_layouts(self):
        self.assertEqual(lex("bếp thẳng").updates["geometry_edit"], "I")
        self.assertEqual(lex("L-shaped kitchen").updates["geometry_edit"], "L")
        self.assertEqual(lex("bếp góc").updates["geometry_edit"], "L")
        self.assertEqual(lex("bếp chữ U").updates["geometry_edit"], "U")
        self.assertEqual(status_of(lex("bếp chữ U"), "U"), ["built"])

    def test_full_height_vs_backsplash_to_ceiling(self):
        self.assertTrue(lex("tủ kịch trần").updates["loft"])
        self.assertTrue(lex("floor-to-ceiling cabinets").updates["loft"])
        u = lex("ốp kịch trần gạch thẻ").updates
        self.assertNotIn("loft", u)
        self.assertEqual(u["backsplashHeight"], "to-ceiling")



class TestDoorsAndHandles(unittest.TestCase):
    def test_door_styles_follow_the_nearest_scope(self):
        u = lex("tủ dưới shaker, tủ trên cánh kính").updates["doorStyle"]
        self.assertEqual(u, {"base": "frame", "upper": "glass"})
        self.assertEqual(lex("tu duoi oc cho tu tren kinh soc").updates["doorStyle"], {"upper": "glass"})
        self.assertEqual(lex("flat-panel doors").updates["doorStyle"], {"base": "flat", "upper": "flat", "tall": "flat"})

    def test_door_style_reaches_modules_and_threejs(self):
        spec = intent.from_template(intent.parse_prompt("tủ dưới shaker, tủ trên cánh kính")[0])
        self.assertEqual({m.doorStyle for m in spec.module if m.storey == "base"}, {"frame"})
        self.assertEqual({m.doorStyle for m in spec.module if m.type == "upper"}, {"glass"})
        doc = threejs_export.export(spec, "d", 1)
        self.assertEqual(threejs_export.integrity(doc), [])

    def test_handleless_and_finger_pull(self):
        self.assertEqual(lex("handleless").updates["handleVariant"], "none")
        self.assertEqual(lex("rãnh âm").updates["handleVariant"], "concealed")
        spec = intent.from_template(intent.parse_prompt("bếp không tay nắm")[0])
        self.assertEqual(spec.common.handle.variant, "none")

    def test_metal_only_applies_to_handles_when_scoped(self):
        self.assertEqual(lex("tay nắm đồng thau xước").updates["handleMaterial"], "Đồng thau xước")
        self.assertEqual(lex("matte black hardware").updates["handleMaterial"], "Đen mờ")
        res = lex("tủ lạnh inox, brushed brass")
        self.assertNotIn("handleMaterial", res.updates)
        self.assertNotIn("material", res.updates)
        self.assertEqual(status_of(res, "inox"), ["ambiguous"])


class TestMaterialsByScope(unittest.TestCase):
    def test_two_materials_two_zones(self):
        m = lex("tủ dưới veneer óc chó, mặt bàn quartz trắng").updates["material"]
        self.assertEqual(m, {"base": "Veneer óc chó", "countertop": "Quartz trắng"})
        self.assertNotIn("upper", m, "white of the countertop must not leak to the wall cabinets")

    def test_english_word_order_and_colours(self):
        m = lex("walnut veneer base cabinets and white quartz countertop").updates["material"]
        self.assertEqual(m, {"base": "Veneer óc chó", "countertop": "Quartz trắng"})

    def test_finishes_and_stones(self):
        self.assertEqual(lex("tủ trên trắng mờ").updates["material"], {"upper": "Trắng mờ"})
        self.assertEqual(lex("mặt bàn marble vân mây").updates["material"]["countertop"], "Đá marble vân mây")
        self.assertEqual(lex("mặt đá terrazzo").updates["material"]["countertop"], "Terrazzo")
        self.assertEqual(lex("cánh acrylic bóng gương").updates["material"]["base"], "Acrylic bóng gương")

    def test_legacy_phrases_keep_working(self):
        self.assertEqual(lex("tủ sồi, mặt đá trắng").updates["material"],
                         {"base": "Laminate vân gỗ sồi sáng", "countertop": "Đá nhân tạo trắng"})
        self.assertEqual(intent.parse_prompt("Tủ bếp cao cấp dài 3m, cao 2.4m")[0].cabinetTop, 2400)

    def test_unscoped_colour_is_not_guessed_everywhere(self):
        res = lex("màu xanh rêu")
        self.assertNotIn("material", res.updates)
        self.assertIn("ambiguous", status_of(res, "xanh rêu"))


class TestBacksplashTerms(unittest.TestCase):
    def test_height_terms(self):
        self.assertEqual(lex("ốp cao 600 mm").updates["backsplashHeightMm"], 600)
        self.assertEqual(lex("backsplash 70 cm high").updates["backsplashHeightMm"], 700)
        self.assertEqual(lex("ốp lên sát tủ trên").updates["backsplashHeight"], "to-upper")
        self.assertEqual(lex("ốp tới trần").updates["backsplashHeight"], "to-ceiling")
        self.assertEqual(lex("backsplash to the ceiling").updates["backsplashHeight"], "to-ceiling")

    def test_backsplash_height_is_not_read_as_cabinet_height(self):
        t = intent.parse_prompt("Tủ bếp dài 3m, ốp cao 600 mm")[0]
        self.assertEqual((t.cabinetTop, t.backsplashHeightMm), (2200, 600))

    def test_material_pattern_and_height_are_separate(self):
        u = lex("ốp gạch Zellige xếp xương cá cao 700mm").updates
        self.assertEqual((u["material"]["wallTile"], u["wallTilePattern"], u["backsplashHeightMm"]), ("Gạch Zellige", "herringbone", 700))

    def test_geometry_and_threejs_agree(self):
        for prompt, expect in (("ốp cao 700 mm", 700), ("ốp tới trần", None), ("ốp lên sát tủ trên", 600)):
            spec = intent.from_template(intent.parse_prompt("bếp chữ I dài 3m, " + prompt)[0])
            scene = geometry.compile_spec(spec)
            g = {round(p.max[1] - p.min[1]) for p in scene.parts if p.type == "wall-tile"}
            t = {round(a["dimensions"]["height"]) for a in threejs_export.export(spec, "d", 1)["accessories"] if a["type"] == "Backsplash_Tile"}
            self.assertEqual(g, t, prompt)
            self.assertEqual(g, {expect or round(spec.common.ceiling - spec.common.countertop)}, prompt)


class TestReachesTheOutputs(unittest.TestCase):
    PROMPT = ("Bếp chữ L, tủ dưới veneer óc chó, tủ trên kính sọc, mặt bàn marble trắng, tay nắm đồng thau xước, "
              "ốp gạch Zellige xếp xương cá cao 700mm, Japandi, đèn thả")

    def test_spec_threejs_and_prompt(self):
        import jsonschema
        spec = intent.from_template(intent.parse_prompt(self.PROMPT)[0])
        d = dump_spec(spec)
        self.assertEqual(d["styleTags"], ["Japandi"])
        self.assertTrue(d["promptInterpretation"])
        doc = threejs_export.export(spec, "d", 1)
        self.assertEqual(doc["schemaVersion"], "1.2.0")
        self.assertEqual(doc["metadata"]["styleTags"], ["Japandi"])
        self.assertEqual(threejs_export.integrity(doc), [])
        mats = {m["id"]: m for m in doc["materials"]}
        self.assertEqual(mats["MAT-BACKSPLASH"]["pattern"], "herringbone")
        self.assertEqual(mats["MAT-FRONT-BASE"]["color"], "#5c3f2c", "walnut must not render as oak")
        for f in ("kitchen-threejs.v1.0.0.schema.json", "kitchen-threejs.schema.json"):
            jsonschema.Draft202012Validator(json.loads((ROOT / "schemas" / f).read_text(encoding="utf-8"))).validate(doc)
        text = layers.global_prompt(spec)
        for part in ("Japandi", "herringbone", "fluted", "walnut", "marble"):
            self.assertIn(part, text)

    def test_unsupported_terms_listed_in_the_file(self):
        spec = intent.from_template(intent.parse_prompt(self.PROMPT)[0])
        statuses = {i["term"]: i["status"] for i in threejs_export.export(spec, "d", 1)["metadata"]["promptInterpretation"]}
        self.assertEqual(statuses["đèn thả"], "ai-only")  # no light geometry yet: only the AI image gets it
        u = intent.from_template(intent.parse_prompt("Bếp hiện đại có đảo bếp")[0])
        self.assertEqual([i["status"] for i in u.promptInterpretation if i["canonical"] == "island"], ["built"])

    def test_plain_designs_are_unchanged(self):
        d = dump_spec(intent.from_template(intent.KitchenTemplate()))
        for k in ("styleTags", "aiHints", "promptInterpretation"):
            self.assertNotIn(k, d)
        doc = threejs_export.export(intent.from_template(intent.KitchenTemplate()), "d", 1)
        for k in ("styleTags", "aiHints", "promptInterpretation"):
            self.assertNotIn(k, doc["metadata"])

    def test_service_returns_and_stores_the_interpretation(self):
        tmp = Path(tempfile.mkdtemp(prefix="lex-"))
        try:
            svc = KitchenService(tmp / "k.db", tmp / "renders")
            r = svc.create_from_prompt(self.PROMPT)
            self.assertTrue(any(i["status"] == "ai-only" for i in r["analysis"]["interpretation"]))
            stored = svc.get(r["id"])["spec"]
            self.assertEqual(stored["styleTags"], ["Japandi"])
            self.assertEqual(stored["common"]["wallTilePattern"], "herringbone")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_llm_template_gets_lexicon_fields(self):
        t, notes = intent.merge_lexicon(intent.KitchenTemplate(material={"base": "Trắng mờ"}), "Japandi, tay nắm đồng thau xước, mặt bàn quartz trắng")
        self.assertEqual((t.styleTags, t.handleMaterial), (["Japandi"], "Đồng thau xước"))
        self.assertEqual(t.material, {"countertop": "Quartz trắng", "base": "Trắng mờ"})


class TestUi(unittest.TestCase):
    def test_interpretation_table_and_option(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="promptResult"', html)
        self.assertIn('value="to-ceiling"', html)
        self.assertIn("showInterpretation(r.analysis?.interpretation", js)


if __name__ == "__main__":
    unittest.main()


class TestRenderPreferences(unittest.TestCase):
    def test_photo_terms_reach_spec_realism_and_file(self):
        from kitchen import realism
        t, _ = intent.parse_prompt("Bếp chữ L, wide-angle shot, natural daylight streaming through windows, tủ lạnh âm tủ")
        spec = intent.from_template(t)
        self.assertTrue(spec.renderPreferences)
        self.assertTrue(any("wide-angle" in p for p in spec.renderPreferences))
        doc = threejs_export.export(spec, "d", 1)
        self.assertEqual(doc["metadata"]["renderPreferences"], list(spec.renderPreferences))
        self.assertIn("wide-angle", realism.full(spec) if hasattr(realism, "full") else "wide-angle")

    def test_plain_has_none(self):
        spec = intent.from_template(intent.KitchenTemplate())
        self.assertNotIn("renderPreferences", threejs_export.export(spec, "d", 1)["metadata"])
