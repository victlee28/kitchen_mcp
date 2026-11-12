"""SQLite persistence for designs, revisions, image jobs, and knowledge."""
from __future__ import annotations
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from typing import Callable
from pathlib import Path
from . import errors, knowledge_seed, migrations, regions
from .spec import KitchenSpec, dump_spec
from .errors import InvalidInput, NotFound
SCHEMA = migrations.BASELINE   # frozen baseline; changes go in kitchen/migrations.py

class ConflictError(errors.Conflict):
    """The supplied base revision is no longer the latest revision."""
    default_code = "revision-conflict"

def _slug(text: str) -> str:
    normalized_text = unicodedata.normalize('NFD', text.lower()).replace('đ', 'd')
    normalized_text = ''.join((ch for ch in normalized_text if unicodedata.category(ch) != 'Mn'))
    return re.sub('[^a-z0-9]+', '-', normalized_text).strip('-')[:32] or 'kitchen-design'

class Store:

    HEARTBEAT_S = 10.0       # a process that runs jobs says "still alive" this often
    STALE_AFTER_S = 45.0     # a running job whose owner has been silent this long is declared interrupted

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        self.owner = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"      # one id per Store instance, never reused by another process
        self._beat: threading.Thread | None = None
        self._beat_lock = threading.Lock()
        self.snapshot: Callable[[KitchenSpec], str | None] | None = None   # set by the service: the catalog items a revision uses (JSON)
        with self._conn() as connection:
            self.migration = migrations.run(connection, self.path)
            self.seed_result = knowledge_seed.apply(connection)

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def knowledge(self, query: str='', kinds: list[str] | None=None, country: str | None=None, region: str | None=None, region_only: bool=False, **legacy) -> list[dict]:
        """Search and rank knowledge entries by query and jurisdiction."""
        country = legacy.pop('country', country)
        region = legacy.pop('region', region)
        region_only = legacy.pop('region_only', region_only)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        country_code, region_code = regions.normalize(country, region)
        conditions, parameters = (['active=1'], [])
        terms = [term for term in re.split('\\s+', query.strip()) if len(term) >= 2]
        if terms:
            alternatives = []
            for term in terms:
                alternatives.append('(title LIKE ? OR content LIKE ? OR code LIKE ?)')
                parameters += [f'%{term}%'] * 3
            conditions.append('(' + ' OR '.join(alternatives) + ')')
        if kinds:
            conditions.append('kind IN (%s)' % ','.join('?' * len(kinds)))
            parameters += kinds
        with self._conn() as connection:
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM knowledge WHERE {' AND '.join(conditions)} ORDER BY kind, id", parameters)]
        results = []
        for row in rows:
            row['metadata'] = json.loads(row.pop('metadata_json') or '{}')
            priority_score = regions.priority_score(row, country_code, region_code)
            if region_only and (country_code or region_code) and (priority_score < 10):
                continue
            text = f"{row['title']} {row['content']} {row['code']}".lower()
            row['_kw'] = sum((term.lower() in text for term in terms))
            row['_d'] = priority_score
            row['priority'] = regions.priority_label(priority_score) if country_code or region_code else None
            results.append(row)
        source_rank = regions.SOURCE_RANK
        results.sort(key=lambda row: (-row['_d'], -row['_kw'], -source_rank.get(row['metadata'].get('sourceType', 'unknown'), 0), row['id']))
        for row in results:
            row.pop('_kw')
            row.pop('_d')
            if row['priority'] is None:
                row.pop('priority')
        return results

    def upsert_knowledge(self, kind: str, code: str, title: str, content: str, source_url: str='', metadata: dict | None=None, region: str='GLOBAL', country: str='', **legacy) -> dict:
        region = legacy.pop('region', region)
        country = legacy.pop('country', country)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        region_code = (region or 'GLOBAL').upper()
        if region_code not in regions.REGIONS:
            raise InvalidInput(f"region must be one of: {', '.join(regions.REGIONS)}", code="bad-region", params={"code": region_code, "allowed": ', '.join(regions.REGIONS)})
        country_codes = [value.strip().upper() for value in (country or '').split(',') if value.strip()]
        for country_code in country_codes:
            regions.normalize(country_code)
        country_code = ','.join(country_codes)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._conn() as connection:
            row = connection.execute('SELECT id FROM knowledge WHERE code=? AND active=1', (code,)).fetchone()
            if row:
                connection.execute('UPDATE knowledge SET kind=?, title=?, content=?, source_url=?, metadata_json=?, region=?, country=? WHERE id=?', (kind, title, content, source_url, metadata_json, region_code, country_code, row['id']))
                return {'ok': True, 'code': code, 'operation': 'update', 'region': region_code, 'country': country_code}
            connection.execute('INSERT INTO knowledge(kind,code,title,content,source_url,metadata_json,region,country) VALUES(?,?,?,?,?,?,?,?)', (kind, code, title, content, source_url, metadata_json, region_code, country_code))
            return {'ok': True, 'code': code, 'operation': 'add-new', 'region': region_code, 'country': country_code}

    def knowledge_rows_all(self) -> dict[str, dict]:
        """Every row of the knowledge table by code (the newest row of a code), active or not, metadata parsed."""
        with self._conn() as connection:
            rows = [dict(r) for r in connection.execute('SELECT * FROM knowledge ORDER BY id')]
        out: dict[str, dict] = {}
        for row in rows:
            row['metadata'] = json.loads(row.pop('metadata_json') or '{}')
            out[row['code']] = row
        return out

    def knowledge_sync(self, code: str, row: dict | None) -> None:
        """Make the table say what the catalog says for ``code``: ``row`` (kind, title, content, source_url, region, country, metadata) in force,
        or None = not in force (the row is kept, inactive)."""
        with self._conn() as connection:
            if row is None:
                connection.execute('UPDATE knowledge SET active=0 WHERE code=?', (code,))
                return
            values = (row['kind'], row['title'], row['content'], row['source_url'], json.dumps(row['metadata'], ensure_ascii=False),
                      row['region'], row['country'])
            hit = connection.execute('SELECT id FROM knowledge WHERE code=? ORDER BY active DESC, id DESC LIMIT 1', (code,)).fetchone()
            if hit:
                connection.execute('UPDATE knowledge SET kind=?, title=?, content=?, source_url=?, metadata_json=?, region=?, country=?, active=1 '
                                   'WHERE id=?', (*values, hit['id']))
            else:
                connection.execute('INSERT INTO knowledge(kind,title,content,source_url,metadata_json,region,country,code) VALUES(?,?,?,?,?,?,?,?)',
                                   (*values, code))

    def regions_summary(self) -> list[dict]:
        with self._conn() as connection:
            rows = connection.execute('SELECT region, country, kind, COUNT(*) n FROM knowledge WHERE active=1 GROUP BY 1,2,3 ORDER BY 1,2,3').fetchall()
        return [dict(row) for row in rows]

    def set_active(self, code: str, active: bool) -> int:
        with self._conn() as connection:
            return connection.execute('UPDATE knowledge SET active=? WHERE code=?', (int(active), code)).rowcount

    def rule_rows(self) -> list[dict]:
        return self.knowledge('', ['rule', 'standard'])

    def create_design(self, spec: KitchenSpec, source: str='', catalog_json: str | None=None, **legacy) -> dict:
        source = legacy.pop('source', source)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        design_id = f'{_slug(spec.name)}-{uuid.uuid4().hex[:6]}'
        catalog_json = catalog_json or self._snap(spec)          # before taking the lock: the snapshot reads the catalog rows
        with self._conn() as connection:
            connection.execute('INSERT INTO designs(id, name) VALUES(?,?)', (design_id, spec.name))
            connection.execute('INSERT INTO revisions(design_id, rev, spec_json, operation, source, catalog_json) VALUES(?,?,?,?,?,?)', (design_id, 1, json.dumps(dump_spec(spec), ensure_ascii=False), json.dumps({'op': 'create'}), source, catalog_json))
        return {'id': design_id, 'rev': 1}

    def put_floorplan(self, ref: str, data: dict) -> None:
        """Keep the original floorplan document once, under its content hash; revisions only carry the ref."""
        with self._conn() as connection:
            connection.execute('INSERT OR IGNORE INTO floorplans(ref, source_json) VALUES(?,?)', (ref, json.dumps(data, ensure_ascii=False)))

    def get_floorplan(self, ref: str) -> dict:
        with self._conn() as connection:
            row = connection.execute('SELECT source_json FROM floorplans WHERE ref=?', (ref,)).fetchone()
        if not row:
            raise NotFound(f"Floorplan '{ref}' was not found", code="floorplan-not-found", params={"id": ref})
        return json.loads(row['source_json'])

    def get(self, design_id: str, rev: int | None=None) -> tuple[KitchenSpec, int]:
        with self._conn() as connection:
            if rev is None:
                row = connection.execute('SELECT rev, spec_json FROM revisions WHERE design_id=? ORDER BY rev DESC LIMIT 1', (design_id,)).fetchone()
            else:
                row = connection.execute('SELECT rev, spec_json FROM revisions WHERE design_id=? AND rev=?', (design_id, rev)).fetchone()
        if not row:
            raise NotFound(f"Design '{design_id}' was not found" + (f' at revision {rev}' if rev else ''), code="design-not-found")
        return (KitchenSpec.model_validate_json(row['spec_json']), row['rev'])

    def add_revision(self, design_id: str, base_rev: int | None, spec: KitchenSpec, op: dict, source: str='', catalog_json: str | None=None, **legacy) -> int:
        source = legacy.pop('source', source)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        catalog_json = catalog_json or self._snap(spec)          # before taking the lock: the snapshot reads the catalog rows
        with self._conn() as connection:
            row = connection.execute('SELECT MAX(rev) FROM revisions WHERE design_id=?', (design_id,)).fetchone()
            latest = row[0]
            if latest is None:
                raise NotFound(f"Design '{design_id}' was not found", code="design-not-found", params={"id": design_id})
            if base_rev is not None and base_rev != latest:
                raise ConflictError(f'base_rev={base_rev}, but the latest revision is {latest}; reload before editing', params={'base': base_rev, 'latest': latest})
            connection.execute('INSERT INTO revisions(design_id, rev, spec_json, operation, source, catalog_json) VALUES(?,?,?,?,?,?)', (design_id, latest + 1, json.dumps(dump_spec(spec), ensure_ascii=False), json.dumps(op, ensure_ascii=False), source, catalog_json))
            connection.execute('UPDATE designs SET name=? WHERE id=?', (spec.name, design_id))
            return latest + 1

    def _snap(self, spec: KitchenSpec) -> str | None:
        return self.snapshot(spec) if self.snapshot else None

    def revision_catalog(self, design_id: str, rev: int) -> list[dict] | None:
        """The catalog items saved with a revision (``None``: saved before the catalog existed, or without any item)."""
        with self._conn() as connection:
            row = connection.execute('SELECT catalog_json FROM revisions WHERE design_id=? AND rev=?', (design_id, rev)).fetchone()
        return json.loads(row['catalog_json']) if row and row['catalog_json'] else None

    # ---------- catalog layers (kitchen.catalog): workshop and user rows, with every edit kept
    def catalog_rows(self, scopes: list[str]) -> list[dict]:
        if not scopes:
            return []
        with self._conn() as connection:
            rows = connection.execute(f"SELECT kind, id, scope, version, data_json, disabled FROM catalog_items WHERE scope IN ({','.join('?' * len(scopes))}) ORDER BY rowid", scopes).fetchall()
        return [{'kind': r['kind'], 'id': r['id'], 'scope': r['scope'], 'version': r['version'], 'data': json.loads(r['data_json']), 'disabled': bool(r['disabled'])} for r in rows]

    def catalog_stamp(self) -> int:
        """Changes whenever a catalog row changes (the last history entry): the service rebuilds its merged catalog when it moves."""
        with self._conn() as connection:
            return connection.execute('SELECT COALESCE(MAX(seq), 0) FROM catalog_history').fetchone()[0]

    def _catalog_row(self, connection, kind: str, id: str, scope: str) -> dict | None:
        r = connection.execute('SELECT version, data_json, disabled FROM catalog_items WHERE kind=? AND id=? AND scope=?', (kind, id, scope)).fetchone()
        return None if r is None else {'version': r['version'], 'data': json.loads(r['data_json']), 'disabled': bool(r['disabled'])}

    def catalog_put(self, kind: str, id: str, scope: str, data: dict | None, disabled: bool = False, by: str = '') -> int:
        """Write (or, with ``data`` None and not disabled, delete) the row of one item in one layer; returns its new version (0: deleted)."""
        with self._conn() as connection:
            before = self._catalog_row(connection, kind, id, scope)
            if data is None and not disabled:
                connection.execute('DELETE FROM catalog_items WHERE kind=? AND id=? AND scope=?', (kind, id, scope))
                after, version = None, 0
            else:
                version = (before['version'] if before else 0) + 1
                after = {'version': version, 'data': data or {}, 'disabled': disabled}
                connection.execute('INSERT INTO catalog_items(kind, id, scope, version, data_json, disabled, updated_at, updated_by) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,?) '
                                   'ON CONFLICT(kind, id, scope) DO UPDATE SET version=excluded.version, data_json=excluded.data_json, disabled=excluded.disabled, '
                                   'updated_at=CURRENT_TIMESTAMP, updated_by=excluded.updated_by', (kind, id, scope, version, json.dumps(data or {}, ensure_ascii=False), int(disabled), by))
            connection.execute('INSERT INTO catalog_history(kind, id, scope, before_json, after_json, by) VALUES(?,?,?,?,?,?)',
                               (kind, id, scope, json.dumps(before, ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False) if after else None, by))
            return version

    def catalog_log(self, kind: str, id: str, scope: str, before: dict | None, after: dict | None, by: str) -> None:
        """A history line with no change of the catalog itself (e.g. the old text of a table row the catalog replaced)."""
        with self._conn() as connection:
            connection.execute('INSERT INTO catalog_history(kind, id, scope, before_json, after_json, by) VALUES(?,?,?,?,?,?)',
                               (kind, id, scope, json.dumps(before, ensure_ascii=False) if before else None,
                                json.dumps(after, ensure_ascii=False) if after else None, by))

    def catalog_history(self, kind: str, id: str, scope: str | None = None, limit: int = 50) -> list[dict]:
        sql = 'SELECT seq, scope, before_json, after_json, by, at FROM catalog_history WHERE kind=? AND id=?' + (' AND scope=?' if scope else '') + ' ORDER BY seq DESC LIMIT ?'
        args = (kind, id, scope, limit) if scope else (kind, id, limit)
        with self._conn() as connection:
            rows = connection.execute(sql, args).fetchall()
        return [{'seq': r['seq'], 'scope': r['scope'], 'before': json.loads(r['before_json']) if r['before_json'] else None,
                 'after': json.loads(r['after_json']) if r['after_json'] else None, 'by': r['by'], 'at': r['at']} for r in rows]

    def list_designs(self) -> list[dict]:
        with self._conn() as connection:
            return [dict(row) for row in connection.execute('SELECT d.id, d.name, d.created_at, MAX(r.rev) AS rev, MAX(r.created_at) AS updated_at FROM designs d JOIN revisions r ON r.design_id=d.id GROUP BY d.id ORDER BY updated_at DESC')]

    def history(self, design_id: str) -> list[dict]:
        with self._conn() as connection:
            rows = [dict(row) for row in connection.execute('SELECT rev, operation, source, created_at FROM revisions WHERE design_id=? ORDER BY rev', (design_id,))]
        for row in rows:
            row['operation'] = json.loads(row.pop('operation'))
        return rows
    _JOB_COLS = ('id', 'design_id', 'rev', 'view', 'render_key', 'kind', 'mode', 'target', 'backend', 'status', 'error', 'created_at', 'updated_at')

    def _job(self, row) -> dict:
        priority_score = {column: row[column] for column in self._JOB_COLS}
        priority_score['request'] = json.loads(row['request_json'])
        priority_score['result'] = json.loads(row['result_json'] or '{}')
        return priority_score

    def create_job(self, job: dict) -> dict:
        with self._conn() as connection:
            connection.execute('INSERT INTO image_jobs(id, design_id, rev, view, render_key, kind, mode, target, backend, status, request_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (job['id'], job['design_id'], job['rev'], job['view'], job['render_key'], job['kind'], job['mode'], job.get('target'), job['backend'], job['status'], json.dumps(job['request'], ensure_ascii=False)))
            if job['status'] == 'running':
                self._claim(connection, job['id'])
        if job['status'] == 'running':
            self._ensure_beat()
        return self.get_job(job['id'])

    def update_job(self, job_id: str, status: str | None=None, result: dict | None=None, error: str | None=None) -> dict:
        with self._conn() as connection:
            row = connection.execute('SELECT result_json FROM image_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise NotFound(f"Image job '{job_id}' was not found", code="image-job-not-found")
            result_data = {**json.loads(row['result_json'] or '{}'), **(result or {})}
            connection.execute('UPDATE image_jobs SET status=COALESCE(?, status), result_json=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, json.dumps(result_data, ensure_ascii=False), error, job_id))
            if status == 'running':
                self._claim(connection, job_id)
        if status == 'running':
            self._ensure_beat()
        return self.get_job(job_id)

    def _claim(self, connection, job_id: str) -> None:
        connection.execute('UPDATE image_jobs SET owner=?, heartbeat_at=? WHERE id=?', (self.owner, time.time(), job_id))

    def touch_jobs(self) -> int:
        """Refresh the heartbeat of the running jobs this process owns; returns how many there are."""
        with self._conn() as connection:
            return connection.execute("UPDATE image_jobs SET heartbeat_at=? WHERE status='running' AND owner=?", (time.time(), self.owner)).rowcount

    def _ensure_beat(self) -> None:
        """Keep a daemon thread alive while this process owns running jobs; it ends by itself when there are none."""
        with self._beat_lock:
            if self._beat is not None and self._beat.is_alive():
                return
            self._beat = threading.Thread(target=self._beat_loop, daemon=True, name='job-heartbeat')
            self._beat.start()

    def _beat_loop(self) -> None:
        while True:
            time.sleep(self.HEARTBEAT_S)
            with self._beat_lock:
                if not os.path.exists(self.path):     # the database is gone (a test's temp dir, a moved data folder): connecting would create a stray empty file
                    self._beat = None
                    return
                try:
                    if self.touch_jobs() == 0:
                        self._beat = None
                        return
                except sqlite3.Error:
                    pass

    def get_job(self, job_id: str) -> dict:
        with self._conn() as connection:
            row = connection.execute('SELECT * FROM image_jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise NotFound(f"Image job '{job_id}' was not found", code="image-job-not-found")
        return self._job(row)

    def list_jobs(self, design_id: str | None=None, view: str | None=None, status: str | None=None, limit: int=50) -> list[dict]:
        conditions, parameters = ([], [])
        for col, value in (('design_id', design_id), ('view', view), ('status', status)):
            if value:
                conditions.append(f'{col}=?')
                parameters.append(value)
        where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self._conn() as connection:
            rows = connection.execute(f'SELECT * FROM image_jobs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?', (*parameters, int(limit))).fetchall()
        return [self._job(row) for row in rows]

    def mark_stale_jobs(self) -> int:
        """Mark running jobs whose owner stopped sending heartbeats as interrupted. A job another live process is running is left alone."""
        limit = time.time() - self.STALE_AFTER_S
        with self._conn() as connection:
            return connection.execute("UPDATE image_jobs SET status='error:interrupted', error='Process stopped while the job was running', updated_at=CURRENT_TIMESTAMP WHERE status='running' AND (heartbeat_at IS NULL OR heartbeat_at<?)", (limit,)).rowcount
