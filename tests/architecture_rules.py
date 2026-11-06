"""Static checks for the Rust-readiness rules (CODING_STANDARDS.md, "Portable core"). Pure AST; no imports of the code under test."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KITCHEN = ROOT / "kitchen"

# R1: modules that must stay free of I/O, clocks, randomness and Pydantic behaviour.
CORE_MODULES = (
    "placement", "roomctx", "rules", "rules_kb", "rules_nkba", "edit", "proposal", "geometry", "moldings", "handles", "hardware",
    "structure_mesh", "layers", "floorplan", "threejs_export", "lexicon", "vocab", "regions", "realism", "errors", "palette", "numeric",
)
# Data-model modules a core module may import (the boundary types); everything else it imports from kitchen must be core.
DATA_MODULES = ("spec", "knowledge_seed")   # boundary types; constant data tables (their SQL helpers take a connection argument)

SHELL_MODULES = ("store", "migrations", "service", "backends", "ai_export", "legacy", "config", "intent", "llm")      # touch disk, network, env, clock
PIXEL_MODULES = ("render", "imaging", "geometry_edit", "request_check", "imagejobs", "view_sync")        # numpy / PIL / job orchestration
ENV_READERS = ("config", "service", "backends")                                                # may read os.environ / getenv
ALL_ZONES = CORE_MODULES + DATA_MODULES + SHELL_MODULES + PIXEL_MODULES

FORBIDDEN_IMPORTS = {
    "os", "sqlite3", "pathlib", "threading", "urllib", "http", "subprocess", "time", "datetime", "random", "uuid", "numpy", "PIL",
    "pydantic", "logging", "shutil", "socket", "tempfile", "requests",
}
PYDANTIC_METHODS = {"model_copy", "model_dump", "model_dump_json", "model_validate", "model_validate_json", "model_construct", "parse_obj", "dict_"}
FORBIDDEN_CALLS = {"open", "print", "input"}
FORBIDDEN_ATTR_CALLS = {"read_text", "write_text", "read_bytes", "write_bytes", "mkdir", "getenv", "now", "utcnow", "today"}
UNTYPED_RAISES = {"ValueError", "KeyError", "RuntimeError", "Exception", "TypeError"}
STATE_NAME_HINTS = ("CACHE", "STATE", "REGISTRY", "SINGLETON")


def module_path(name: str) -> Path:
    return KITCHEN / f"{name}.py"


def violations(name: str) -> list[tuple[str, str]]:
    """[(rule, detail)] for one kitchen module, deduplicated and sorted so the allowlist can name them exactly."""
    tree = ast.parse(module_path(name).read_text(encoding="utf-8"), filename=f"kitchen/{name}.py")
    found: set[tuple[str, str]] = set()
    typing_only = {id(n) for top in ast.walk(tree) if isinstance(top, ast.If) and "TYPE_CHECKING" in ast.dump(top.test)
                   for body in top.body for n in ast.walk(body)}          # imports used only for annotations do not count
    for node in ast.walk(tree):
        if id(node) in typing_only:
            continue
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    found.add(("R1-import", top))
        elif isinstance(node, ast.ImportFrom):
            if node.level:                                        # from . import x / from .x import y
                targets = [a.name for a in node.names] if not node.module else [node.module.split(".")[0]]
                for t in targets:
                    if t not in CORE_MODULES and t not in DATA_MODULES and t != name:
                        found.add(("R1-kitchen-import", t))
            else:
                top = (node.module or "").split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    found.add(("R1-import", top))
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in FORBIDDEN_CALLS:
                found.add(("R1-call", f.id))
            elif isinstance(f, ast.Attribute):
                if f.attr in PYDANTIC_METHODS:
                    found.add(("R6-pydantic", f.attr))
                elif f.attr in FORBIDDEN_ATTR_CALLS:
                    found.add(("R1-call", f.attr))
        elif isinstance(node, ast.ExceptHandler):
            t = node.type
            if t is None or (isinstance(t, ast.Name) and t.id in ("Exception", "BaseException")):
                found.add(("R14-broad-except", f"line {node.lineno}"))
        elif isinstance(node, ast.Raise):
            e = node.exc
            nm = e.func.id if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) else e.id if isinstance(e, ast.Name) else None
            if nm in UNTYPED_RAISES:
                found.add(("R14-untyped-raise", nm))
        elif isinstance(node, ast.Global):
            found.add(("R16-global", ",".join(node.names)))
    for node in tree.body:                                         # module-level mutable state
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for t in targets:
            if any(h in t.upper() for h in STATE_NAME_HINTS):
                found.add(("R16-module-state", t))
    return sorted(found)


def round_calls(name: str) -> int:
    """How many builtin ``round(...)`` calls a module still makes (R10: written-out values use numeric.round_half_away)."""
    tree = ast.parse(module_path(name).read_text(encoding="utf-8"))
    return sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "round")


def env_reads(name: str) -> bool:
    text = module_path(name).read_text(encoding="utf-8")
    tree = ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os" and n.attr in ("getenv", "environ"):
            return True
    return False
