"""
Terminal-task evaluation: repair_nginx_service.

This eval grades whether an agent leaves a realistic terminal environment in the
required final state.  The agent receives a Docker container with Nginx
installed but stopped and misconfigured.  It must repair the configuration and
leave a working Nginx service.

The instruction is loaded through `act_embedded_values` and the hidden tests
through `score_embedded_values`. The oracle is never embedded into a runtime
phase. Hidden artifacts remain outside the Docker build context (fixtures/image/).

Scoring is binary: all hidden checks pass → 1.0, any failure → 0.0.  Evaluator
or fixture defects raise so the run is marked FAILED rather than scoring zero.
"""

from src.helpers.file_helper import read_eval_fixture

INSTRUCTION = ""
TESTS = ""


class RepairNginxService:
    dockerfile = "fixtures/image/Dockerfile"

    act_embedded_values = {
        "INSTRUCTION": read_eval_fixture(__file__, "instruction.md"),
    }

    score_embedded_values = {
        "TESTS": read_eval_fixture(__file__, "tests.py"),
    }

    async def arrange(self) -> None:
        import os
        import subprocess

        # Confirm the expected starting files exist.
        required = ["/srv/site/index.html", "/etc/nginx/nginx.conf"]
        for path in required:
            if not os.path.exists(path):
                raise RuntimeError(f"Starting file missing from image: {path}")

        # Ensure Nginx is stopped — the custom image owns the starting state,
        # but a stale process would interfere.
        subprocess.run(["nginx", "-s", "stop"], capture_output=True)
        print("arrange complete: starting files present, nginx stopped")

    async def act(self) -> None:
        import os
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))

        print("calling agent for repair_nginx_service")
        response = await shell.execute(
            cwd="/tmp",
            prompt=INSTRUCTION,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
        )
        print(response.response)
        print(f"Session: {response.session_id}")

    async def score(self) -> None:
        import subprocess

        # Send the hidden tests directly to isolated Python. No agent-writable
        # file is created for a still-running agent process to replace.
        try:
            result = subprocess.run(
                ["python", "-I", "-"],
                input=TESTS,
                capture_output=True,
                text=True,
                timeout=120,
            )
            print(result.stdout)
            if result.stderr.strip():
                print(result.stderr)
        except Exception as e:
            raise RuntimeError(f"Hidden test runner crashed: {e}") from e

        if result.returncode != 0:
            raise RuntimeError(f"Hidden tests exited with code {result.returncode}")

        # Extract the EVAL_SCORE marker printed by tests.py.
        score = None
        for line in result.stdout.splitlines():
            if line.startswith("EVAL_SCORE="):
                raw = line.removeprefix("EVAL_SCORE=").strip()
                try:
                    score = float(raw)
                except ValueError as e:
                    raise RuntimeError(f"Malformed score line {line!r}") from e
                break

        if score is None:
            raise RuntimeError("Hidden tests produced no EVAL_SCORE marker")

        print(f"EVAL_SCORE={score:.1f}")
