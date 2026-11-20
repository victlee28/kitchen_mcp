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
    # What is left reads Vietnamese text itself: letter ranges in regexes ([a-zà-ỹ]), folding "đ", the unit "mét", yes/no cells of a CSV,
    # a few colour / sink words of the matchers. Wording people read lives in data/i18n, the command words in the catalog.
    "kitchen/appliance_models.py": 1,
    "kitchen/catalog_csv.py": 3,
    "kitchen/intent.py": 4,
    "kitchen/lexicon.py": 3,
    "kitchen/regions.py": 4,
    "kitchen/store.py": 1,
    "kitchen/tv_system.py": 1,
    "kitchen/vocab.py": 4,
}
