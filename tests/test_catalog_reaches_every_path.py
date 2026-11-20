"""19/11/2026 (claude/kiem-tra-data-driven-19-11.md, group A): the workshop's and user's catalog layers count on every path, not only the
builtin one: a TV unit layout of the workshop, the camera views of a stored revision, the countries and source ranks of the knowledge
search, the image rules of the AI package."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kitchen import builtin, edit, geometry, regions, tv_system  # noqa: E402
from kitchen.intent import KitchenTemplate  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402


class TestCatalogReachesEveryPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="catalog-paths-"))
        cls.svc = KitchenService(cls.tmp / "k.db", cls.tmp / "renders")
        cls.did = cls.svc.create_from_template(KitchenTemplate.model_validate({"geometry_edit": "I", "backWallLength": 3000}), "t")["id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_tv_layouts_are_the_catalogs(self):
        """tv-layout items stand for code (the workshop edits or hides them, it does not add ids): the layouts offered are the catalog's."""
        cat = self.svc.catalog()
        self.assertEqual(set(tv_system.layouts(cat)), set(builtin.CATALOG.ids("tv-layout")))
        self.assertEqual(tv_system.run_fields("shelves", cat)["tvLayout"], "shelves")
        self.assertEqual(tv_system.run_fields("nope", cat)["tvLayout"], "columns", "an unknown layout falls back to columns")
        spec, _ = self.svc.store.get(self.did)
        run = spec.runs[0].id
        tv = edit.apply_op(spec, {"op": "set-run-tv", "id": run, "layout": "full"}, cat)
        self.assertEqual(next(r for r in tv.runs if r.id == run).tvLayout, "full")
        with self.assertRaises(Exception):
            edit.apply_op(spec, {"op": "set-run-tv", "id": run, "layout": "nope"}, cat)

    def test_the_views_of_a_revision_are_built_with_its_catalog(self):
        spec, rev = self.svc.store.get(self.did)
        want = geometry.views_of(spec, self.svc.catalog_for_revision(self.did, rev))
        self.assertEqual(list(self.svc.images.views(self.did, rev)), list(want))

    def test_the_knowledge_search_takes_the_catalog(self):
        rows = self.svc.search_knowledge("", None, "VN", None, False)
        self.assertTrue(rows, "the search runs with the merged catalog")
        self.assertEqual(set(regions.tables(self.svc.catalog()).regions), set(regions.tables().regions))


if __name__ == "__main__":
    unittest.main()
