# Task: Implement a standard chess move generator in Rust

This crate (`rust-chess`) exposes a `Board` API in `src/lib.rs` whose method bodies are stubbed
with `unimplemented!()`. Implement them so the crate becomes a correct, fully legal standard-chess
move generator.

## What to implement

In `src/lib.rs`, fill in the bodies of these three methods (and add whatever internal fields,
types, and helpers you need):

- `Board::from_fen(fen: &str) -> Board` — parse a FEN string into a board position.
- `Board::legal_moves(&self) -> Vec<Move>` — return every legal move for the side to move.
- `Board::make_move(&self, mv: &Move) -> Board` — return a new board with the move applied
  (immutable apply: the receiver is left unchanged).

## Rules you must handle

Full standard chess: pawn pushes (single and double), captures, en passant, all promotions
(including underpromotions), knight/bishop/rook/queen/king movement, castling (king- and
queen-side, with all legality conditions), check detection, and the rule that a move is illegal
if it leaves your own king in check (pins, discovered checks, double checks).

## Constraints (these are graded)

- **Do not change the public API.** Keep the names `Board` and `Move` and the exact signatures of
  the three methods above. Hidden tests compile against them — any signature change fails the build
  and scores zero. You may add public or private items, but do not remove or rename these.
- **Standard library only.** Do not add any dependencies to `Cargo.toml` (no `dependencies`,
  `dev-dependencies`, or `build-dependencies`). Using any third-party crate scores zero.
- **Rust only.** Implement everything in this crate.
