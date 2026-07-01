# New Feature with Automated Tests

This eval measures two things:
1. The ability of an agent to implement a non-trivial new feature against a fixed, pre-defined API
   contract.
1. The ability to do so well enough to pass a hidden automated test suite it never gets to see -
   with no chance to hard-code, fetch, or otherwise cheat its way to the answer.

## Overview
For this example the agent implements a standard chess move generator in Rust. We clone a
scaffolded fork, [ScottRBK/rust-chess](https://github.com/ScottRBK/rust-chess) on the `eval-v1`
ref, whose `src/lib.rs` exposes a frozen `Board` API - `from_fen`, `legal_moves`, and `make_move`
- with every method body stubbed out as `unimplemented!()`. The agent's job is to fill those bodies
in so the crate becomes a correct, fully-legal chess engine. For the exact contract, the six
positions we grade against, and how the ground truth was validated, see the
[Chess Engine](../evals.md#chess-engine) entry in the eval catalogue.

Two reusable capabilities are what make this pattern worth its own write-up.

The first is grading against a **hidden test suite** using *fixture-injection*. This sits at the
opposite end of a spectrum from the restore-from-git approach in [bug_fix](./bug_fix.md), and it is
chosen for exactly the reason that one isn't: here the tests would hand the agent the answer, so
they never touch the workspace until score time. The two approaches - and the single question that
decides between them - are contrasted in
[Hiding tests from the agent](../evals.md#hiding-tests-from-the-agent).

The second is running on a **custom Docker image**. A chess engine needs a Rust toolchain, so this
eval runs on `eval-harness-rust:latest` rather than the default image.

> [!TIP]
> The image is selected by a single class attribute - `image = "eval-harness-rust:latest"` - which
> the engine reads with a `getattr(eval_cls, "image", "eval-harness:latest")` fallback, so no
> change to `evals.json` or the runner is needed to bring in a new toolchain. The rust image is just
> `FROM eval-harness:latest` plus `rustup`, so you must build the base image **first** and then the
> rust image - there is no auto-rebuild (see the build commands in [AGENTS](../../AGENTS.md)).

```dockerfile
from eval-harness:latest

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# rustup wires PATH via shell profiles, but the harness runs phases through non-login
# `docker exec`, which never sources them. Set it on the image env so `cargo` is always found.
ENV PATH=/home/node/.cargo/bin:$PATH
```

The values each phase needs are a mix of inline repo coordinates and files pulled from the eval's
`fixtures/` directory via [`read_eval_fixture`](../helpers.md) - the prompt for `act`, and the
hidden test file for `score` (see [embedded values](../../README.md#embedded-values)). Note the
`image` attribute sits right alongside them on the class body.

```python
image = "eval-harness-rust:latest"

arrange_embedded_values = {
    "REPO_URL": "https://github.com/ScottRBK/rust-chess",
    "REPO_REF": "eval-v1",
    "REPO_DIR": "/workspace/rust-chess",
}

act_embedded_values = {
    "REPO_DIR": "/workspace/rust-chess",
    "PROMPT": read_eval_fixture(__file__, "prompt.md"),
}

score_embedded_values = {
    "REPO_DIR": "/workspace/rust-chess",
    "INTEGRATION_TESTS": read_eval_fixture(__file__, "integration_tests.rs"),
}
```

## Evaluation Details

### arrange
The arrange phase just clones the scaffold and severs the remote - the same shallow, pinned,
detached-HEAD clone the other evals use, followed by `git remote remove origin` so the agent can't
push its work back or re-fetch anything from the tag. There is nothing to restore here (the tests
were never in this repo to begin with), so that is all arrange does.

```python
subprocess.run(
    ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
     "--depth", "1", "--branch", REPO_REF, REPO_URL, REPO_DIR],
    check=True,
)
subprocess.run(["git", "-C", REPO_DIR, "remote", "remove", "origin"])
```

### act
We build an `AgentShell` and hand it the
[prompt](../../example_evals/chess_engine/fixtures/prompt.md) fixture. That prompt spells out the
API contract in the agent's own terms: keep the `Board` and `Move` names and the three exact
signatures (the hidden tests compile against them), standard library only, Rust only. It is the
agent-facing mirror of the anti-cheat logic that `score` enforces.

```python
shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
response = await shell.execute(
    cwd=REPO_DIR,
    prompt=PROMPT,
    model=os.environ["AGENT_MODEL"],
    effort=os.environ["AGENT_EFFORT"],
    disallowed_tools=["web_search", "web_fetch"],
)
```

The one thing worth calling out is `disallowed_tools`. A correct chess engine is one of the
most-published pieces of code on the internet, so we disable the agent-shell's `web_search` and
`web_fetch` tools to stop it simply fetching a reference implementation and pasting it in. Note this
is *tool-level*, not network-level: we are removing the harness's search/fetch tools, not sandboxing
the box, so the model's own connectivity is untouched.

### score
Scoring has three moving parts: an anti-cheat gate, the injection of the hidden tests, and the run
itself.

First, std-only enforcement. A correct engine has to be built from the standard library alone, so we
parse `Cargo.toml` and refuse the run outright if the agent has added any dependency. This is what
stops an agent `cargo add`-ing an existing engine crate like `shakmaty` and wiring it up.

```python
with open(os.path.join(REPO_DIR, "Cargo.toml"), "rb") as f:
    manifest = tomllib.load(f)
for table in ("dependencies", "dev-dependencies", "build-dependencies"):
    if manifest.get(table):
        print(f"Third-party dependency found in [{table}] - std-only required")
        print("EVAL_SCORE=0.0")
        return
```

Next we inject the hidden test suite. This is the enforcement half of the "hidden tests" design: the
perft driver and its expected node counts have been sitting in a fixture on the host the whole time,
embedded into `INTEGRATION_TESTS`, and only now do we write them into the working tree. We overwrite
unconditionally, so whatever the agent may have dropped at that path during `act` is replaced by our
canonical copy.

```python
tests_dir = os.path.join(REPO_DIR, "tests")
os.makedirs(tests_dir, exist_ok=True)
with open(os.path.join(tests_dir, "integration_tests.rs"), "w") as f:
    f.write(INTEGRATION_TESTS)
```

Then we run just that test target. It is a `--release` build for a specific reason: a perft suite
walks the move tree to a fixed depth and counts millions of leaf nodes, so a debug build would
crawl. We also deliberately do *not* pass `check=True` - `cargo test` exits non-zero whenever a test
fails, and the harness treats a non-zero phase exit as a hard error, so instead we let it finish and
parse the summary line ourselves.

```python
result = subprocess.run(
    ["cargo", "test", "--release", "--test", "integration_tests"],
    cwd=REPO_DIR, capture_output=True, text=True,
)
match = re.search(r"(\d+) passed; (\d+) failed", result.stdout)
if not match:
    print("No test result line found (compile failure or no tests ran)")
    print("EVAL_SCORE=0.0")
    return
```

If the summary line is missing entirely the crate almost certainly failed to compile - a signature
change that broke the frozen API, say - and we score a zero. We also guard on the count: the suite
is exactly **24** perft cases (six canonical positions taken from the Chess Programming Wiki), so if
we don't see 24 tests run, something structural has shifted and the score is void.

```python
EXPECTED_TESTS = 24
passed, failed = int(match.group(1)), int(match.group(2))
if passed + failed != EXPECTED_TESTS:
    print(f"Test count mismatch: ran {passed + failed}, expected {EXPECTED_TESTS}")
    print("EVAL_SCORE=0.0")
    return

score = passed / EXPECTED_TESTS
print(f"EVAL_SCORE={score:.4f}")
```

The score is just the fraction of the 24 cases that pass, so the untouched stub scores `0` and a
fully-correct engine scores `1`. As with the other evals the whole body is wrapped in a `try/except`
that emits `EVAL_SCORE=0.0` on any failure, and that final print is what the harness reads back out
of the container.

> [!WARNING]
> This pattern only holds because the primitives never see a position-plus-depth pair - the perft
> driver lives entirely in the hidden test - so the published node counts cannot be hard-coded into
> `legal_moves` or `make_move`. If you adapt it, keep the graded logic and the test harness strictly
> separate: the moment the contract the agent implements also tells it what the tests will ask, the
> hidden-test guarantee is gone.

> [!NOTE]
> Unlike the [bug_fix](./bug_fix.md) eval - which parses a JUnit XML report precisely because
> regexing test output is fragile - this eval scrapes `cargo test`'s stdout summary line, since
> `cargo test` has no stable first-party JUnit equivalent (libtest's JSON output is nightly-only).
> The `passed + failed != 24` guard is what keeps that regex honest; if you want XML-grade
> robustness for a Rust eval, the usual route is the third-party `cargo-nextest` runner, which can
> emit JUnit XML.
