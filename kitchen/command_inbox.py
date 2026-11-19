"""The command inbox on disk: one JSON file per right-click sentence sent to Claude (``menu_commands`` says what a record is).

A plain folder (``KITCHEN_COMMAND_INBOX``, default ``command-inbox/`` beside the database), so the web server that writes a command and the MCP
server Claude reads it with need nothing else in common. Each file is written whole (temporary file, then replace).

Taking a command (``take``) is atomic across processes: a ``<id>.take`` file created exclusively, removed when the command is answered or
given back; a command ``working`` longer than ``STALE_S`` (its taker stopped) is pending again.
"""
from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import menu_commands as mc
from .errors import InvalidInput, NotFound


STALE_S = 900.0          # a command working this long without an answer was dropped by its taker: pending again


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
        """``YYYYMMDD-HHMMSS-xxxx``; ids made in the same second sort in the order they were made (the queue is carried out by id)."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        same = sorted(p.stem for p in self.root.glob(f"{stamp}-*.json")) if self.root.exists() else []
        low = int(same[-1][-4:], 16) + 1 if same else 0
        while True:
            n = low + secrets.randbelow(16) if same else secrets.randbelow(0x8000)
            cid = f"{stamp}-{min(n, 0xffff):04x}"
            if not self._path(cid).exists():
                return cid
            low = n + 1

    def put(self, design_id: str, text: Any, place: Any, base_rev: Any, lang: Any, reply_to: str | None = None,
            picture: tuple[bytes, str, str] | None = None) -> dict[str, Any]:
        """A new command; ``reply_to``: the answered command it answers (marked ``followUp``, and ``replied`` if it asked). ``picture``:
        ``(bytes, mime, file name)`` of a reference picture sent with it, kept as ``<id>.<ext>`` beside the record (``attachment``)."""
        answering = self.get(reply_to) if reply_to is not None else None
        draft = mc.new_record(self._new_id(), design_id, text, place, base_rev, lang, self.clock(), answering)
        if picture is not None:
            info = mc.picture_info(picture[0], picture[1], picture[2])
            file = f"{draft['id']}.{mc.PICTURE_TYPES[info['mime']]}"
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / file).write_bytes(picture[0])
            draft["attachment"] = {"file": file, **info}
        record = self._write(draft)
        if answering is not None:
            self._write(mc.followed(answering, record["id"]))
        return record

    def get(self, cid: str) -> dict[str, Any]:
        path = self._path(cid)
        if not path.exists():
            raise NotFound(f"No command {cid}", code="command-not-found", params={"id": cid})
        return json.loads(path.read_text(encoding="utf-8"))

    def picture(self, cid: str) -> tuple[bytes, str, dict[str, Any]]:
        """``(bytes, mime, attachment)`` of the reference picture sent with a command; NotFound when it has none."""
        att = self.get(cid).get("attachment")
        if not isinstance(att, dict):
            raise NotFound(f"Command {cid} has no reference picture", code="command-no-picture", params={"id": cid})
        path = self.root / str(att.get("file"))
        if path.parent != self.root or not path.is_file():
            raise NotFound(f"Command {cid} has no reference picture", code="command-no-picture", params={"id": cid})
        return path.read_bytes(), str(att.get("mime") or "image/png"), dict(att)

    def list(self, status: str | None = None, design_id: str | None = None) -> list[dict[str, Any]]:
        records = []
        for path in sorted(self.root.glob("*.json")) if self.root.exists() else []:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue                      # a file being replaced right now: read on the next call
        for i, r in enumerate(records):          # a taker that stopped: its command is pending again
            if r.get("status") == "working" and self._stale(r):
                records[i] = self._write(mc.requeued(r))
                self._release(str(r.get("id")))
        return mc.matching(records, status, design_id)

    def answer(self, cid: str, status: Any, reply: Any, revision: Any = None, choices: Any = None, from_rev: Any = None) -> dict[str, Any]:
        out = self._write(mc.answered(self.get(cid), status, reply, revision, self.clock(), choices, from_rev))
        self._release(cid)
        return out

    def _take_path(self, cid: str) -> Path:
        return self.root / f"{mc.clean_id(cid)}.take"

    def _release(self, cid: str) -> None:
        try:
            self._take_path(cid).unlink()
        except FileNotFoundError:
            pass

    def take(self, cid: str, by: str) -> dict[str, Any]:
        """Take a pending command for ``by`` (``worker`` | ``claude``): it becomes ``working``; refused (``command-taken``) when another one
        took it first, even from another process."""
        record = self.get(cid)
        if record.get("status") == "working" and self._stale(record):
            record = self._write(mc.requeued(record))
            self._release(cid)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self._take_path(cid), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise InvalidInput(f"Command {cid} is being carried out", code="command-taken", params={"id": cid, "worker": "?"}) from None
        os.close(fd)
        try:
            return self._write(mc.started(self.get(cid), by, self.clock()))
        except Exception:
            self._release(cid)
            raise

    def give_back(self, cid: str) -> dict[str, Any]:
        """A taken command not carried out after all (the model could not be reached): pending again."""
        out = self._write(mc.requeued(self.get(cid)))
        self._release(cid)
        return out

    def _stale(self, record: dict[str, Any]) -> bool:
        def when(text: Any) -> datetime | None:
            try:
                at = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
            except ValueError:
                return None
            return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)
        at, now = when(record.get("startedAt")), when(self.clock())
        return at is None or now is None or (now - at).total_seconds() > STALE_S

    def drop(self, cid: str) -> dict[str, Any]:
        return self._write(mc.dropped(self.get(cid), self.clock()))
