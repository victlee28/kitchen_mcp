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

## Portable core (rules R1-R23)

The backend may be rewritten in Rust later. Python stays the reference implementation, JSON stays the contract. The rules below keep the logic portable; `tests/test_architecture.py`, `tests/test_golden.py`, `tests/test_errors.py` and `tests/test_typecheck.py` (pyright, per-file error count in `tests/typecheck_baseline.json`, may only shrink; `pip install pyright`) enforce what a machine can check. Rationale and the full discussion: `docs/adr/0003-portable-core.md`.

Zones (every module in `kitchen/` is in exactly one; the list lives in `tests/architecture_rules.py`):
- **Core** (pure): `placement roomctx rules rules_kb rules_nkba edit proposal geometry moldings handles hardware structure_mesh layers threejs_export lexicon vocab edit_intent cabinet_run runs regions errors palette numeric` and the packages `kitchen/prompts/` (all model-facing wording: `photo layer instruction`) `kitchen/recognition/` (`contract draft operation`) and `kitchen/floorplan/` (`constants geom document regions trim normalize back binding structures export`; `from kitchen import floorplan` keeps the public surface). A package listed in `CORE_PACKAGES` has every file checked as core.
- **Data** (boundary types, constant tables): `spec knowledge_seed`.
- **Shell** (may touch disk, network, environment, clock): `store migrations service backends ai_export legacy config intent llm` (only `config` and `service` read the environment; `backends`, `llm` and `images` are given a `Config`).
- **Pixel** (numpy/PIL and job orchestration; compared by tolerance, not bit for bit): `render imaging geometry_edit request_check view_sync` and the package `kitchen/images/` (image jobs: `common runtime request base_images request_builder packages runners results jobs`; the parts are composed, not inherited: `ImageJobs` holds `base builder packages results runners` that share one `JobEnv` and forwards to them; it takes a `Config` and a `Runtime` (clock, ids, seeds) and never imports the service).

| ID | Rule | Checked by |
|---|---|---|
| R1 | Core imports only the pure stdlib (`math dataclasses typing enum re hashlib itertools unicodedata json`) and other core or data modules. Forbidden in core: `os sqlite3 pathlib open threading urllib http subprocess time datetime random uuid numpy PIL pydantic logging print`, wall-clock calls. | architecture test |
| R2 | I/O only in the shell. The environment is read once into `config.Config` and passed down; core never reads `os.environ`. | architecture test (ENV_READERS) |
| R3 | Only three ports cross the boundary: a design store, an artifact store (renders), an image backend; plus injected `clock` and seed. No other injection without two real users. | review |
| R4 | A core function's public arguments and results are JSON data (`dict list str int float bool None`) or frozen dataclasses of them. No Pydantic instances, numpy arrays, `Path`, `datetime`, callables across the boundary. | review + golden |
| R5 | Explicit types: no bare `dict`/`list` in new core signatures (write `dict[str, Any]` at the least); use frozen dataclasses, `TypedDict`, `NamedTuple`, `Enum`/`Literal`. Core modules pass pyright (`tests/test_typecheck.py`, baseline all zero); `[tool.pyright] strict` in `pyproject.toml` lists the modules checked strictly (`placement numeric errors proposal floorplan/`); add a module there once it is clean. Read untyped JSON through `jsonview.as_dict` / `as_list` (typed views) instead of bare `isinstance` checks. A second ratchet runs the same files in strict mode (`tests/pyright_strict.json`, baseline `tests/typecheck_strict_baseline.json`): every core file is at 0 (11/11/2026), so any new unknown type in the core fails the test; only `images/` (shell) still has strict errors, and its counts only go down. Narrow an optional field with `errors.require(value, what)`. | pyright ratchet |
| R6 | Pydantic only at the boundary: core calls `spec.to_data` / `spec.from_data`, never `model_dump`, `model_validate`, `model_copy`. Do not mutate arguments; return new values. | architecture test (pydantic part) + review |
| R7 | `extra="allow"` stays on the spec models for stored-data compatibility; core reads only declared fields. New stored fields are additive with a default; a stored-shape change ships a migration (`kitchen/migrations.py`) and a compatibility test. | migration tests |
| R8 | Enum values and codes are closed ASCII kebab-case strings declared in one place. An unknown value is a validation error, never silently replaced by a default. | review |
| R9 | Units and frames are named: `*_mm`, `yaw_deg`, `room`/`kitchen`/`scene`. Geometry docstrings say which frame they take and return. | review |
| R10 | Reals are `f64`. Compare with named tolerances (`numeric.EPS_MM`), never `==`. Values written out are rounded with `numeric.round_half_away` (Python's `round` rounds halves to even, Rust's `f64::round` away from zero). `round_int` for integers. The core no longer calls the builtin `round` (baseline is empty; a new call fails the architecture test). | architecture test (round baseline) |
| R11 | Deterministic: no wall clock, randomness or `uuid4` in core; time, seed and ids are injected. Sort explicitly wherever order matters (a Rust `HashMap` is unordered). | architecture test |
| R12 | Text is UTF-8, NFC from users; keys and codes are ASCII; never slice by bytes. Normalisation functions have test vectors. | golden |
| R13 | Defaults, evaluation order and edge cases (empty, zero, negative, overlapping) are documented and covered by a case. | golden |
| R14 | Core raises only `kitchen.errors` types: `InvalidInput`, `Conflict`, `NotFound`, `Unsupported`, `Infrastructure`, each with a stable kebab-case `code`. No `except Exception` that returns a default. Adapters map kind to status in one place (`errors.http_status`). | architecture test + `test_errors.py` |
| R15 | Warnings are data (`warnings: [{code, ...}]`), not log lines; never turn a failure into a silent success. | review |
| R16 | No mutable module state or `global` in core; caches are memos keyed by content hash; no monkey-patching in production code; tests fake the ports, not modules. | architecture test |
| R17 | SQL only in `store` and `migrations`; schema changes only as a new `migrations.STEPS` entry. Stored time is UTC ISO-8601; JSON is encoded consistently; no `pickle`/`repr`. `PRAGMA user_version` is a shared contract. | migration tests |
| R18 | Adapters parse, validate, call `KitchenService`, format. No business rules, no store access; every feature exists in both MCP and HTTP. | `test_adapters.py` |
| R19 | Every public core function has golden cases in `tests/golden/<area>/<name>.json` (normal, edge and error cases). Values are regenerated only with `tests/golden_regen.py`, reviewed in the diff, never during a test run. | `test_golden.py` |
| R20 | Test public behaviour at JSON level, not private helpers; do not use `sleep` to wait for logic (inject the clock). | review |
| R21 | Ratchet: new and changed code meets R1-R20. Existing exceptions are in `tests/architecture_allowlist.py` and may only shrink; adding one needs a reason in the PR. | architecture test |
| R22 | No premature restructuring: no folder moves, no `core/` package, no imitation of `Result`/`Option`, no builders. Split a module only when its responsibilities are clear and tests pin its behaviour. | review |
| R23 | Core uses only the standard library. Heavy libraries stay in the pixel zone. A new third-party dependency needs a note on its Rust counterpart. | review |

Review question for every change that touches core: if this module were replaced by a Rust function, would it have to carry Pydantic, SQLite, `Path`, the environment, a clock, numpy or a web library with it? If yes, the boundary is not clean yet.

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
