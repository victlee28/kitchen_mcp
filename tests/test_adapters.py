"""server.py (MCP) and web_server.py (HTTP) are adapters: they parse input, call ONE service method and shape the reply.

These checks keep business logic from leaking into them and keep the two adapters honest about what the service offers.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kitchen.imagejobs import ImageJobs  # noqa: E402
from kitchen.service import KitchenService  # noqa: E402

ADAPTERS = ("server.py", "web_server.py")
ALLOWED_KITCHEN_IMPORTS = {"kitchen.service", "kitchen.store", "kitchen.intent", "kitchen.errors"}  # the facade, its error types, the template type MCP exposes
SERVICE_NAMES = {"svc", "s", "SVC"}


def _tree(name: str) -> ast.AST:
    return ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)


def _service_calls(tree: ast.AST) -> set[tuple[str, ...]]:
    """Attribute paths below the service object: svc().a.b(...) -> ('a', 'b'); s.images.get(...) -> ('images', 'get')."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        chain, cur = [], node
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        root = cur.func if isinstance(cur, ast.Call) else cur
        if isinstance(root, ast.Name) and root.id in SERVICE_NAMES and (isinstance(cur, ast.Call) or root.id in ("s", "SVC")):
            found.add(tuple(reversed(chain)))
    return found


class TestAdapterBoundary(unittest.TestCase):
    def test_adapters_import_no_business_modules(self):
        for name in ADAPTERS:
            for node in ast.walk(_tree(name)):
                if isinstance(node, ast.ImportFrom) and node.module == "kitchen":
                    mods = [f"kitchen.{a.name}" for a in node.names]  # `from kitchen import x` is the module kitchen.x
                else:
                    mods = [node.module] if isinstance(node, ast.ImportFrom) and node.module else [a.name for a in node.names] if isinstance(node, ast.Import) else []
                for m in mods:
                    if m.split(".")[0] == "kitchen":
                        self.assertIn(m, ALLOWED_KITCHEN_IMPORTS, f"{name} imports {m}: move that work into the service")

    def test_adapters_do_not_import_dynamically(self):
        for name in ADAPTERS:
            for node in ast.walk(_tree(name)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    self.fail(f"{name} uses __import__: it hides a business import from this check")

    def test_adapters_do_not_reach_into_service_internals(self):
        banned = {"store", "render_dir", "db_path"}
        for name in ADAPTERS:
            for path in _service_calls(_tree(name)):
                self.assertFalse(banned & {path[0]}, f"{name} uses service.{'.'.join(path)}; add a service method instead")

    def test_every_adapter_call_exists_on_the_service(self):
        for name in ADAPTERS:
            for path in _service_calls(_tree(name)):
                if path == ("images",):
                    continue
                if path[0] == "images":
                    self.assertTrue(hasattr(ImageJobs, path[1]), f"{name}: ImageJobs has no {path[1]}")
                elif len(path) == 1:
                    self.assertTrue(hasattr(KitchenService, path[0]), f"{name}: KitchenService has no {path[0]}")

    def test_mcp_tools_and_http_routes_cover_the_same_floorplan_and_view_sync_features(self):
        """A feature added to one adapter must be reachable from the other."""
        mcp = {p for p in _service_calls(_tree("server.py"))}
        http = {p for p in _service_calls(_tree("web_server.py"))}
        for feature in (("import_floorplan",), ("bind_floorplan",), ("list_floorplan_rooms",), ("images", "view_status"), ("images", "regenerate_stale"), ("propose",)):
            self.assertIn(feature, mcp, f"MCP lacks {feature}")
            self.assertIn(feature, http, f"HTTP lacks {feature}")


if __name__ == "__main__":
    unittest.main()
