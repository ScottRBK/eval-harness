# [Scorer Authoring](../../example_evals/eval_generator)

This eval measures an agent's ability to:

1. Read a specification for a small software task and derive the behaviours that a correct
   implementation should exhibit.
1. Write a scoring routine that discriminates a correct implementation from incorrect ones — scoring
   the former high and the latter low — without ever seeing either.

It does **not** test the agent's ability to author a full eval-harness evaluation: only the scoring
logic is measured. The arrange and act phases the agent would write for its own eval are neither
exercised nor graded.

## Overview

We hold three implementations of a pure-Python task — one golden (correct) and two broken that fail
in *different* ways — and ask the agent to write a standalone `eval.py` scorer. The scorer is a
plain Python script: it reads the implementation under test from a directory passed via the
`REPO_DIR` environment variable, exercises it against the specification, and prints a single
`EVAL_SCORE=<float>` verdict. We then run the agent's scorer against each held-out solution and
measure how well it separates golden from broken.

The held-out task is a **balanced-bracket checker** — a single function `is_balanced(text: str) ->
bool`. We pick a small, pure-Python task on purpose so (a) the agent never needs to see the golden
solution to derive good tests, and (b) the scorer only needs the standard library — it runs in the
base image with no extra dependencies.

The three held-out implementations are carried as fixtures and never touch the workspace during
`arrange` or `act`. The agent receives only the task specification in the act prompt; the solutions
themselves are staged in `score()`, after the agent has finished its work.

> [!TIP]
> This eval uses no private repositories and no external services, so it needs no credentials at
> all. It is the simplest eval in the suite to run and a good smoke-test for a new agent
> configuration.

The values each phase needs are a mix of directory paths and files pulled from the eval's
`fixtures/` directory via [`read_eval_fixture`](../helpers.md) — the prompt for `act`, and the
three held-out solutions for `score` (see [embedded values](../../README.md#embedded-values)).

```python
arrange_embedded_values = {
    "DESIGNER_EVAL_DIR": "/workspace/brackets_eval",
}

act_embedded_values = {
    "DESIGNER_EVAL_DIR": "/workspace/brackets_eval",
    "PROMPT":            read_eval_fixture(__file__, "prompt.md"),
}

score_embedded_values = {
    "DESIGNER_EVAL_DIR":  "/workspace/brackets_eval",
    "GOLDEN_DIR":         "/workspace/golden",
    "BROKEN_WRONG_DIR":   "/workspace/broken_wrong",
    "BROKEN_CRASH_DIR":   "/workspace/broken_crash",
    "GOLDEN_IMPL":        read_eval_fixture(__file__, "golden.py"),
    "BROKEN_WRONG_IMPL": read_eval_fixture(__file__, "broken_wrong.py"),
    "BROKEN_CRASH_IMPL":  read_eval_fixture(__file__, "broken_crash.py"),
    "PASS_THRESHOLD":     0.8,
    "FAIL_THRESHOLD":     0.2,
}
```

## Evaluation Details

### arrange

The arrange phase is deliberately minimal: it just creates the empty workspace directory the agent
will work in. There is no repo to clone, no MCP server to start, and — critically — no held-out
solutions staged on disk.

```python
os.makedirs(DESIGNER_EVAL_DIR, exist_ok=True)
```

The held-out solutions are **never** written during `arrange` because `arrange` and `act` run in the
same container as the same user, so anything `arrange` puts on disk is readable by the agent via
`bash` during `act`. Staging the solutions in `score()` — which runs after `act()` has finished — is
the only way to keep them hidden.

### act

The act phase calls `AgentShell` and hands it the prompt fixture. That prompt describes the task
specification (a balanced-bracket checker) and asks the agent to write `eval.py` into the workspace
directory. There are no tools to disable, no repos to navigate — the agent has everything it needs
in the prompt.

```python
shell = AgentShell(AgentType(os.environ["AGENT_TYPE"]))
response = await shell.execute(
    cwd=DESIGNER_EVAL_DIR,
    prompt=PROMPT,
    model=os.environ["AGENT_MODEL"],
    effort=os.environ["AGENT_EFFORT"],
)
```

The [prompt](../../example_evals/eval_generator/fixtures/prompt.md) tells the agent exactly what
bracket types to handle, what the `REPO_DIR` contract is, and what output format is expected. It
contains no link to the eval-harness repository and no hint about what the held-out solutions look
like — the agent derives its tests purely from the specification.

### score

Scoring has three steps: stage the held-out solutions, run the agent's scorer against each one, and
compute a discrimination score.

First we verify the agent produced a file. If `eval.py` doesn't exist, the run scores zero — the
agent failed to deliver.

```python
eval_path = os.path.join(DESIGNER_EVAL_DIR, "eval.py")
if not os.path.isfile(eval_path):
    print(f"No {DESIGNER_EVAL_DIR} created, evaluation failed")
    print("EVAL_SCORE=0.0")
    return
```

Then we stage the three solutions. Each gets its own directory with a `bracket_balance.py`:

```python
solutions = {
    "golden":       (GOLDEN_DIR,       GOLDEN_IMPL),
    "broken_wrong": (BROKEN_WRONG_DIR, BROKEN_WRONG_IMPL),
    "broken_crash":  (BROKEN_CRASH_DIR,  BROKEN_CRASH_IMPL),
}
for dirpath, body in solutions.values():
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "bracket_balance.py"), "w") as f:
        f.write(body)
```

Each solution is run through the agent's scorer in a subprocess, with `REPO_DIR` pointed at the
staged solution. The scorer's verdict is scraped from stdout — the last `EVAL_SCORE=<float>` line
wins — and clamped to `[0.0, 1.0]`. If the scorer crashes, times out, or prints no verdict, that
run scores `0.0`.

```python
def run_against(label, repo_dir):
    try:
        proc = subprocess.run(
            ["python", eval_path],
            env={**os.environ, "REPO_DIR": repo_dir},
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return 0.0
    scraped = None
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("EVAL_SCORE="):
            raw = line.removeprefix("EVAL_SCORE=")
            try:
                scraped = max(0.0, min(1.0, float(raw)))
            except ValueError:
                scraped = None
            break
    return 0.0 if scraped is None else scraped
```

The final score is a **discrimination** term — the golden score minus the average of the two broken
scores, clamped to zero:

```python
golden        = run_against("golden", GOLDEN_DIR)
broken_wrong  = run_against("broken_wrong", BROKEN_WRONG_DIR)
broken_crash  = run_against("broken_crash", BROKEN_CRASH_DIR)

avg_broken = (broken_wrong + broken_crash) / 2
discrimination = max(0.0, golden - avg_broken)

print(f"EVAL_SCORE={discrimination}")
```

So a perfect scorer — one that awards `1.0` to golden and `0.0` to both broken implementations —
scores `1.0`. A scorer that gives the same verdict to everything (or scores the broken
implementations higher than golden) scores `0.0`. The discrimination formula rewards *separation*:
what matters is the gap between correct and incorrect, not the absolute values.

### The broken implementations

The two broken solutions fail in deliberately different ways so a single narrow check can't catch
both:

- **`broken_wrong`**: counts bracket depth but ignores nesting order and type matching.
  `([)]` returns `True` here (it should be `False`). The function still runs cleanly — no
  exceptions — so a scorer that only checks for crashes would be fooled.

- **`broken_crash`**: raises `ValueError` on any square bracket, a hard crash rather than a subtle
  logic error. A scorer that only checks return values would miss this entirely if the raised
  exception isn't caught, because the subprocess wrapper treats non-zero exits as `0.0` scores
  rather than propagating the crash. But `EVAL_SCORE=` scraping works regardless — the agent's
  scorer catches the exception, scores low, and prints its verdict.

These two failure modes span the range from "wrong answer, clean exit" to "crashes immediately," so
the agent *must* cover the specification broadly — a single narrow check will be fooled by one or
the other.

> [!WARNING]
> **Design limitation — only the scorer is measured.** Whatever `arrange()` or `act()` the agent
> would write for its own evaluation is neither run nor graded. A correct scorer paired with a
> broken act (wrong working directory, bad prompt shape, missing setup, etc.) still scores full
> marks here. This eval measures one sub-skill of eval authoring — the ability to build a
> discriminating scoring oracle — not the full end-to-end ability to produce a working eval-harness
> evaluation.

> [!NOTE]
> Unlike the other evals in the suite, there is no repo clone and no git remote to sever — the task
> is purely synthetic. This makes it the fastest example eval in the suite to run and the simplest to
> extend. To adapt it to a new task, replace the three fixture files (`golden.py`, `broken_wrong.py`,
> `broken_crash.py`) and the prompt — the scoring harness itself needs no changes as long as the
> `REPO_DIR` → `bracket_balance.py` → `is_balanced` contract holds (or is renamed consistently
> across all four files).
