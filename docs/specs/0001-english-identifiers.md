# English identifiers and legacy data migration

Status: implemented

## Goal

Every identifier in the code and in the data formats is English, and data created under the old Vietnamese names keeps working without manual steps. See ADR 0002.

## Requirements

- R1. Specification fields, operation names, MCP tool parameters, HTTP query and body keys, stored enum values, SQLite columns, and file and directory names use English names.
- R2. `kitchen/legacy.py` is the only module that contains the old Vietnamese names.
- R3. `Store` migrates an old `kitchen.db` on open, before the schema is created: it renames columns and converts stored JSON and enum values, and records completion in `PRAGMA user_version`.
- R4. `KitchenService` migrates an old `renders/` directory on start: view directories, file names and JSON content, and marks completion with `.english-schema-v1`.
- R5. Both migrations are idempotent: running them again changes nothing.
- R6. `convert_spec` turns a specification file saved under the old names into the current schema.
- R8. Converting the original sample specification gives exactly `fixtures/l-shaped-kitchen.json`.
- R9. Job statuses are `awaiting-send`, `awaiting-result`, `running`, `needs-review`, `accepted`, `rejected` and `error:<code>`; the web editor styles each one.
- R10. The three.js export uses `storey` (values `base`, `upper`, `loft`, `tall`, `corner`) and `plinthHeight`; the current schema describes both.
- R11. User-facing text and the user-input vocabulary tables stay in Vietnamese and are not altered by the rename.

## Out of scope

- `database_export.json` is not converted.
- `schemaVersion` of the export stays `1.1.0`.
