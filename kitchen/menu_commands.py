"""Right-click sentences sent to Claude instead of the server's own reader (the command inbox). Pure (rule R1): the records, what they
may hold and how an answer changes them; ``command_inbox`` keeps them on disk.

A record::

    {"id": "20261116-151500-a1b2", "designId", "text", "place": {...}, "baseRev", "lang", "createdAt",
     "status": "pending" | "done" | "failed" | "question" | "dropped" | "replied", "reply"?, "choices"?, "revision"?, "fromRev"?,
     "answeredAt"?, "replyTo"?, "context"?, "followUp"?}

Claude's answer may offer ``choices`` (short sentences the user can pick instead of typing) and say ``fromRev``, the revision before
its change (the menu's undo goes back to it). The user's answer to it is a new command with ``replyTo`` (the answered command) and
``context`` (that command's sentence and Claude's reply); the answered command then carries ``followUp`` and, if it was a question,
the status ``replied``.

``place`` says what was right-clicked, as the menu knows it: ``kind`` (module | part | group | appliance | structure | floor | opening),
``id``, ``part`` (door | drawer | handle | countertop), ``point`` {x, z} (the wall-axis frame, as the menu sends to /opening-command),
``structureId`` (a floorplan element), ``module``, ``modules`` (a Shift-selected group), ``surfaces`` (wall faces picked first),
``title`` (the menu's own heading, for the reader).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .errors import InvalidInput
from .jsonview import as_dict, as_list
from .numeric import round_half_away

ID = re.compile(r"^\d{8}-\d{6}-[a-z0-9]{4}$")
STATUSES = ("pending", "done", "failed", "question", "dropped", "replied")
ANSWERS = ("done", "failed", "question")         # what Claude may set; "dropped" is the user's
KINDS = ("module", "part", "group", "appliance", "structure", "floor", "opening")
PARTS = ("door", "drawer", "handle", "countertop")
MAX_TEXT = 500
MAX_REPLY = 2000
MAX_LIST = 50
MAX_CHOICES = 6
MAX_CHOICE = 160
NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
SURFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}#[A-Za-z0-9_-]{1,20}$")     # a wall face: "<wall>#<face>" (wall_surfaces)


def clean_id(value: Any) -> str:
    """A command id as it goes into a file name; anything else is refused."""
    if not isinstance(value, str) or not ID.match(value):
        raise InvalidInput("Not a command id", code="command-bad-id", params={"id": str(value)[:40]})
    return value


def _name(value: Any) -> str | None:
    return value if isinstance(value, str) and NAME.match(value) else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 1e7 else None


def clean_place(raw: Any) -> dict[str, Any]:
    """What was right-clicked, keeping only the known fields with sane values (the record is read by a person and by Claude)."""
    d = as_dict(raw) or {}
    out: dict[str, Any] = {}
    if d.get("kind") in KINDS:
        out["kind"] = d["kind"]
    if d.get("part") in PARTS:
        out["part"] = d["part"]
    for key in ("id", "structureId", "module"):
        v = _name(d.get(key))
        if v is not None:
            out[key] = v
    pt = as_dict(d.get("point")) or {}
    x, z = _number(pt.get("x")), _number(pt.get("z"))
    if x is not None and z is not None:
        out["point"] = {"x": round_half_away(x, 1), "z": round_half_away(z, 1)}
    for key, ok in (("modules", NAME), ("surfaces", SURFACE)):
        items = [x for x in (as_list(d.get(key)) or [])[:MAX_LIST] if isinstance(x, str) and ok.match(x)]
        if items:
            out[key] = items
    title = d.get("title")
    if isinstance(title, str) and title.strip():
        out["title"] = title.strip()[:120]
    return out


def _rev(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def clean_choices(raw: Any) -> list[str]:
    """Claude's offered answers: up to ``MAX_CHOICES`` non-empty sentences of at most ``MAX_CHOICE`` characters, without repeats."""
    out: list[str] = []
    for v in (as_list(raw) or [])[:MAX_CHOICES]:
        if isinstance(v, str) and v.strip() and v.strip()[:MAX_CHOICE] not in out:
            out.append(v.strip()[:MAX_CHOICE])
    return out


def new_record(cid: str, design_id: str, text: Any, place: Any, base_rev: Any, lang: Any, now: str,
               answering: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A pending command: the sentence (trimmed, at most ``MAX_TEXT``), what was clicked and the revision it was said on. ``answering``:
    the answered command this one replies to (same design; its place is used when the reply names none)."""
    sentence = text.strip() if isinstance(text, str) else ""
    if not sentence:
        raise InvalidInput("Type a command first", code="command-empty")
    if len(sentence) > MAX_TEXT:
        raise InvalidInput(f"A command has at most {MAX_TEXT} characters", code="command-too-long", params={"max": MAX_TEXT})
    out: dict[str, Any] = {"id": clean_id(cid), "designId": design_id, "text": sentence, "place": clean_place(place), "baseRev": _rev(base_rev),
                           "lang": lang if lang in ("vi", "en") else "vi", "createdAt": now, "status": "pending"}
    if answering is not None:
        if answering.get("designId") != design_id:
            raise InvalidInput("A reply goes to a command of the same design", code="command-reply-design",
                               params={"id": str(answering.get("id"))})
        if answering.get("status") not in ANSWERS:
            raise InvalidInput(f"Command {answering.get('id')} has no answer to reply to", code="command-reply-open",
                               params={"id": str(answering.get("id")), "status": str(answering.get("status"))})
        out["replyTo"] = str(answering.get("id"))
        out["context"] = {"text": str(answering.get("text") or ""), "reply": str(answering.get("reply") or ""),
                          "status": str(answering.get("status"))}
        if not out["place"]:
            out["place"] = clean_place(answering.get("place"))
    return out


def followed(record: Mapping[str, Any], follow_id: str) -> dict[str, Any]:
    """The answered command once the user replied to it: ``followUp`` = the reply's id; a question becomes ``replied``."""
    return {**record, "followUp": follow_id, **({"status": "replied"} if record.get("status") == "question" else {})}


def answered(record: Mapping[str, Any], status: Any, reply: Any, revision: Any, now: str, choices: Any = None,
             from_rev: Any = None) -> dict[str, Any]:
    """The record once Claude answered it: ``done`` (carried out; ``revision`` = the design's revision after it, ``from_rev`` = the one
    before), ``failed`` (could not), ``question`` (needs the user: ``reply`` asks it). ``choices``: answers the user can pick (with any
    status: a question's options, or other ways a done change could have gone). Only a pending command or one waiting on a question is
    answered."""
    if status not in ANSWERS:
        raise InvalidInput(f"status must be one of {', '.join(ANSWERS)}", code="command-bad-status", params={"status": str(status)[:20]})
    if record.get("status") not in ("pending", "question"):
        raise InvalidInput(f"Command {record.get('id')} is already {record.get('status')}", code="command-closed",
                           params={"id": str(record.get("id")), "status": str(record.get("status"))})
    text = reply.strip()[:MAX_REPLY] if isinstance(reply, str) else ""
    out = {**record, "status": status, "reply": text, "answeredAt": now}
    for key, value in (("revision", _rev(revision)), ("fromRev", _rev(from_rev) if status == "done" else None)):
        if value is not None:
            out[key] = value
        else:
            out.pop(key, None)
    picks = clean_choices(choices)
    if picks:
        out["choices"] = picks
    else:
        out.pop("choices", None)
    return out


def dropped(record: Mapping[str, Any], now: str) -> dict[str, Any]:
    """The user took the command back before Claude did it (an answered one is only hidden: it stays as it was)."""
    if record.get("status") != "pending":
        return dict(record)
    return {**record, "status": "dropped", "answeredAt": now}


def matching(records: list[Mapping[str, Any]], status: str | None = None, design_id: str | None = None) -> list[dict[str, Any]]:
    """The records with that status / of that design, oldest first."""
    if status is not None and status not in STATUSES:
        raise InvalidInput(f"status must be one of {', '.join(STATUSES)}", code="command-bad-status", params={"status": status[:20]})
    keep = [dict(r) for r in records if (status is None or r.get("status") == status) and (design_id is None or r.get("designId") == design_id)]
    return sorted(keep, key=lambda r: str(r.get("id")))
