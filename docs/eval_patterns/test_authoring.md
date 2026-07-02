# [Test Authoring](../../example_evals/inflection_test_writing)

This eval measures an agent's ability to:

1. Read and comprehend an unfamiliar repository.
1. Turn that comprehension into a pytest suite that pins down the library's current behaviour.
1. Work around a missing test-tooling baseline (no `pytest` pre-installed, no `pyproject.toml`).

## Overview

We revisit [inflection](https://github.com/jpvanhal/inflection) for this pattern, because it is
effectively the inverse of the [Bug Fix](./bug_fix.md) pattern. In Bug Fix we hand the agent a
failing suite and grade the code it writes to make it pass; here we hand the agent the code with its
suite deleted and grade the **tests** it writes, by mutating the code and measuring how many of the
faults the suite catches. Mutation testing is the scoring mechanism: the harness owns a set of small
behavioural faults (mutants) as a fixture, applies them to the module one at a time, and scores the
fraction of mutants the suite kills.

The harness owns the truth end to end through **fixture-injection** applied to the source itself:
the pristine module bytes live in a fixture and are written over whatever the agent left at the
module path, so source tampering can't help.

> [!TIP]
> `inflection` is public, so the clone runs anonymously. To use a private library instead, include
> the `gh auth setup-git` phase shown in [search_with_qa](./search_with_qa.md).

## Evaluation Details

### arrange
Clone the repo at a pinned ref, then remove the upstream test suite **and** the `.git` directory
wholesale. With history present the upstream 455-test suite is one `git show` away, and it *is* the
answer key here, so the history has to go.

We also delete `tox.ini`. inflection's `tox.ini` carries a `[pytest]` section with
`addopts = --doctest-modules`, so a bare `pytest` from the repo root would pick that up and run the
module's docstring examples as part of the suite. Removing it in `arrange` keeps what the agent
experiences during `act` (bare pytest, no config) identical to how it will be scored - the agent
isn't developing against a doctest-inclusive run only to be graded without one.

### act
Thin by design. We build an `AgentShell`, hand it the prompt, and disallow `web_search` and
`web_fetch` - the upstream suite is public, so the agent can't just go and fetch the answer key.

### score
Score is where the mutation testing happens. We build the module path and capture the `__pycache__`
directory up front: each mutant run writes new source bytes to the module path, and we wipe
`__pycache__` before every run so the interpreter recompiles from what we just wrote rather than
serving a stale `.pyc` from a previous mutant.

Before any kills count, the suite must pass a **gate**: we overwrite the module with the pristine
fixture and require the suite to be green against it and to collect at least one test. The gate
exists to defeat the degenerate always-failing suite - without it, a suite that fails on the
pristine module would "kill" every mutant and score full marks for nothing. A trivially-passing
suite (`assert 1 == 1`) passes the gate but kills no mutants, so the mutation score already encodes
"vacuous suite → zero"; the gate is only the guardrail against the opposite extreme.

For each mutant we overwrite the module with the mutated source, run the suite under bare
`uv run --no-project --with pytest pytest`, and count it **killed** if pytest exits non-zero (test
failures or collection errors). The score is the fraction of real mutants killed:

```python
score = killed / real_total
print(f"EVAL_SCORE={score:.4f}")
```

### Canaries
Two mutants are marked `"canary": true` and must **not** be killed: a comment-only edit, and a
behaviour-preserving refactor that changes the AST but not the output. A suite that fails on either
is diffing source bytes or AST rather than testing behaviour, and the run scores a hard zero. This
is the anti-cheat layer that catches an agent that tries to "test" by comparing the module's source
text against a saved copy.

### The mutant-set invariant
Every real mutant is deliberately chosen to **survive the module's own docstring examples**, so an
agent that just transcribes the `>>>` lines into `test_*.py` (or leans on `--doctest-modules`)
kills nothing and scores zero. This is a load-bearing property of the fixture set: when you add a
mutant, verify it doesn't alter any documented example, or the doctest shortcut will start scoring
for free. The defense lives in the mutant curation, not in runtime config cleanup.
