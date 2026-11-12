"""The catalog (kitchen.catalog + catalog_files + service): layers, checks, permissions, history, snapshots, wording."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import catalog as cat, catalog_files, i18n  # noqa: E402
from kitchen.errors import InvalidInput, NotFound  # noqa: E402

KINDS = {
    "material": {"label": {"vi": "Vật liệu", "en": "Material"}, "writers": ["workshop", "user"], "usedBy": ["common.material.base", "common.material.upper"]},
    "style": {"label": {"vi": "Phong cách", "en": "Style"}, "writers": ["workshop", "user"], "refs": [["front", "material"]]},
    "appliance": {"label": {"vi": "Thiết bị", "en": "Appliance"}, "writers": ["workshop"]},
    "palette": {"label": {"vi": "Bảng màu", "en": "Palette"}, "writers": [], "locked": True},
}
SCHEMA = {"type": "object", "required": ["name"], "properties": {"name": {"type": "object"}, "hex": {"type": "string", "pattern": "^#[0-9a-f]{6}$"},
                                                               "front": {"type": "string"}}, "additionalProperties": False}
ITEMS = {"material": [{"id": "oak", "name": {"vi": "Gỗ sồi", "en": "Oak"}, "hex": "#c49a6c"}, {"id": "white", "name": {"vi": "Trắng"}, "hex": "#f2f2f0"}],
         "style": [{"id": "warm", "name": {"vi": "Ấm"}, "front": "oak"}], "appliance": [{"id": "hob", "name": {"vi": "Bếp"}}],
         "palette": [{"id": "door", "name": {"vi": "Cánh"}, "hex": "#00ff00"}]}


def write_data(base: Path, kinds=KINDS, items=ITEMS) -> Path:
    data = base / "data"
    (data / "schemas").mkdir(parents=True)
    (data / "items").mkdir()
    (data / "i18n").mkdir()
    (data / "kinds.json").write_text(json.dumps(kinds), encoding="utf-8")
    for k in kinds:
        (data / "schemas" / f"{k}.schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        (data / "items" / f"{k}.json").write_text(json.dumps(items.get(k, [])), encoding="utf-8")
    (data / "i18n" / "vi.json").write_text(json.dumps({"hello": "Chào {name}", "only.vi": "chỉ có tiếng Việt"}), encoding="utf-8")
    (data / "i18n" / "en.json").write_text(json.dumps({"hello": "Hello {name}"}), encoding="utf-8")
    return data


class TestCore(unittest.TestCase):
    def test_layers_override_and_hide(self):
        e = [cat.Entry("material", "oak", "builtin", {"hex": "#1"}), cat.Entry("material", "white", "builtin", {"hex": "#2"}),
             cat.Entry("material", "oak", "user:default", {"hex": "#3"}), cat.Entry("material", "oak", "workshop", {"hex": "#4"}),
             cat.Entry("material", "white", "workshop", {}, disabled=True), cat.Entry("material", "navy", "workshop", {"hex": "#5"})]
        c = cat.merge(e)
        self.assertEqual(c.ids("material"), ["oak", "navy"])                       # builtin order kept, added items after, hidden gone
        self.assertEqual(c.get("material", "oak").data["hex"], "#3")                # user over workshop over builtin
        self.assertEqual(c.get("material", "oak").source, "user:default")
        self.assertEqual(cat.merge(e, ["builtin", "workshop"]).get("material", "oak").data["hex"], "#4")
        with self.assertRaises(NotFound):
            c.get("material", "white")

    def test_refs_and_paths(self):
        kinds = {k: cat.kind_info(k, v) for k, v in KINDS.items()}
        c = cat.merge([cat.Entry("style", "s", "builtin", {"front": "nope"}), cat.Entry("material", "oak", "builtin", {})])
        self.assertEqual([p.to_data() for p in cat.check_refs(c, kinds)], [{"kind": "style", "id": "s", "path": "front", "message": "material 'nope' does not exist"}])
        from kitchen.catalog.check import values_at
        self.assertEqual(values_at({"parts": [{"m": "a"}, {"m": ["b", "c"]}, {}]}, "parts[].m"), ["a", "b", "c"])

    def test_who_may_write(self):
        kinds = {k: cat.kind_info(k, v) for k, v in KINDS.items()}
        cat.check_write(kinds["material"], "user")
        for kind, role in (("appliance", "user"), ("palette", "workshop")):
            with self.assertRaises(InvalidInput):
                cat.check_write(kinds[kind], role)
        self.assertEqual((cat.scope_for("workshop"), cat.scope_for("user")), ("workshop", "user:default"))

    def test_snapshot(self):
        kinds = {k: cat.kind_info(k, v) for k, v in KINDS.items()}
        c = cat.merge([cat.Entry("material", "oak", "builtin", {"hex": "#1"}), cat.Entry("material", "white", "builtin", {})])
        used = cat.used_items({"common": {"material": {"base": "oak", "upper": "Trắng mờ"}}}, c, kinds)
        self.assertEqual([i.id for i in used], ["oak"])                             # free text that names no item is just text
        later = cat.merge([cat.Entry("material", "oak", "builtin", {"hex": "#9"})])
        self.assertEqual(cat.with_snapshot(later, used).get("material", "oak").data["hex"], "#1")

    def test_messages(self):
        m = i18n.Messages({"vi": {"a": "Xin chào {name}", "b": "chỉ vi"}, "en": {"a": "Hi {name}"}})
        self.assertEqual(m.text("a", "en", name="An"), "Hi An")
        self.assertEqual(m.text("b", "en"), "chỉ vi")                               # missing English falls back to Vietnamese
        self.assertEqual(m.text("a", "en"), "Hi {name}")                            # a missing parameter stays visible
        self.assertEqual(m.missing(), {"vi": [], "en": ["b"]})
        self.assertEqual((i18n.pick({"vi": "Gỗ", "en": "Wood"}, "en"), i18n.pick({"vi": "Gỗ"}, "en"), i18n.lang_of("fr")), ("Wood", "Gỗ", "vi"))


class TestFilesAndService(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = write_data(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def svc(self):
        from kitchen.service import KitchenService
        return KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r", data_dir=self.data)

    def test_bad_builtin_stops_the_start(self):
        bad = dict(ITEMS, style=[{"id": "x", "name": {}, "front": "missing"}, {"id": "y", "hex": "red"}])
        shutil.rmtree(self.data)
        write_data(self.tmp, items=bad)
        with self.assertRaises(catalog_files.CatalogInvalid) as ctx:
            catalog_files.load_builtin(self.data)
        text = str(ctx.exception)
        self.assertIn("style x: front: material 'missing' does not exist", text)
        self.assertIn("style.json y: (item): 'name' is a required property", text)

    def test_write_read_undo_reset(self):
        s = self.svc()
        self.assertEqual(s.catalog_put("material", "navy", {"name": {"vi": "Xanh navy"}, "hex": "#22324f"}, "user")["scope"], "user:default")
        self.assertEqual(s.catalog().get("material", "navy").source, "user:default")
        s.catalog_put("material", "oak", {"name": {"vi": "Sồi xưởng"}, "hex": "#aa9966"}, "workshop")
        self.assertEqual(s.catalog().get("material", "oak").data["hex"], "#aa9966")
        s.catalog_put("material", "oak", {"name": {"vi": "Sồi 2"}, "hex": "#aa9977"}, "workshop")
        self.assertEqual(s.catalog_undo("material", "oak", "workshop")["version"], 3)
        self.assertEqual(s.catalog().get("material", "oak").data["hex"], "#aa9966")
        s.catalog_delete("material", "oak", "workshop")
        self.assertEqual(s.catalog().get("material", "oak").data["hex"], "#c49a6c")  # back to the builtin item
        self.assertEqual(len(s.catalog_history("material", "oak")), 4)
        listing = s.catalog_list("material", "user", "en")
        self.assertEqual((listing["label"], [i["id"] for i in listing["items"]]), ("Material", ["oak", "white", "navy"]))

    def test_refused_writes(self):
        s = self.svc()
        cases = [(("appliance", "x", {"name": {}}, "user"), "catalog-not-allowed"), (("palette", "door", {"name": {}}, "workshop"), "catalog-not-allowed"),
                 (("material", "bad id!", {"name": {}}, "user"), "catalog-bad-id"), (("material", "m", {"hex": "#zz"}, "user"), "catalog-invalid"),
                 (("style", "s2", {"name": {}, "front": "nope"}, "user"), "catalog-invalid"), (("material", "oak", {}, "user", True), "catalog-invalid")]
        for args, code in cases:
            with self.assertRaises(InvalidInput, msg=str(args)) as ctx:
                s.catalog_put(*args)
            self.assertEqual(ctx.exception.code, code, args)         # hiding oak would leave style warm pointing at nothing
        with self.assertRaises(NotFound):
            s.catalog_put("nope", "x", {}, "user")

    def test_export_import(self):
        s = self.svc()
        s.catalog_put("material", "navy", {"name": {"vi": "Xanh navy"}}, "workshop")
        s.catalog_put("material", "white", {}, "workshop", disabled=True)
        exported = s.catalog_export("workshop")
        other = Path(tempfile.mkdtemp())
        try:
            from kitchen.service import KitchenService
            t = KitchenService(db_path=other / "k.db", render_dir=other / "r", data_dir=self.data)
            self.assertEqual(t.catalog_import(exported, "workshop"), {"imported": 2})
            self.assertEqual(t.catalog().ids("material"), ["oak", "navy"])
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_revision_keeps_the_items_it_used(self):
        s = self.svc()
        fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        fixture["common"]["material"]["base"] = "oak"
        rec = s.create_from_spec(fixture)
        s.catalog_put("material", "oak", {"name": {"vi": "Sồi mới"}, "hex": "#000000"}, "workshop")
        self.assertEqual(s.catalog_for_revision(rec["id"], 1).get("material", "oak").data["hex"], "#c49a6c")
        self.assertEqual(s.catalog().get("material", "oak").data["hex"], "#000000")

    def test_repository_data_is_valid(self):
        b = catalog_files.load_builtin(ROOT / "data")
        self.assertEqual(b.messages.missing(), {"vi": [], "en": []}, "every wording key in both languages")


class TestAppliancesFromTheCatalog(unittest.TestCase):
    """Stage 1.1: appliance models are catalog items; a model the workshop adds is offered, fitted and exported like a builtin one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")       # the repository's data/

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_workshop_model_is_offered_and_used(self):
        s = self.s
        new = {"type": "cooktop", "name": {"vi": "Bếp từ xưởng 70", "en": "Workshop hob 70"}, "energy": "induction", "size": {"w": 700, "d": 410, "h": 60},
               "cutout": {"w": 560, "d": 380}, "mount": "built_in", "fits": {"hostWidth": 600}, "prompt": "black induction hob"}
        s.catalog_put("appliance", "hob-workshop-70", new, "workshop")
        fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        rec = s.create_from_spec(fixture)
        got = s._replace_appliance(rec["id"], s.store.get(rec["id"])[0], rec["rev"], {"id": "TB4"}, None)
        self.assertIn("hob-workshop-70", [m["id"] for m in got["models"]])
        done = s._replace_appliance(rec["id"], s.store.get(rec["id"])[0], rec["rev"], {"id": "TB4", "model": "hob-workshop-70"}, None)
        self.assertIn("update-appliance", json.dumps(done["operation"]))
        with self.assertRaises(InvalidInput):
            s.catalog_put("appliance", "x", new, "user")                     # users do not edit appliances (decision 11/11/2026)

    def test_tv_from_the_catalog(self):
        from kitchen import tv_system
        self.assertEqual(tv_system.tv_for(1500)["model"], "tv-55")
        bigger = {"type": "tv", "name": {"vi": "Tivi 75 inch"}, "size": {"w": 1680, "d": 30, "h": 960}, "fits": {"nicheFrom": 1900}, "prompt": "75-inch TV"}
        self.s.catalog_put("appliance", "tv-75", bigger, "workshop")
        self.assertEqual(tv_system.tv_for(2000, self.s.catalog())["model"], "tv-75")


class TestMaterialsFromTheCatalog(unittest.TestCase):
    """Stage 1.2: the material words (prompt English, display colours), the 3D looks and the suggested materials are catalog items."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_word_the_user_adds_is_understood(self):
        from kitchen import vocab
        self.assertEqual(vocab.to_english("Laminate xanh bơ"), "laminate")                       # only "xanh" alone is known: not translated
        self.s.catalog_put("material-word", "color-xanh-bo", {"group": "color", "word": "xanh bơ", "hex": "#a8c070", "en": "avocado green"}, "user")
        c = self.s.catalog()
        self.assertIn("avocado green", vocab.to_english("Laminate xanh bơ", c))
        self.assertEqual(vocab.color("xanh bơ", c), "#a8c070")
        with self.assertRaises(InvalidInput):                                                    # a colour needs its display colour
            self.s.catalog_put("material-word", "color-x", {"group": "color", "word": "x", "en": "x"}, "user")

    def test_old_revisions_keep_their_words_and_looks(self):
        fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        rec = self.s.create_from_spec(fixture)
        before = self.s.threejs(rec["id"], rec["rev"])
        self.s.catalog_put("material-look", "wood", {"any": ["sồi", "oak", "gỗ"], "look": {"color": "#000000", "roughness": 0.6}}, "workshop")
        self.s.catalog_put("material-word", "wood-soi", {"group": "wood", "word": "sồi", "hex": "#000001", "en": "oak wood"}, "user")
        old = self.s.catalog_for_revision(rec["id"], rec["rev"])
        self.assertEqual(old.data("material-look", "wood")["look"]["color"], "#c49a6c")
        self.assertEqual(self.s.threejs(rec["id"], rec["rev"])["materials"], before["materials"])
        new = self.s.create_from_spec(fixture)
        mats = {m["id"]: m for m in self.s.threejs(new["id"], new["rev"])["materials"]}
        self.assertEqual(mats["MAT-FRONT-BASE"]["color"], "#000001")                              # "Laminate vân gỗ sồi sáng": the oak word now

    def test_suggested_materials(self):
        texts = [i["data"]["text"] for i in self.s.catalog_list("material", "user")["items"]]
        self.assertIn("Laminate xanh rêu mờ", texts)


class TestStylesFromTheCatalog(unittest.TestCase):
    """Stage 1.3: the style presets of a whole cabinet system are catalog items (workshop and user)."""

    def test_a_user_style_restyles_a_system(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            from kitchen import runs
            from kitchen.service import KitchenService
            s = KitchenService(db_path=tmp / "k.db", render_dir=tmp / "r")
            s.catalog_put("style", "my-blue", {"name": {"vi": "Xanh của tôi"}, "front": "Sơn xanh navy mờ", "door": "frame", "handle": "knob",
                                               "handleMaterial": "Đồng thau"}, "user")
            fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
            rec = s.create_from_spec(fixture)
            spec = s.store.get(rec["id"])[0]
            system = next(iter(runs.systems(spec).values()))
            got = s._replace_system(spec, system, None, "my-blue", None, s.catalog())
            self.assertEqual(got["style"], "my-blue")
            self.assertIn("Sơn xanh navy mờ", json.dumps(got["operation"], ensure_ascii=False))
            with self.assertRaises(InvalidInput):
                s._replace_system(spec, system, None, "my-blue", None)                  # not in the builtin catalog
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestBackendsFromTheCatalog(unittest.TestCase):
    """Stage 1.5: image backends and recognizers are closed catalog kinds: the workshop renames, reorders or hides them, never adds one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_hide_rename_and_no_new_ones(self):
        s = self.s
        self.assertEqual(list(s.image_backends()["backends"]), ["recolor", "job-package", "gemini"])
        s.catalog_put("backend", "recolor", {}, "workshop", disabled=True)
        b = s.catalog().data("backend", "gemini")
        s.catalog_put("backend", "gemini", {**b, "name": {"vi": "Gemini của xưởng"}, "rank": 0}, "workshop")
        offered = s.image_backends()["backends"]
        self.assertEqual(list(offered), ["gemini", "job-package"])
        self.assertEqual(offered["gemini"]["name"], "Gemini của xưởng")
        with self.assertRaises(InvalidInput) as e:
            s.catalog_put("backend", "midjourney", {"name": {"vi": "MJ"}, "kind": ["edit"]}, "workshop")
        self.assertEqual(e.exception.code, "catalog-closed-kind")

    def test_recognizer_preference(self):
        from kitchen import recognition
        self.assertEqual(recognition.choose_recognizer(["gemini", "inbox"], None, None), "inbox")
        self.s.catalog_put("recognizer", "inbox", {}, "workshop", disabled=True)
        c = self.s.catalog()
        self.assertEqual(recognition.choose_recognizer(["gemini", "inbox"], None, None, c), "gemini")
        self.assertIsNone(recognition.choose_recognizer(["gemini", "inbox"], "inbox", None, c))
        self.assertEqual(recognition.choose_recognizer(["fake"], None, None, c), "fake")              # a plug-in under its own name


class TestCsvAndPreview(unittest.TestCase):
    """Stage 1.7: a kind as CSV and back (the workshop's real appliance list), and trying a material name."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_appliances_round_trip(self):
        from kitchen import catalog_csv
        text = self.s.catalog_csv("appliance")["csv"]
        back = dict(catalog_csv.from_csv(text, self.s.builtin.schemas["appliance"]))
        for it in self.s.catalog().all("appliance"):
            self.assertEqual(json.dumps(back[it.id], sort_keys=True), json.dumps(dict(it.data), sort_keys=True), it.id)   # ints stay ints

    def test_import_checks_every_row_first(self):
        head = "id,type,name.vi,size.w,size.d,size.h,prompt\n"
        good = "hob-x,cooktop,Bếp X,700,400,60,black hob\n"
        with self.assertRaises(InvalidInput):
            self.s.catalog_csv_import("appliance", head + good + "hob-y,cooktop,Bếp Y,rộng,400,60,x\n", "workshop")
        self.assertIsNone(self.s.catalog().find("appliance", "hob-x"))                                 # nothing written
        with self.assertRaises(InvalidInput):
            self.s.catalog_csv_import("appliance", head + good, "user")                                  # users do not edit appliances
        self.assertEqual(self.s.catalog_csv_import("appliance", head + good, "workshop")["imported"], 1)
        self.assertEqual(self.s.catalog().data("appliance", "hob-x")["size"], {"w": 700, "d": 400, "h": 60})

    def test_material_preview(self):
        r = self.s.material_preview("Laminate xanh rêu mờ")
        self.assertEqual(r["english"], "sage green matte finish laminate")
        self.assertEqual(r["look"]["color"], "#7d8a5f")


class TestDefaultsFromTheCatalog(unittest.TestCase):
    """Stage 2.1: the workshop's default sizes and limits (catalog kind defaults, one item) change what is made, not what is stored."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _set(self, **sections):
        d = json.loads(json.dumps(dict(self.s.catalog().data("defaults", "default"))))
        for k, v in sections.items():
            d[k].update(v)
        self.s.catalog_put("defaults", "default", d, "workshop")

    def test_split_and_new_design(self):
        from kitchen import cabinet_run, defaults
        self.assertEqual(cabinet_run.split_widths(1900), [600, 600, 700])
        self._set(run={"moduleWidth": 450}, newDesign={"doorThickness": 20, "cabinetTop": 2300})
        c = self.s.catalog()
        self.assertEqual(defaults.of(c).module_width, 450)
        self.assertEqual(cabinet_run.split_widths(1900, c), [450, 450, 450, 550])
        spec = self.s.store.get(self.s.create_from_prompt("bếp chữ I dài 3m")["id"])[0]
        self.assertEqual(spec.common.doorThickness, 20)
        self.assertEqual(spec.common.cabinetTop, 2300)

    def test_only_the_workshop_and_no_second_item(self):
        d = dict(self.s.catalog().data("defaults", "default"))
        with self.assertRaises(InvalidInput):
            self.s.catalog_put("defaults", "default", d, "user")
        with self.assertRaises(InvalidInput):
            self.s.catalog_put("defaults", "other", d, "workshop")

    def test_stretch_limit(self):
        from kitchen import defaults
        self._set(stretch={"max": 900})
        self.assertEqual(defaults.of(self.s.catalog()).stretch_max, 900)


class TestRegionsFromTheCatalog(unittest.TestCase):
    """Stage 2.2: regions, countries (and the words naming them), source types and check topics are catalog items."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_workshop_adds_a_country(self):
        from kitchen import regions
        with self.assertRaises(InvalidInput):
            regions.normalize("KH")
        self.s.catalog_put("country", "KH", {"name": {"vi": "Campuchia", "en": "Cambodia"}, "region": "SEA", "keywords": ["campuchia"]}, "workshop")
        c = self.s.catalog()
        self.assertEqual(regions.normalize("KH", None, c), ("KH", "SEA"))
        self.assertEqual(regions.from_description("bếp chuẩn Campuchia", c), ("KH", "SEA"))
        self.assertIn("KH", self.s.list_regions()["country"])
        with self.assertRaises(InvalidInput):                                             # its region must exist
            self.s.catalog_put("country", "XX", {"name": {"vi": "X"}, "region": "MARS"}, "workshop")

    def test_hiding_a_topic_drops_its_check(self):
        fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        rec = self.s.create_from_spec(fixture)
        spec = self.s.store.get(rec["id"])[0]
        topics = {i.get("topic") for i in self.s.validate_spec(spec)["issues"]}
        some = next(t for t in topics if t)
        self.s.catalog_put("rule-topic", some, {}, "workshop", disabled=True)
        self.assertNotIn(some, {i.get("topic") for i in self.s.validate_spec(spec)["issues"]})


class TestKnowledgeInTheCatalog(unittest.TestCase):
    """Stage 2.3: the knowledge table is the catalog kind "knowledge" (builtin = knowledge_seed, workshop layer, history, undo)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _codes(self):
        return {r["code"] for r in self.s.search_knowledge("", ["rule", "standard"])}

    def test_edit_hide_reset(self):
        s = self.s
        hood = dict(s.catalog().data("knowledge", "HOOD-001"))
        s.catalog_put("knowledge", "HOOD-001", {**hood, "title": "Hút mùi của xưởng"}, "workshop")
        self.assertEqual(s.store.knowledge_rows_all()["HOOD-001"]["title"], "Hút mùi của xưởng")          # the table follows
        s.catalog_put("knowledge", "HOOD-001", {}, "workshop", disabled=True)
        self.assertNotIn("HOOD-001", self._codes())
        s.catalog_delete("knowledge", "HOOD-001", "workshop")
        self.assertIn("HOOD-001", self._codes())
        self.assertEqual(s.store.knowledge_rows_all()["HOOD-001"]["title"], hood["title"])                  # back to the builtin text
        with self.assertRaises(InvalidInput):
            s.catalog_put("knowledge", "HOOD-001", hood, "user")

    def test_old_api_writes_the_catalog(self):
        self.s.add_knowledge(kind="rule", code="XUONG-01", title="Luật xưởng", content="x", region="SEA", country="VN")
        self.assertEqual(self.s.catalog().data("knowledge", "XUONG-01")["country"], "VN")
        self.assertIn("XUONG-01", self._codes())
        self.assertEqual(len(self.s.catalog_history("knowledge", "XUONG-01")), 1)

    def test_a_restart_adopts_table_rows(self):
        from kitchen.service import KitchenService
        self.s.store.knowledge_sync("HAND-01", {"kind": "rule", "title": "Thêm tay", "content": "", "source_url": "", "region": "GLOBAL",
                                               "country": "", "metadata": {}})
        again = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")
        self.assertEqual(again.catalog().get("knowledge", "HAND-01").source, "workshop")


class TestMoldingProfilesFromTheCatalog(unittest.TestCase):
    """Stage 2.4: molding profiles are catalog items; a design carries any profile that is not exactly a builtin one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from kitchen.service import KitchenService
        self.s = KitchenService(db_path=self.tmp / "k.db", render_dir=self.tmp / "r")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_user_profile_travels_with_the_design(self):
        s = self.s
        mine = {"name": {"vi": "Phào của tôi"}, "variant": "crown", "points": [[-40, 0], [0, 0], [20, 40], [-40, 40]]}
        s.catalog_put("molding-profile", "my-crown", mine, "user")
        self.assertIn("my-crown", s.molding_profiles())
        fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        rec = s.create_from_spec(fixture)
        done = s.set_moldings(rec["id"], rec["rev"], crown_profile="my-crown")
        spec = s.store.get(rec["id"], done["rev"])[0]
        self.assertEqual([p.id for p in spec.moldingProfiles], ["my-crown"])
        s.catalog_put("molding-profile", "my-crown", {**mine, "points": [[-40, 0], [0, 0], [0, 80], [-40, 80]]}, "user")
        self.assertEqual(s.store.get(rec["id"], done["rev"])[0].moldingProfiles[0].height, 40)              # the design keeps its copy

    def test_builtin_profiles_are_not_copied(self):
        fixture = json.loads((ROOT / "fixtures" / "l-shaped-kitchen.json").read_text(encoding="utf-8"))
        rec = self.s.create_from_spec(fixture)
        done = self.s.set_moldings(rec["id"], rec["rev"])
        self.assertEqual(self.s.store.get(rec["id"], done["rev"])[0].moldingProfiles, [])


if __name__ == "__main__":
    unittest.main()
