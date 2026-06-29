use rust_chess::{Board, Move};

// Perft ("performance test") walks the legal-move tree to a fixed depth and counts the
// leaf nodes. The count is brutally sensitive to any move-generation bug (a single missed
// or illegal move anywhere in the tree shifts the total), which makes it an exact oracle.
//
// The driver lives here in the hidden tests, NOT in the crate under test: the agent only
// implements the move-generation primitives (from_fen / legal_moves / make_move). It never
// sees the expected counts, so it cannot hard-code them — passing requires a correct engine.
//
// The positions and counts below are the canonical 6-position suite published on the Chess
// Programming Wiki (https://www.chessprogramming.org/Perft_Results) — consensus-verified by
// hundreds of independent engines, so the ground truth originates entirely outside this repo.
//
// Depths are capped so each test stays in the few-million-node range (a correct-but-naive
// clone-per-node engine still finishes quickly); the constructed positions cover castling,
// en passant, promotion, pins and discovered/double check even at shallow depth.

fn perft(b: &Board, depth: u32) -> u64 {
    if depth == 0 {
        return 1;
    }
    b.legal_moves()
        .iter()
        .map(|m: &Move| perft(&b.make_move(m), depth - 1))
        .sum()
}

// Position 1 — starting position
const START: &str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
// Position 2 — "Kiwipete": dense middlegame stressing castling, pins and captures
const KIWIPETE: &str = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1";
// Position 3 — sparse endgame stressing en passant and rook/pawn races
const POS3: &str = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1";
// Position 4 — promotions and an in-check start
const POS4: &str = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1";
// Position 5 — promotions and underpromotions
const POS5: &str = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8";
// Position 6 — balanced middlegame, no castling rights
const POS6: &str = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10";

// --- Position 1: starting position ---
#[test] fn start_d1() { assert_eq!(perft(&Board::from_fen(START), 1), 20); }
#[test] fn start_d2() { assert_eq!(perft(&Board::from_fen(START), 2), 400); }
#[test] fn start_d3() { assert_eq!(perft(&Board::from_fen(START), 3), 8_902); }
#[test] fn start_d4() { assert_eq!(perft(&Board::from_fen(START), 4), 197_281); }
#[test] fn start_d5() { assert_eq!(perft(&Board::from_fen(START), 5), 4_865_609); }

// --- Position 2: Kiwipete ---
#[test] fn kiwipete_d1() { assert_eq!(perft(&Board::from_fen(KIWIPETE), 1), 48); }
#[test] fn kiwipete_d2() { assert_eq!(perft(&Board::from_fen(KIWIPETE), 2), 2_039); }
#[test] fn kiwipete_d3() { assert_eq!(perft(&Board::from_fen(KIWIPETE), 3), 97_862); }
#[test] fn kiwipete_d4() { assert_eq!(perft(&Board::from_fen(KIWIPETE), 4), 4_085_603); }

// --- Position 3 ---
#[test] fn pos3_d1() { assert_eq!(perft(&Board::from_fen(POS3), 1), 14); }
#[test] fn pos3_d2() { assert_eq!(perft(&Board::from_fen(POS3), 2), 191); }
#[test] fn pos3_d3() { assert_eq!(perft(&Board::from_fen(POS3), 3), 2_812); }
#[test] fn pos3_d4() { assert_eq!(perft(&Board::from_fen(POS3), 4), 43_238); }
#[test] fn pos3_d5() { assert_eq!(perft(&Board::from_fen(POS3), 5), 674_624); }

// --- Position 4 ---
#[test] fn pos4_d1() { assert_eq!(perft(&Board::from_fen(POS4), 1), 6); }
#[test] fn pos4_d2() { assert_eq!(perft(&Board::from_fen(POS4), 2), 264); }
#[test] fn pos4_d3() { assert_eq!(perft(&Board::from_fen(POS4), 3), 9_467); }
#[test] fn pos4_d4() { assert_eq!(perft(&Board::from_fen(POS4), 4), 422_333); }

// --- Position 5 ---
#[test] fn pos5_d1() { assert_eq!(perft(&Board::from_fen(POS5), 1), 44); }
#[test] fn pos5_d2() { assert_eq!(perft(&Board::from_fen(POS5), 2), 1_486); }
#[test] fn pos5_d3() { assert_eq!(perft(&Board::from_fen(POS5), 3), 62_379); }

// --- Position 6 ---
#[test] fn pos6_d1() { assert_eq!(perft(&Board::from_fen(POS6), 1), 46); }
#[test] fn pos6_d2() { assert_eq!(perft(&Board::from_fen(POS6), 2), 2_079); }
#[test] fn pos6_d3() { assert_eq!(perft(&Board::from_fen(POS6), 3), 89_890); }
