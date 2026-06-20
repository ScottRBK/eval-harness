# Evals

## [Encode Repo to Forgetful](../src/evals/encode_repo_forgetful/)

## [Inflection Bug Fix](../src/evals/inflection_bug_fix/)
This eval sees a forked version of https://github.com/jpvanhal/inflection in which three bugs
have been injected to the code that the agent must fix.

Specifically the bugs are as follows. All three live in `inflection/__init__.py`:

| Line | Function | Change | Failures |
|------|----------|--------|----------|
| 229 | `ordinal` (via `ordinalize`) | `% 100` -> `% 10` | 24 unit + 2 doctest = 26 |
| 29 | `pluralize` (-> `tableize`) | `\1ies` -> `\1ys` | 5 unit + 1 doctest = 6 |
| 169 | `camelize` (-> `underscore`) | `.upper()` -> `.lower()` | 5 unit + 2 doctest = 7 |

Effects:

- **ordinal** — the 11/12/13 special case dies, so `ordinalize(11)` returns `"11st"`
  instead of `"11th"` (same for 12/13 and 111/112/113).
- **pluralize** — words ending consonant+`y` pluralize wrong, e.g. `category` ->
  `"categorys"`, `query` -> `"querys"`.
- **camelize** — stops capitalising, e.g. `"product"` -> `"product"`, `"Camel_Case"` ->
  `"camelcase"`.

All three bugs resul in 39 out of 428 tests failing. 

Two bugs claim a second victim via a call/doctest dependency: `pluralize`
breaks `tableize` (which calls it), and `camelize` breaks the `underscore` doctest (whose
docstring example calls `camelize`). This was not intentional initally but making a note here just
for provenance.
