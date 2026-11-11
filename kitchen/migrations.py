"""Versioned SQLite migrations, tracked by ``PRAGMA user_version``.

Rules for changing the database:
* Append a step to ``STEPS`` with the next number; never edit or reorder a step that has shipped.
* ``BASELINE`` is the table set as of step 2 and stays frozen: later changes are steps, not edits to it.
* A step is a function ``fn(conn)``. It runs in one transaction together with the version bump, so a failing step leaves the
  database exactly as it was (``atomic=False`` only for steps that need ``executescript``; those must be idempotent).
* Before pending steps run on a database that already holds data, a consistent copy is written next to it (``<db>.bak-v<N>-<time>``).
* A database written by a newer version of the code is refused instead of being guessed at.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import errors, knowledge_seed
from . import legacy as legacy_schema

BASELINE = "\nCREATE TABLE IF NOT EXISTS knowledge (\n id INTEGER PRIMARY KEY AUTOINCREMENT,\n kind TEXT NOT NULL CHECK(kind IN ('standard','rule','material')),\n code TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,\n source_url TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', active INTEGER NOT NULL DEFAULT 1,\n created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);\nCREATE INDEX IF NOT EXISTS idx_knowledge_kind ON knowledge(kind, active);\nCREATE TABLE IF NOT EXISTS designs (\n id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);\nCREATE TABLE IF NOT EXISTS revisions (\n design_id TEXT NOT NULL REFERENCES designs(id), rev INTEGER NOT NULL, spec_json TEXT NOT NULL,\n operation TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n PRIMARY KEY (design_id, rev)\n);\nCREATE TABLE IF NOT EXISTS image_jobs (\n id TEXT PRIMARY KEY, design_id TEXT NOT NULL REFERENCES designs(id), rev INTEGER NOT NULL, view TEXT NOT NULL,\n render_key TEXT NOT NULL, kind TEXT NOT NULL, mode TEXT NOT NULL, target TEXT, backend TEXT NOT NULL,\n status TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT,\n created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);\nCREATE INDEX IF NOT EXISTS idx_image_jobs_design ON image_jobs(design_id, view, render_key, status);\nCREATE TABLE IF NOT EXISTS floorplans (\n ref TEXT PRIMARY KEY, source_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n);\n"


class MigrationError(errors.Infrastructure):
    """A step failed (the database stays at the previous version) or the database is newer than this code."""


@dataclass(frozen=True)
class Step:
    version: int
    name: str
    fn: Callable[[sqlite3.Connection], object]   # what it returns is ignored
    atomic: bool = True


def _create_baseline(conn: sqlite3.Connection) -> None:
    conn.executescript(BASELINE)            # IF NOT EXISTS throughout: safe on databases that already have the tables


def _knowledge_jurisdiction(conn: sqlite3.Connection) -> None:
    knowledge_seed.migrate(conn)            # region / country columns and their index


def _job_ownership(conn: sqlite3.Connection) -> None:
    """Who is running a job and when it last proved it is alive, so a second process does not mistake a live job for a dead one."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(image_jobs)")}
    if "owner" not in cols:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN owner TEXT")
    if "heartbeat_at" not in cols:
        conn.execute("ALTER TABLE image_jobs ADD COLUMN heartbeat_at REAL")


STEPS: list[Step] = [
    Step(1, "english-schema", legacy_schema.migrate_database),
    Step(2, "baseline-tables", _create_baseline, atomic=False),
    Step(3, "knowledge-jurisdiction", _knowledge_jurisdiction),
    Step(4, "job-ownership", _job_ownership),
]
LATEST = STEPS[-1].version


def version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _has_data(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0] > 0


def _backup(conn: sqlite3.Connection, path: str | Path, current: int) -> Path:
    target = Path(f"{path}.bak-v{current}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}")
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def run(conn: sqlite3.Connection, path: str | Path | None = None, steps: list[Step] | None = None) -> dict:
    """Bring the database to the latest version. Returns {"from", "to", "applied": [names], "backup": path | None}."""
    steps = STEPS if steps is None else steps
    latest = steps[-1].version
    current = version(conn)
    if current > latest:
        raise MigrationError(f"The database is at version {current} but this code only knows up to {latest}; update the code instead of opening it with an older one.")
    pending = [s for s in steps if s.version > current]
    result = {"from": current, "to": current, "applied": [], "backup": None}
    if not pending:
        return result
    if path and _has_data(conn):
        result["backup"] = str(_backup(conn, path, current))
    for step in pending:
        try:
            if step.atomic:
                conn.execute("BEGIN IMMEDIATE")
            step.fn(conn)
            if not step.atomic:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"PRAGMA user_version = {int(step.version)}")
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise MigrationError(f"Migration {step.version} ({step.name}) failed: {exc}. The database is still at version {version(conn)}."
                                 + (f" A copy from before the migration: {result['backup']}" if result["backup"] else "")) from exc
        result["applied"].append(step.name)
        result["to"] = step.version
    return result
