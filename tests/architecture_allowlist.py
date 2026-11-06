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
