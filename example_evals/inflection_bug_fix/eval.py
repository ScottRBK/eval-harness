"""
This eval sees a forked version of https://github.com/jpvanhal/inflection in which three bugs
 have been injected to the code that the agent must fix
"""

REPO_URL = ""
REPO_REF = ""
REPO_DIR = ""


class InflectionBugFix:
    arrange_embedded_values = {
        "REPO_URL": "https://github.com/ScottRBK/inflection",
        "REPO_REF": "eval-v1",
        "REPO_DIR": "/workspace/inflection",
    }

    act_embedded_values = {"REPO_DIR": "/workspace/inflection"}

    score_embedded_values = {
        "REPO_DIR": "/workspace/inflection",
        "REPO_REF": "eval-v1",
    }

    async def arrange(self) -> None:

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

        # We do this so that the agent cannot push any of their changes or test changes back to
        # the remote branch, potentially contaminating scoring and or future evals
        print("removing git remote link")
        subprocess.run(["git", "-C", REPO_DIR, "remote", "remove", "origin"])
        print("git remote link removed")

    async def act(self) -> None:
        import os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
        print("calling agent")
        response = await shell.execute(
            cwd=REPO_DIR,
            prompt="""Please can you run the tests in this repo and fix the bugs, please do not
            modify the tests in anyway, just find and fix the bugs in the repo""",
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
        )

        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        import os
        import subprocess
        import xml.etree.ElementTree as ET

        try:
            # restore the original tests  just in case the agent has modified them
            subprocess.run(
                ["git", "-C", REPO_DIR, "checkout", REPO_REF, "--", "test_inflection.py"]
            )
            subprocess.run(["rm", "-rf", os.path.join(REPO_DIR, "inflection", "__pycache__")])

            report = "/tmp/report.xml"

            subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--with",
                    "pytest",
                    "pytest",
                    "test_inflection.py",
                    f"--junitxml={report}",
                ],
                cwd=REPO_DIR,
                capture_output=True,
                text=True,
            )

            suite = ET.parse(report).getroot().find("testsuite")

            if suite is None:
                print("EVAL_SCORE=0.0")
                return

            TOTAL_TESTS = 455
            tests = int(suite.get("tests", "0"))
            if tests != TOTAL_TESTS:
                print("Error for Inflection Bub Fix eval, tests do not align")
                print("EVAL_SCORE=0.0")
                return

            BROKEN_TESTS = 34
            failed = int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
            score = max(0.0, (BROKEN_TESTS - failed) / BROKEN_TESTS)
            print(f"EVAL_SCORE={score:.4f}")

        except Exception as e:
            print(f"Error scoring inflection bug fix eval: {e}")
            print("EVAL_SCORE=0.0")
