# [Bug Fix with Automated Tests](../../example_evals/inflection_bug_fix)

This eval measures two things:
1. The ability of an agent to diagnose and fix bugs in a codebase it has never seen before.
1. The ability to do so guided only by a failing test suite - *without* cheating by editing the
   tests to make them go green.

## Overview
For this example we are using a fork of [inflection](https://github.com/jpvanhal/inflection), a
small, pure-Python library that ports Rails' string inflections (`pluralize`, `camelize`,
`ordinalize`, and friends). It is a nice fit for this pattern because it is a single module backed
by a large, heavily parametrised `pytest` suite - **455 tests** - so there is a rich, unambiguous
ground truth to grade against.

The fork lives at [ScottRBK/inflection](https://github.com/ScottRBK/inflection) on the `eval-v1`
ref, and it has **three bugs injected** into `inflection/__init__.py`. Those three bugs break
**34** of the 455 tests. The agent's job is simply to make them pass again. Two of the three
claim a second victim through a call dependency - `pluralize` breaks `tableize` (which calls it),
and `camelize` breaks the `underscore` doctest (whose example calls `camelize`) - so fixing the root
cause can green tests the agent never directly touched.

The defining feature of this pattern is that, unlike a hidden-test eval, **the agent can see and
edit the test file**. It lives right there in the workspace and we even tell the agent to run it.
That makes the whole eval an exercise in tamper-proof scoring: everything below is built so that the
score reflects real production fixes and not an agent quietly rewriting a test to pass. The two ways
to keep tests honest - restore-from-git (used here) versus fixture-injection - are contrasted in
the [new feature](./new_feature.md) pattern, which sits at the opposite end of that spectrum.

> [!TIP]
> `inflection` is a public library, so the clone here runs anonymously and is only meant to
> demonstrate the pattern. For a real bug-fix eval you would normally inject the bugs into a
> **private** fork, so the untouched upstream code isn't a `git clone` away for the agent. To do
> that, set `EVAL_HARNESS_GITHUB_TOKEN` in `.env` and add the `gh auth setup-git` guard shown in
> [search_with_qa](./search_with_qa.md); the harness injects the token as `GH_TOKEN` so the HTTPS
> clone authenticates. See [authorisation](../authorisation.md#private-repositories-harness-level-github-token)
> for details.

Unlike the search-with-Q&A eval, there are no fixtures or helper calls here. The only values the
phases need are the repo coordinates, so they are declared inline as literals in the per-phase
embedded-value dicts (see [embedded values](../../README.md#embedded-values)).

```python
arrange_embedded_values = {
    "REPO_URL": "https://github.com/ScottRBK/inflection",
    "REPO_REF": "eval-v1",
    "REPO_DIR": "/workspace/inflection"
}
```

## Evaluation Details

### arrange
The arrange phase clones the fork into the workspace. It is a shallow clone pinned to the `eval-v1`
ref, so we land on a fixed, immutable snapshot of the buggy code - checking out a pinned ref lands
us in a detached HEAD, which is exactly why `advice.detachedHead=false` is set to keep the output
quiet.

```python
subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
         "--depth", "1", "--branch", REPO_REF, REPO_URL, REPO_DIR],
        check=True,
      )
```

The one non-obvious step is that we then remove the git remote. Because the agent has a live shell
in this repo it could, in principle, commit and push its work - or its test edits - back to the
fork, which would contaminate scoring and poison every future run of the eval. Severing `origin`
closes that door entirely.

```python
# We do this so that the agent cannot push any of their changes or test changes back to
# the remote branch, potentially contaminating scoring and or future evals
subprocess.run(["git", "-C", REPO_DIR, "remote", "remove", "origin"])
```

### act
The act phase is deliberately thin. We build an `AgentShell` for the agent under test and hand it a
single prompt: run the tests, find the bugs, fix them, and don't touch the tests. There are no
fixtures to write and no tools to disable - the agent has free rein of the workspace.

```python
shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
response = await shell.execute(
    cwd=REPO_DIR,
    prompt="""Please can you run the tests in this repo and fix the bugs, please do not
    modify the tests in anyway, just find and fix the bugs in the repo""",
    model=os.environ["AGENT_MODEL"],
    effort=os.environ["AGENT_EFFORT"],
)
```

Note that "please do not modify the tests" is a *request*, not a guarantee. The agent might edit the
tests anyway - by accident or to force a pass - so we never rely on it. Enforcement happens in
`score`, not here.

### score
Before grading anything, we restore the pristine test file straight out of git and clear any stale
bytecode. This is the enforcement half of the tamper-proofing: whatever the agent did to
`test_inflection.py` - edited it, deleted a case, even committed the change - `git checkout` at the
pinned ref overwrites it with the original. It is a purely local operation, so it works even though
we removed the remote in `arrange`.

```python
# restore the original tests  just in case the agent has modified them
subprocess.run(["git", "-C", REPO_DIR, "checkout", REPO_REF, "--", "test_inflection.py"])
subprocess.run(["rm", "-rf", os.path.join(REPO_DIR, "inflection", "__pycache__")])
```

We then run the tests, but only the test file, and emit a JUnit XML report rather than scraping
stdout. Parsing the machine-readable report is far more robust than regexing `pytest`'s console
output. Scoping the run to `test_inflection.py` (instead of the whole `tox` target) also collects
zero doctests - which is why the baseline is **34** broken unit tests here, not the 39 you get once
the doctest failures are included.

```python
report = "/tmp/report.xml"
subprocess.run(["uv", "run", "--no-project", "--with", "pytest", "pytest", "test_inflection.py",
                f"--junitxml={report}"], cwd=REPO_DIR, capture_output=True, text=True)
suite = ET.parse(report).getroot().find("testsuite")
```

If there is no test suite in the report we bail out with a zero. We also guard on the total test
count: if the number of collected tests isn't exactly what we expect, something structural has
changed - a broken import from a bad fix, a deleted test, an added one - and the "34 broken"
baseline no longer means anything, so we score it a hard zero.

```python
TOTAL_TESTS = 455
tests = int(suite.get("tests", "0"))
if tests != TOTAL_TESTS:
    print("Error for Inflection Bub Fix eval, tests do not align")
    print("EVAL_SCORE=0.0")
    return
```

With the run validated, the score is just the fraction of the originally-broken tests that the agent
brought back to green. We count failures *and* errors as still-broken, and clamp at zero so that a
fix which introduces brand-new failures can never drag the score negative.

```python
BROKEN_TESTS = 34
failed = int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
score = max(0.0, (BROKEN_TESTS - failed) / BROKEN_TESTS)
print(f"EVAL_SCORE={score:.4f}")
```

So a no-op run leaves all 34 failing and scores `0`, fixing half of them scores `0.5`, and a clean
fix-to-green scores `1`. The whole thing is wrapped in a `try/except` that emits `EVAL_SCORE=0.0` on
any failure, and as with the other evals this final print is what the eval harness collects back out
of the container.

> [!WARNING]
> Restore-from-git makes the tests tamper-proof, but it is not bullet-proof: an agent that deletes
> the `eval-v1` ref or the `.git` directory outright would leave nothing to restore *from*. This
> pattern is the right choice when seeing the tests doesn't reveal the answer. When the test
> contents themselves would hand the agent the solution, reach for **fixture-injection** instead -
> where the harness owns the test bytes and writes them in at score time - as demonstrated by the
> [new feature](./new_feature.md) eval.
