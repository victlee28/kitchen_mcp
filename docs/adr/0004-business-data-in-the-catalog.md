# 0004. Business data lives in the catalog, not in the core

Status: accepted (11/2026)

## Context

Cabinet types, layout templates, TV unit layouts, default sizes and finishes, the command dictionary and every word people read were
Python constants. A workshop that wanted a new cabinet type or a different L-shaped layout had to ask a developer, and a Rust rewrite
would have had to copy every table.

## Decision

- What a workshop may want to change is **data**: an item of a catalog kind (`data/kinds.json`, schema in `data/schemas/<kind>.schema.json`,
  builtin items in `data/items/<kind>.json`). The workshop edits it on the catalog page (`web/catalog.html`); users edit the kinds whose
  `writers` include `user`.
- The core is an **engine**: it reads a `Catalog` it is given (never a file), compiles what it needs once per catalog
  (`catalog.derived(key, build)`) and evaluates formulas written in data with `kitchen/catalog/expr.py` (no `eval`).
- Words people read are keys of `data/i18n/<lang>.json` (`words.say`, web `tx`); default names a design stores are recognised by their
  wording and worded again in the reader's language (`i18n.Names`).
- A design is drawn with the catalog of the revision it was saved with (`catalog_for_revision`); the kinds marked `snapshot` are copied
  into the revision. A newer catalog reaches an old design only through the `catalog-refresh` operation, which the user asks for.
- An item is accepted only if the core can compile it (`service._check_trial`): a broken formula or an unknown cabinet type is refused
  when it is saved, not when someone draws.

## Consequences

- R24 in `CODING_STANDARDS.md`: a new table of business values in `kitchen/` is refused in review; Vietnamese literals are counted per file
  (`VIETNAMESE_BASELINE`) and may only go down.
- The builtin items are golden-tested; changing one is a reviewed data change, the same as a code change.
- Still in code: geometry of a single panel, the solver that places cabinets (its parameters are data), the image pipeline.
