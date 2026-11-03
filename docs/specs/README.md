# Specs

Each file describes the intended behaviour of one feature as numbered requirements (`R1`, `R2`, ...). The `code-review` skill reads the spec that matches a change and checks the diff against it, quoting the requirement it finds missing, wrong, or unrequested.

Conventions:

- File name: `NNNN-feature-slug.md`. The first line is the title; `Status:` is `implemented`, `partial` or `planned`.
- One requirement per bullet, written so it can be checked from the code or a test. Use `GLOSSARY.md` terms.
- A change that implements part of a spec names the file in its commit message or passes its path to the review (`/code-review <fixed-point> docs/specs/NNNN-...md`).
- When behaviour changes on purpose, update the spec in the same change.
- Hard-to-reverse decisions go to `docs/adr/`, not here.
