# Coding Standards

Rules the `code-review` skill checks the diff against. Where this file and `AGENTS.md` overlap, they say the same thing; `AGENTS.md` explains the architecture, this file lists the checkable rules. Use the terms in `GLOSSARY.md`.

## Language and naming

- S1. New or changed code, identifiers, docstrings, comments, log messages and docs are written in English.
- S2. Field names, operation names, tool parameters, API keys, stored values, SQLite columns and file names are English. The old Vietnamese names appear only in `kitchen/legacy.py`.
- S3. Vietnamese is allowed only in user-facing text (messages, UI) and in the user-input vocabulary tables (`kitchen/vocab.py`, `kitchen/regions.py`, intent parsing). Do not translate those tables.
- S4. Domain concepts use the glossary term, not a listed `_Avoid_` synonym (for example `storey`, not `tier`; `module`, not `cabinet`).

## Architecture boundaries

- S5. `server.py` (MCP) and `web_server.py` (HTTP) only parse input and format output; behaviour lives in `kitchen.service.KitchenService`.
- S6. SQLite is touched only through `kitchen.store.Store`.
- S7. Specifications enter the system through the Pydantic models in `kitchen/spec.py`.
- S8. Revisions are append-only. Edits pass `base_rev`; a stale `base_rev` is a conflict, never a silent overwrite. Reverting creates a new revision.
- S9. A design changes only through an operation that produces a new revision. An accepted image job that changes the design does the same.
- S10. Generated files stay in their established places: `renders/<design-id>/rev<N>/`, `logs/`, `kitchen.db`.

## Compatibility

- S11. Code must run on Python 3.11. Do not nest the same quote character inside an f-string expression.
- S12. Published schemas in `schemas/` stay valid for the exported scene. A change to an exported field name or value is a breaking change and must be called out, with a migration in `kitchen/legacy.py` for stored data.
- S13. Any change to stored data shape (database columns, JSON in `renders/`) ships with a migration that is idempotent.

## Security and configuration

- S14. Secrets come from the environment. Never write them to source, logs, fixtures or docs.
- S15. HTTP changes keep the host and request-size checks in `web_server.py`.

## Tests

- S16. Tests use `unittest` and run with `python -m unittest discover -s tests -v`.
- S17. Test behaviour through public interfaces (service methods, HTTP endpoints, MCP tools), not private helpers.
- S18. A bug fix adds a test that fails without the fix.
- S19. Changes to exports or migrations are covered by the fixture comparison in `tests/test_legacy_migration.py` or the schema validation tests in `tests/test_kitchen.py`.
