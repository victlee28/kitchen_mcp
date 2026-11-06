# rust/

`golden/` is a std-only Rust crate that runs the shared golden files in `tests/golden/` against Rust ports.

    cd rust/golden && cargo test          # or: cargo run -- ../../tests/golden/**/*.json

Ported so far (all cases match Python): `numeric.round_half_away`, `placement.to_room`, `placement.to_kitchen`, `proposal.op_hash`.
Not ported yet (listed as "not ported", never silently passed): `edit`, `floorplan`, `layers`, `moldings`, `rules`, `structure_mesh`.
Error cases (`"error": {...}`) are skipped until the typed `KitchenError` is ported.
`json.rs` and `sha256.rs` are hand-written only because the build machine had no crates.io access; replace them with `serde_json` / `sha2`.
