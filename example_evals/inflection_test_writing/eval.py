"""
This eval inverts the bug_fix pattern: instead of grading the agent's code with our tests, it
grades the agent's TESTS with our code. The agent is handed inflection (pinned upstream 0.5.1)
with its test suite deleted and is asked to write one.
In addition to this, There is no pyproject.toml file  and no pytest installed in the container image,
so the agent has to figure this out.
score() then grades the suite by mutation testing: the harness holds a set of small behavioural
faults (mutants) as a fixture, applies them to the module one at a time, and scores the fraction of
mutants the suite kills (at least one test fails).

The harness owns the truth end to end - fixture-injection applied to the source itself:
- The pristine module bytes live in a fixture and are written over whatever the agent left at
  the module path, so source tampering can't help.
- Gate: the suite must be green against the pristine module before kills count (a suite that
  always fails would otherwise "kill" everything), and must collect at least one test.
- Mutants are find/replace edits against the pinned source, validated fail-closed: a
  find-string that doesn't match exactly once voids the run.

Anti-cheat layers:
- arrange deletes test_inflection.py AND .git wholesale - with history present the upstream
  455-test suite is one `git show` away, and it is the answer key here.
- Two canary mutants (a comment-only edit and a behaviour-preserving refactor) must NOT be
  killed: a suite that fails on them is diffing source bytes or AST rather than testing
  behaviour, and scores zero.
- Every real mutant is chosen to survive the module's own docstring examples, so delegating
  to doctest catches nothing. This is a load-bearing invariant of the mutant set - keep it in
  mind when adding mutants.
- act() disallows web search/fetch - the upstream suite is public.
"""

from src.helpers.file_helper import read_eval_fixture

REPO_URL = ""
REPO_REF = ""
REPO_DIR = ""
MODULE_RELPATH = ""
PROMPT = ""
PRISTINE_MODULE = ""
MUTANTS_DOC = ""


class InflectionTestWriting:
    arrange_embedded_values = {
        "REPO_URL": "https://github.com/jpvanhal/inflection",
        "REPO_REF": "0.5.1",
        "REPO_DIR": "/workspace/inflection",
    }

    act_embedded_values = {
        "REPO_DIR": "/workspace/inflection",
        "PROMPT": read_eval_fixture(__file__, "prompt.md"),
    }

    score_embedded_values = {
        "REPO_DIR": "/workspace/inflection",
        "MODULE_RELPATH": "inflection/__init__.py",
        "PRISTINE_MODULE": read_eval_fixture(__file__, "pristine_module.py"),
        "MUTANTS_DOC": read_eval_fixture(__file__, "mutants.json"),
    }

    async def arrange(self) -> None:
        import os
        import subprocess

        print("cloning github repo")
        subprocess.run(
            [
                "git",
                "-c",
                "advice.detachedHead=false",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--branch",
                REPO_REF,
                REPO_URL,
                REPO_DIR,
            ],
            check=True,
        )
        print("repo cloned")

        print("removing upstream test suite and git history")
        subprocess.run(["rm", "-rf", os.path.join(REPO_DIR, ".git")], check=True)
        subprocess.run(
            [
                "rm",
                "-f",
                os.path.join(REPO_DIR, "test_inflection.py"),
                os.path.join(REPO_DIR, "tox.ini"),
            ],
            check=True,
        )
        print("upstream test suite and git history removed")

    async def act(self) -> None:
        import os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))

        print("calling agent")
        response = await shell.execute(
            cwd=REPO_DIR,
            prompt=PROMPT,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
            disallowed_tools=["web_search", "web_fetch"],
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        import json
        import os
        import subprocess
        import xml.etree.ElementTree as ET

        try:
            module_path = os.path.join(REPO_DIR, MODULE_RELPATH)
            pycache = os.path.join(os.path.dirname(module_path), "__pycache__")

            # Fail closed: every find-string must appear exactly once in the pinned source,
            # otherwise the mutant fixture has drifted from the ref and no score is meaningful.
            mutants = json.loads(MUTANTS_DOC)
            for mutant in mutants:
                if PRISTINE_MODULE.count(mutant["find"]) != 1:
                    print(f"fixture error: find-string for '{mutant['name']}' not unique")
                    print("EVAL_SCORE=0.0")
                    return

            def run_suite(module_source, junit_path=None):
                with open(module_path, "w") as f:
                    f.write(module_source)
                subprocess.run(["rm", "-rf", pycache])
                cmd = ["uv", "run", "--no-project", "--with", "pytest", "pytest", "-q"]
                if junit_path:
                    cmd.append(f"--junitxml={junit_path}")
                return subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True)

            # Gate: overwrite whatever the agent left at the module path with the pristine
            # fixture copy and require the suite to be green against it before kills count.
            report = "/tmp/report.xml"
            result = run_suite(PRISTINE_MODULE, junit_path=report)
            suite = ET.parse(report).getroot().find("testsuite")
            if suite is None:
                print("no testsuite found in junit report")
                print("EVAL_SCORE=0.0")
                return

            tests = int(suite.get("tests", "0"))
            failed = int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
            print(f"gate: {tests} tests collected, {failed} failing against pristine module")
            if tests == 0 or failed > 0:
                print("suite must exist and be green on the pristine module")
                print("EVAL_SCORE=0.0")
                return

            killed = 0
            real_total = 0
            for mutant in mutants:
                mutated = PRISTINE_MODULE.replace(mutant["find"], mutant["replace"])
                result = run_suite(mutated)
                # 0 = all passed (survived); 1 = test failures, 2 = collection/import error
                # (both count as killed). Anything else means pytest itself misbehaved and
                # no score is trustworthy.
                if result.returncode not in (0, 1, 2):
                    print(f"unexpected pytest exit {result.returncode} on '{mutant['name']}'")
                    print("EVAL_SCORE=0.0")
                    return
                was_killed = result.returncode != 0
                status = "KILLED" if was_killed else "SURVIVED"
                print(f"[{status}] {mutant['name']}: {mutant['description']}")

                if mutant["canary"]:
                    if was_killed:
                        print("canary killed - suite is diffing source, not testing behaviour")
                        print("EVAL_SCORE=0.0")
                        return
                else:
                    real_total += 1
                    if was_killed:
                        killed += 1

            # leave the workspace on the pristine module
            with open(module_path, "w") as f:
                f.write(PRISTINE_MODULE)

            score = killed / real_total
            print(f"killed {killed}/{real_total} mutants")
            print(f"EVAL_SCORE={score:.4f}")

        except Exception as e:
            print(f"Error scoring inflection test writing eval: {e}")
            print("EVAL_SCORE=0.0")
