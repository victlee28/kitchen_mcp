"""The command inbox on disk: one JSON file per right-click sentence sent to Claude (``menu_commands`` says what a record is).

A plain folder (``KITCHEN_COMMAND_INBOX``, default ``command-inbox/`` beside the database), so the web server that writes a command and the MCP
server Claude reads it with need nothing else in common. Each file is written whole (temporary file, then replace).
"""
from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import menu_commands as mc
from .errors import NotFound


class CommandInbox:
    def __init__(self, root: str | Path, clock: Callable[[], str]):
        self.root = Path(root)
        self.clock = clock

    def _path(self, cid: str) -> Path:
        return self.root / f"{mc.clean_id(cid)}.json"

    def _write(self, record: dict[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(record["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return record

    def _new_id(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        while True:
            cid = f"{stamp}-{secrets.token_hex(2)}"
            if not self._path(cid).exists():
                return cid

    def put(self, design_id: str, text: Any, place: Any, base_rev: Any, lang: Any, reply_to: str | None = None) -> dict[str, Any]:
        """A new command; ``reply_to``: the answered command it answers (marked ``followUp``, and ``replied`` if it asked)."""
        answering = self.get(reply_to) if reply_to is not None else None
        record = self._write(mc.new_record(self._new_id(), design_id, text, place, base_rev, lang, self.clock(), answering))
        if answering is not None:
            self._write(mc.followed(answering, record["id"]))
        return record

    def get(self, cid: str) -> dict[str, Any]:
        path = self._path(cid)
        if not path.exists():
            raise NotFound(f"No command {cid}", code="command-not-found", params={"id": cid})
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, status: str | None = None, design_id: str | None = None) -> list[dict[str, Any]]:
        records = []
        for path in sorted(self.root.glob("*.json")) if self.root.exists() else []:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue                      # a file being replaced right now: read on the next call
        return mc.matching(records, status, design_id)

    def answer(self, cid: str, status: Any, reply: Any, revision: Any = None, choices: Any = None, from_rev: Any = None) -> dict[str, Any]:
        return self._write(mc.answered(self.get(cid), status, reply, revision, self.clock(), choices, from_rev))

    def drop(self, cid: str) -> dict[str, Any]:
        return self._write(mc.dropped(self.get(cid), self.clock()))
