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
- `kitchen/llm.py`: asks the language model (DeepSeek) for design parameters; takes a `Config`, never raises, the caller falls back to `intent.parse_prompt`.
- `kitchen/edit.py`: applies design operations to specifications.
- `kitchen/rules.py`, `kitchen/rules_kb.py`, `kitchen/rules_nkba.py`: validates designs using geometry and stored knowledge.
- `kitchen/regions.py`: country and region mappings used to select applicable knowledge.
- `kitchen/errors.py`, `kitchen/config.py`, `kitchen/numeric.py`, `kitchen/palette.py`, `kitchen/placement.py`, `kitchen/roomctx.py`, `kitchen/migrations.py`: typed errors, one-time environment settings, number conventions, shared colours, kitchen-room transform, room context, versioned database migrations.
- `kitchen/geometry.py`: compiles specifications into geometry and view definitions.
- `kitchen/render.py`: creates raster control images and render metadata.
- `kitchen/threejs_export.py`: exports the scene format consumed by the browser renderer (schema 1.4.0; `partRef` on doors, drawers, handles and countertop runs tells the web menu what a click means — change `schemas/build_schema.py`, never the JSON).
- `kitchen/cabinet_run.py` (core): cabinet templates (an I-shaped run of base cabinets against one edge of a floorplan object, doors facing away). Free runs use `Module.wall="island"` + `Module.facing` (`-z` default, `+z`, `-x`, `+x`); geometry, `threejs_export._module_frame`, `rules._envelopes` and `Part.orient` must stay in step (`tests/test_free_run.py`).
- `kitchen/edit_intent.py` (core): free-form edit sentence -> an `edit.apply_op` operation or a clarifying question; `service.interpret` previews it through `propose`. `kitchen/recognition/` (core package): `Recognizer` interface + draft checking + one `replace` operation; `service.recognize` previews it, no model is wired. Neither writes to the store.
- `kitchen/images/` (package; `request.py` holds the typed `NewJob` input and `JobRequest`/`Task` stored shapes — add a request key there first), `kitchen/prompts/` (every sentence sent to an image model lives here; `test_architecture` refuses such wording elsewhere), `kitchen/layers.py`, `kitchen/imaging.py`, `kitchen/backends.py`: image layers, job lifecycle, compositing, and generation backends.
- `kitchen/ai_export.py`: assembles design and render data into AI image-generation requests.
- `web/`: browser editor, scene loader, and bundled front-end assets.
- `schemas/`: published scene schemas and related documentation.
- `workflows/`: ComfyUI workflow templates.
- `fixtures/` and `tests/`: sample designs and automated tests.

## Portable core (read before touching `kitchen/`)

The code is organised so the backend can later move to Rust without re-deciding behaviour. The rules are R1-R23 in `CODING_STANDARDS.md`; the reasoning is in `docs/adr/0003-portable-core.md`.

- Each module is in one zone: **core** (pure functions on JSON-like data), **data** (`spec`, `knowledge_seed`), **shell** (store, service, backends, config, llm, intent: may do I/O; `intent` is the text parser and is shell only because it uses Pydantic; the network call to the language model is in `kitchen/llm.py`), **pixel** (numpy/PIL, image jobs). The list is `tests/architecture_rules.py`; a new module must be added to a zone or `tests/test_architecture.py` fails.
- Core code does not read files, the environment, the clock, random numbers or the network, and does not call Pydantic behaviour. Take a value as an argument instead; use `spec.to_data` / `spec.from_data` at the boundary, `numeric.round_half_away` for written-out numbers, `errors.*` for failures.
- Raise `kitchen.errors` types with a stable `code`; do not raise bare `ValueError`/`KeyError` in core and do not `except Exception` to hide a failure.
- A new public core function gets golden cases (`tests/golden/<area>/<name>.json`, a wrapper in `tests/golden_functions.py`). Fill expected values with `python tests/golden_regen.py`, then read the diff before committing.
- The exceptions list `tests/architecture_allowlist.py` may only shrink. If a test says an entry is stale, delete it.
- Run before finishing: `python -m unittest tests.test_architecture tests.test_golden tests.test_errors`, then the full suite.

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
