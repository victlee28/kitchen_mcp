"""Agent skills shipped with the app (I/O shell): ``<data dir>/skills/<name>/SKILL.md`` in the open Agent Skills format.

A skill is the procedure an AI follows for one kind of work (``kitchen-inbox``: carrying out the right-click command inbox). It lives in
the data folder, so it ships wherever the app does (exe, Docker) and is versioned with the code. The server hands it out: the background
inbox worker takes its body as instructions, ``list_menu_commands`` / ``get_inbox_skill`` give it to any agent on MCP, so changing the AI
model does not mean explaining the procedure again.

``load`` reads ``SKILL.md`` (YAML-style front matter ``name`` / ``description`` + markdown body) on every call;
``reference`` reads one file of its ``references/`` folder.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")       # the standard's skill name: lower case words joined by hyphens
REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.md$")  # a file directly in references/ (no paths)
MAX_DESCRIPTION = 1024


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str                      # the markdown after the front matter
    version: str                   # sha1 of the whole file, first 12 hex digits: changes whenever the file does
    references: tuple[str, ...]    # the file names in references/


def parse(text: str) -> tuple[dict[str, str], str]:
    """``(front matter, body)`` of a SKILL.md text: ``key: value`` lines between the opening and closing ``---``."""
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta, text
    end = text.find("\n---", 3)
    if end < 0:
        return meta, text
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4:].lstrip("\n")


def folder(name: str, data_dir: Path) -> Path:
    return Path(data_dir) / "skills" / name


def load(name: str, data_dir: Path) -> Skill | None:
    """The skill ``name`` of the data folder, None when it has no SKILL.md. Read on every call (a few kB), so an edit applies at once."""
    path = folder(name, data_dir) / "SKILL.md"
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    meta, body = parse(raw)
    refs = folder(name, data_dir) / "references"
    names = tuple(sorted(p.name for p in refs.glob("*.md"))) if refs.is_dir() else ()
    return Skill(meta.get("name") or name, meta.get("description") or "", body,
                 hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12], names)


def reference(name: str, file: str, data_dir: Path) -> str | None:
    """The text of ``references/<file>`` of the skill ``name``; None for a name that is not a file there."""
    if not REFERENCE.match(file):
        return None
    path = folder(name, data_dir) / "references" / file
    return path.read_text(encoding="utf-8") if path.is_file() else None
