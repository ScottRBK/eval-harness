"""
This evaluation asks an agent to implement a standard chess move generator in Rust.

We clone a scaffolded repo whose `src/lib.rs` exposes a frozen `Board` API (from_fen /
legal_moves / make_move) stubbed with `unimplemented!()`. The agent fills in the bodies.

The graded tests are a hidden perft suite. Unlike the inflection eval (which leaves the tests
in the repo and restores them from git at score time), the tests here are NOT in the cloned
repo or its git history at all. They live as a fixture in this eval and are injected into the
working tree only during score(). This keeps the answer key (the perft driver and the canonical
expected counts) entirely out of anything the agent can see during act, which is the reusable
pattern for evals where the tests themselves would hand the agent too much information.

Anti-cheat: the move-generation primitives never receive a position+depth, so the published
counts cannot be hard-coded into them. score() additionally rejects any third-party dependency
(std-only is required), and act() disallows web search/fetch so engine source cannot be pulled.
"""

from src.helpers.file_helper import read_eval_fixture

REPO_URL = ""
REPO_REF = ""
REPO_DIR = ""
PROMPT = ""
INTEGRATION_TESTS = ""


class ChessEngine:
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

        # Drop the remote so the agent can't push changes back or pull anything else, and so the
        # tagged history (which never contained the tests anyway) can't be re-fetched.
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
            prompt=PROMPT,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
            disallowed_tools=["web_search", "web_fetch"],
        )
        print(response.response)
        print(f"Cost: ${response.cost:.4f}")
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        import os
        import re
        import tomllib
        import subprocess

        EXPECTED_TESTS = 24

        try:
            with open(os.path.join(REPO_DIR, "Cargo.toml"), "rb") as f:
                manifest = tomllib.load(f)
            for table in ("dependencies", "dev-dependencies", "build-dependencies"):
                if manifest.get(table):
                    print(f"Third-party dependency found in [{table}] - std-only required")
                    print("EVAL_SCORE=0.0")
                    return

            # Inject the hidden perft suite. We overwrite unconditionally so anything the agent
            # may have placed at this path during act is replaced by our canonical fixture.
            tests_dir = os.path.join(REPO_DIR, "tests")
            os.makedirs(tests_dir, exist_ok=True)
            with open(os.path.join(tests_dir, "integration_tests.rs"), "w") as f:
                f.write(INTEGRATION_TESTS)

            # --release so perft (millions of nodes) runs fast enough; --test isolates our target.
            # Don't pass check=True: cargo exits non-zero when tests fail, and docker_runner raises
            # on a non-zero phase exit. We parse the summary line instead.
            result = subprocess.run(
                ["cargo", "test", "--release", "--test", "integration_tests"],
                cwd=REPO_DIR,
                capture_output=True,
                text=True,
            )
            print(result.stdout)
            print(result.stderr)

            match = re.search(r"(\d+) passed; (\d+) failed", result.stdout)
            if not match:
                print("No test result line found (compile failure or no tests ran)")
                print("EVAL_SCORE=0.0")
                return

            passed, failed = int(match.group(1)), int(match.group(2))
            if passed + failed != EXPECTED_TESTS:
                print(f"Test count mismatch: ran {passed + failed}, expected {EXPECTED_TESTS}")
                print("EVAL_SCORE=0.0")
                return

            score = passed / EXPECTED_TESTS
            print(f"EVAL_SCORE={score:.4f}")

        except Exception as e:
            print(f"Error scoring chess engine eval: {e}")
            print("EVAL_SCORE=0.0")
