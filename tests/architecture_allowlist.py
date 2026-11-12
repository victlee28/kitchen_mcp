"""Known exceptions to the portable-core rules. THIS LIST MAY ONLY SHRINK: test_architecture fails when an entry is no longer needed,
and adding one needs a reason a reviewer accepts. Key: (module, rule, detail) as reported by architecture_rules.violations()."""

ALLOWED: dict[tuple[str, str, str], str] = {
    ("roomctx", "R16-module-state", "_CACHE"):
        "A memo, not state: keyed by the sha256 of the whole floorplan + the run lengths, so a hit equals a fresh computation. A Rust port keeps an LRU in the shell.",
}

# R10: builtin round() calls still in each core module (written-out values should use numeric.round_half_away). Lower these numbers
# when you convert calls; the test fails if a count goes UP or a module not listed here gains its first call.
ROUND_BASELINE: dict[str, int] = {}

# R2: modules allowed to read os.environ / os.getenv. Core modules never do.


# Words people read live in data/ (data/i18n, the catalog); the code names keys. String literals holding Vietnamese still in each file
# (docstrings and comments do not count). THESE NUMBERS MAY ONLY GO DOWN: the test fails when a count goes up, when a file not listed here
# gains one, and when a count went down without being lowered here.
VIETNAMESE_BASELINE: dict[str, int] = {
    # Data-driven stage 4 (command dictionary: words and patterns that read what people type)
    "kitchen/lexicon.py": 30,
    "kitchen/intent.py": 32,
    "kitchen/regions.py": 4,
    "kitchen/appliance_models.py": 1,
    "kitchen/floorplan/structures.py": 2,
    "kitchen/floorplan/document.py": 1,
    "kitchen/prompts/photo.py": 19,
    "kitchen/vocab.py": 4,
    "kitchen/catalog_csv.py": 3,
    "kitchen/store.py": 1,
    "kitchen/tv_system.py": 1,
    # Data-driven stage 5 (default material names, written into designs)
    "kitchen/layers.py": 13,
    "kitchen/threejs_export.py": 7,
    "kitchen/handles.py": 3,
    "kitchen/prompts/layer.py": 1,
    "kitchen/geometry_edit.py": 8,
    # Messages still to move to data/i18n (field descriptions of the design schema, request checks, image jobs, backends, notes)
    "kitchen/ai_export.py": 1,
    "kitchen/backends.py": 9,
    "kitchen/floorplan/binding.py": 2,
    "kitchen/images/base_images.py": 1,
    "kitchen/images/common.py": 18,
    "kitchen/images/packages.py": 1,
    "kitchen/images/request_builder.py": 2,
    "kitchen/images/results.py": 8,
    "kitchen/images/runners.py": 2,
    "kitchen/imaging.py": 4,
    "kitchen/knowledge_seed.py": 1,
    "kitchen/llm.py": 6,
    "kitchen/render.py": 3,
    "kitchen/request_check.py": 33,
    "kitchen/spec.py": 37,
}
