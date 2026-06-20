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

## [Saleor ↔ Spree Mapping](../src/evals/saleor_spree_mapping/)
The agent reads two real e-commerce repos and produces a field mapping for the **Order** entity,
Saleor (source) → Spree (target). It emits a CSV with columns `saleor_field,spree_field,transform`;
`score()` compares it against the canonical mapping fixture (`fixtures/canonical_mapping.csv`).

The ground truth was hand-built (2026-06-20) from these schema files:

| System | File | Format |
|--------|------|--------|
| Saleor | `saleor/graphql/schema.graphql` (`type Order`, ~line 11788) | GraphQL SDL |
| Spree  | `packages/cli/src/generated/admin-spec.json` (`schemas.Order`) | OpenAPI JSON |

Scoring contract — the single CSV carries everything `score()` needs:

- **19 positive rows** — must hit the correct `spree_field` AND `transform`.
- **3 `none` rows** (`trackingClientId`, `weight`, `invoices`) — traps with no Spree counterpart;
  must be left unmapped. Mapping them is a precision error.
- **Any other Saleor field** is ignored (no reward, no penalty). This is how the debatable fields
  are handled — by omission, not an explicit ignore list: the metadata family, `isPaid`,
  vouchers/gift cards, and the tax/money sprawl (`shippingTaxRate`, `totalCharged`,
  `undiscountedTotal`, ...) are genuinely N:M or shape-mismatched, so there is no single
  defensible answer.

The `transform` enum is keyed on the **target field's shape** (checkable against Spree's schema):

| value | meaning |
|-------|---------|
| `direct` | target is a scalar, value copies across as-is (rename only) |
| `transform` | target scalar but value needs conversion (enum remap, format, extract-from-object) |
| `structural` | target is a composite (object/array) needing its own sub-mapping |
| `none` | no target (trap) |

Judgement calls worth noting:

- An earlier research draft claimed Saleor `status` → Spree `state`. The live Spree admin-spec has
  **no `state` field**; it exposes `status` (plus `fulfillment_status` / `payment_status`).
- `id → id` is `direct` by the target-shape rule (scalar→scalar) even though Saleor's `id` is a
  base64 Node global id; it is a deliberate discriminator vs `number` / `token`.
- Money fields (`total`, `subtotal`, `shippingPrice`) are `transform` (target is a scalar string),
  not `structural`, despite the Saleor source being a nested `TaxedMoney` object.

## [Chess Engine](../src/evals/chess_engine/)
The agent implements a standard chess move generator in Rust. The cloned repo
(`ScottRBK/rust-chess` @ `eval-v1`) is a stub: `src/lib.rs` exposes a frozen `Board` API whose
method bodies are `unimplemented!()`. The agent fills in the three primitives:

| Method | Contract |
|--------|----------|
| `Board::from_fen(fen: &str) -> Board` | parse a FEN into a position |
| `Board::legal_moves(&self) -> Vec<Move>` | all legal moves for the side to move |
| `Board::make_move(&self, mv: &Move) -> Board` | immutable apply (returns a new board) |

Scoring — a hidden **perft** suite (`fixtures/integration_tests.rs`) walks the legal-move tree to a
fixed depth from six canonical positions and counts the leaf nodes. The counts are the
consensus-verified [Chess Programming Wiki](https://www.chessprogramming.org/Perft_Results) values,
so the ground truth originates entirely outside this repo (and outside the model under test). 24
test cases; `score() = passed / 24`.

Why the agent implements only primitives: the perft driver and the expected counts live in the
hidden test, never in the crate. Since `legal_moves` / `make_move` never see a position+depth, the
published counts can't be hard-coded into them — passing requires a genuinely correct engine.

Anti-cheat:

- **std-only** — `score()` parses `Cargo.toml`; any `dependencies` / `dev-dependencies` /
  `build-dependencies` entry scores 0.0 (kills `cargo add shakmaty`).
- **no web** — `act()` sets `disallowed_tools=["web_search", "web_fetch"]` so engine source can't
  be fetched and pasted. Network stays open for the model itself.
- The frozen API is its own gate: a signature change breaks the hidden test's compile, which zeros
  the whole suite.

Ground truth was validated (2026-06-20) by implementing the same `Board` API against the `shakmaty`
reference engine in a throwaway git worktree and running the fixture: **24/24**, confirming every
FEN and count is correctly transcribed. Stub scores `0.0000`, a correct implementation `1.0000`.

Runs on the `eval-harness-rust:latest` image (base image + rustup), declared via the eval class's
`image` attribute rather than in `evals.json`.

## Hiding tests from the agent
Two patterns, chosen by whether the tests themselves give the answer away:

- **Restore-from-git** (inflection) — the tests ship in the repo. `arrange` leaves them in place
  (the agent is even told to run them), and `score()` runs `git checkout <ref> -- <testfile>` to
  undo any tampering before grading. Fine when seeing the tests doesn't reveal the answer.
- **Fixture-injection** (chess engine) — the tests are NOT in the repo or its git history at all.
  They live as a fixture in the eval (`fixtures/integration_tests.rs`), are read on the host via
  `read_eval_fixture(__file__, ...)` into `score_embedded_values`, and `score()` writes them into
  the working tree just before running. Use this whenever the test contents (here, the expected
  perft counts) would hand the agent the answer. Because phase methods ship as `python -c` with
  embedded values and the eval source is never mounted, the fixture never reaches the container
  until scoring.
