"""SQLite persistence for designs, revisions, image jobs, and knowledge."""
from __future__ import annotations
import json
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from . import knowledge_seed, migrations, regions
from .spec import KitchenSpec, dump_spec
SCHEMA = migrations.BASELINE   # frozen baseline; changes go in kitchen/migrations.py

class ConflictError(Exception):
    """The supplied base revision is no longer the latest revision."""

def _slug(text: str) -> str:
    normalized_text = unicodedata.normalize('NFD', text.lower()).replace('đ', 'd')
    normalized_text = ''.join((ch for ch in normalized_text if unicodedata.category(ch) != 'Mn'))
    return re.sub('[^a-z0-9]+', '-', normalized_text).strip('-')[:32] or 'kitchen-design'

class Store:

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
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
            raise ValueError(f"region must be one of: {', '.join(regions.REGIONS)}")
        country_codes = [value.strip().upper() for value in (country or '').split(',') if value.strip()]
        for country_code in country_codes:
            regions.normalize(country_code)
        country_code = ','.join(country_codes)
        metadata = json.dumps(metadata or {}, ensure_ascii=False)
        with self._conn() as connection:
            row = connection.execute('SELECT id FROM knowledge WHERE code=? AND active=1', (code,)).fetchone()
            if row:
                connection.execute('UPDATE knowledge SET kind=?, title=?, content=?, source_url=?, metadata_json=?, region=?, country=? WHERE id=?', (kind, title, content, source_url, metadata, region_code, country_code, row['id']))
                return {'ok': True, 'code': code, 'operation': 'update', 'region': region_code, 'country': country_code}
            connection.execute('INSERT INTO knowledge(kind,code,title,content,source_url,metadata_json,region,country) VALUES(?,?,?,?,?,?,?,?)', (kind, code, title, content, source_url, metadata, region_code, country_code))
            return {'ok': True, 'code': code, 'operation': 'add-new', 'region': region_code, 'country': country_code}

    def regions_summary(self) -> list[dict]:
        with self._conn() as connection:
            rows = connection.execute('SELECT region, country, kind, COUNT(*) n FROM knowledge WHERE active=1 GROUP BY 1,2,3 ORDER BY 1,2,3').fetchall()
        return [dict(row) for row in rows]

    def set_active(self, code: str, active: bool) -> int:
        with self._conn() as connection:
            return connection.execute('UPDATE knowledge SET active=? WHERE code=?', (int(active), code)).rowcount

    def rule_rows(self) -> list[dict]:
        return self.knowledge('', ['rule', 'standard'])

    def create_design(self, spec: KitchenSpec, source: str='', **legacy) -> dict:
        source = legacy.pop('source', source)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        design_id = f'{_slug(spec.name)}-{uuid.uuid4().hex[:6]}'
        with self._conn() as connection:
            connection.execute('INSERT INTO designs(id, name) VALUES(?,?)', (design_id, spec.name))
            connection.execute('INSERT INTO revisions(design_id, rev, spec_json, operation, source) VALUES(?,?,?,?,?)', (design_id, 1, json.dumps(dump_spec(spec), ensure_ascii=False), json.dumps({'op': 'create'}), source))
        return {'id': design_id, 'rev': 1}

    def put_floorplan(self, ref: str, data: dict) -> None:
        """Keep the original floorplan document once, under its content hash; revisions only carry the ref."""
        with self._conn() as connection:
            connection.execute('INSERT OR IGNORE INTO floorplans(ref, source_json) VALUES(?,?)', (ref, json.dumps(data, ensure_ascii=False)))

    def get_floorplan(self, ref: str) -> dict:
        with self._conn() as connection:
            row = connection.execute('SELECT source_json FROM floorplans WHERE ref=?', (ref,)).fetchone()
        if not row:
            raise KeyError(f"Floorplan '{ref}' was not found")
        return json.loads(row['source_json'])

    def get(self, design_id: str, rev: int | None=None) -> tuple[KitchenSpec, int]:
        with self._conn() as connection:
            if rev is None:
                row = connection.execute('SELECT rev, spec_json FROM revisions WHERE design_id=? ORDER BY rev DESC LIMIT 1', (design_id,)).fetchone()
            else:
                row = connection.execute('SELECT rev, spec_json FROM revisions WHERE design_id=? AND rev=?', (design_id, rev)).fetchone()
        if not row:
            raise KeyError(f"Design '{design_id}' was not found" + (f' at revision {rev}' if rev else ''))
        return (KitchenSpec.model_validate_json(row['spec_json']), row['rev'])

    def add_revision(self, design_id: str, base_rev: int | None, spec: KitchenSpec, op: dict, source: str='', **legacy) -> int:
        source = legacy.pop('source', source)
        if legacy:
            raise TypeError(f"Unexpected options: {', '.join(legacy)}")
        with self._conn() as connection:
            row = connection.execute('SELECT MAX(rev) FROM revisions WHERE design_id=?', (design_id,)).fetchone()
            latest = row[0]
            if latest is None:
                raise KeyError(f"Design '{design_id}' was not found")
            if base_rev is not None and base_rev != latest:
                raise ConflictError(f'base_rev={base_rev}, but the latest revision is {latest}; reload before editing')
            connection.execute('INSERT INTO revisions(design_id, rev, spec_json, operation, source) VALUES(?,?,?,?,?)', (design_id, latest + 1, json.dumps(dump_spec(spec), ensure_ascii=False), json.dumps(op, ensure_ascii=False), source))
            connection.execute('UPDATE designs SET name=? WHERE id=?', (spec.name, design_id))
            return latest + 1

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
        return self.get_job(job['id'])

    def update_job(self, job_id: str, status: str | None=None, result: dict | None=None, error: str | None=None) -> dict:
        with self._conn() as connection:
            row = connection.execute('SELECT result_json FROM image_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Image job '{job_id}' was not found")
            result_data = {**json.loads(row['result_json'] or '{}'), **(result or {})}
            connection.execute('UPDATE image_jobs SET status=COALESCE(?, status), result_json=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, json.dumps(result_data, ensure_ascii=False), error, job_id))
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict:
        with self._conn() as connection:
            row = connection.execute('SELECT * FROM image_jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise KeyError(f"Image job '{job_id}' was not found")
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
        """Mark jobs left running by a stopped process as interrupted."""
        with self._conn() as connection:
            return connection.execute("UPDATE image_jobs SET status='error:interrupted', error='Process stopped while the job was running', updated_at=CURRENT_TIMESTAMP WHERE status='running'").rowcount
