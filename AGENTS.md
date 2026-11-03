# Agent Guide

## Project Overview

Kitchen Design MCP is a local kitchen-design application. It stores parameterized kitchen specifications, validates them against geometry and knowledge rules, produces scene exports and control renders, and manages image-editing jobs.

The project has two interfaces:

- `server.py` exposes tools over MCP stdio.
- `web_server.py` exposes the local HTTP API and serves the web editor.

Both interfaces should delegate application behavior to `kitchen.service.KitchenService`. Keep transport-specific parsing and response handling in the interface layer; do not duplicate business logic there.

## Architecture and Main Modules

- `kitchen/spec.py`: Pydantic models and serialization for kitchen specifications.
- `kitchen/service.py`: shared application-service facade used by MCP and HTTP.
- `kitchen/store.py`: SQLite persistence for designs, append-only revisions, and knowledge entries.
- `kitchen/intent.py`: converts structured templates or free-text requests into specifications.
- `kitchen/edit.py`: applies design operations to specifications.
- `kitchen/rules.py`, `kitchen/rules_kb.py`, `kitchen/rules_nkba.py`: validates designs using geometry and stored knowledge.
- `kitchen/regions.py`: country and region mappings used to select applicable knowledge.
- `kitchen/geometry.py`: compiles specifications into geometry and view definitions.
- `kitchen/render.py`: creates raster control images and render metadata.
- `kitchen/threejs_export.py`: exports the scene format consumed by the browser renderer.
- `kitchen/imagejobs.py`, `kitchen/layers.py`, `kitchen/imaging.py`, `kitchen/backends.py`: image layers, job lifecycle, compositing, and generation backends.
- `kitchen/ai_export.py`: assembles design and render data into AI image-generation requests.
- `web/`: browser editor, scene loader, and bundled front-end assets.
- `schemas/`: published scene schemas and related documentation.
- `workflows/`: ComfyUI workflow templates.
- `fixtures/` and `tests/`: sample designs and automated tests.

## Important Runtime Flows

### Design creation and editing

1. An interface calls a `KitchenService` method.
2. Input is validated or converted into a `KitchenSpec`.
3. `Store` persists the design and its initial revision.
4. Edits are applied through `kitchen.edit` and saved as new revisions.
5. Use `base_rev` when saving edits so stale clients receive a revision conflict instead of silently overwriting newer work.

Revisions are append-only. Reverting a design must create a new revision containing the older specification; do not delete or rewrite revision history.

### Validation and rendering

Validation uses the specification plus relevant knowledge rows from the store. Geometry, Three.js export, and raster rendering are separate transformations of a specification. Preserve the same design ID and revision in generated metadata and output paths. Render artifacts are stored under `renders/<design-id>/rev<N>/`.

### Image-editing jobs

Image jobs use layer and instance information from renders. A job moves through preparation, backend execution or external submission, result validation/compositing, and acceptance or rejection. Keep job state, request files, masks, and output artifacts consistent. If an accepted job changes the design, save that change as a new design revision.

## Language and Naming Rules

- Write all new or revised Python code, function and class names, variable names, docstrings, comments, log messages, and user-facing instructions in English.
- Write new or revised project documentation and agent instructions in English.
- Do not add Vietnamese prose or Vietnamese identifiers to new code or documentation.
- Field names, operation names, tool parameters, API keys, serialized values, SQLite columns, and file names are English. They were renamed in one deliberate breaking change; `kitchen/legacy.py` is the only place that may contain the old Vietnamese identifiers (data conversion: `convert_spec`, `migrate_database`, `migrate_renders`). Do not reintroduce Vietnamese identifiers elsewhere.
- Vietnamese remains only in user-facing prose (messages, UI text, comments) and in the user-input vocabulary tables (`kitchen/vocab.py`, `kitchen/regions.py`, intent parsing). Do not translate those tables.

## Implementation Guidance

- Inspect the relevant caller, service method, and downstream module before changing behavior.
- Keep `KitchenService` as the shared application boundary for MCP and HTTP.
- Keep persistence operations in `Store`; avoid direct SQLite access from interfaces or unrelated modules.
- Validate incoming specifications through the existing Pydantic models and serialization helpers.
- Preserve API and schema compatibility unless the requested change explicitly requires a breaking change.
- Keep generated files and runtime data in their established locations, especially `renders/`, `logs/`, and `kitchen.db`.
- Load secrets from environment configuration. Never write secret values into source code, logs, fixtures, or documentation.
- Follow the host and request-size checks already present in `web_server.py` when changing HTTP behavior.

## Local Commands

- Start the web editor on Windows: `python run.py`.
- Run the HTTP server directly: `python web_server.py`.
- Run the MCP server: `python server.py`.
- Install the project and dependencies: `python -m pip install -e .`.
- Run the test suite: `python -m unittest discover -s tests -v`.

Use the project's virtual environment when available. The web editor is normally served at `http://localhost:8080/web/`.

## Agent skills

Project skills live in `.claude/skills/`: `domain-modeling`, `tdd`, `diagnosing-bugs`, `code-review`, `improve-codebase-architecture`, `codebase-design`, `git-guardrails-claude-code`.

### Issue tracker

Issues live on GitHub (`origin`, use the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. Use the glossary's terms in code, tests and docs, and record hard-to-reverse, surprising decisions as ADRs. See `docs/agents/domain.md`.

### Code review

`/code-review <fixed-point> [spec-path]` checks the diff against `CODING_STANDARDS.md` (and the smell baseline) and against the matching spec in `docs/specs/` (see `docs/specs/README.md`). Name the spec in the commit message or pass its path so the Spec axis can run.
