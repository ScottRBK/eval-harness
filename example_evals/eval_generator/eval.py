"""
This evaluation measures an agent's ability to write a scoring routine that discriminates a
correct implementation of a small task from incorrect ones. It does NOT test the agent's ability
to author a full eval-harness evaluation — only the scoring logic is measured; the arrange and act
phases of the agent's deliverable are never exercised (see the design-limitation note below).

Concept: we hold three implementations of a pure-Python task — one golden (correct) and two broken
that fail in *different* ways — and ask the agent to write a `python eval.py` scorer that tests a
`bracket_balance.py` implementation and prints a `EVAL_SCORE=<float>` verdict. We then run the
agent's scorer against each held-out solution and measure how well it separates golden from broken.

The score is made up of a discrimination term (golden minus average-broken, clamped to >= 0), 

Held-out task (fixtures/prompt.md): a balanced-bracket checker. We pick a small pure-Python task on
purpose so (a) the agent never needs to see the golden solution to derive good tests, and (b) the
scorer only needs the stdlib — it runs in the base image with no extra deps.

Workspaces:
  act()   -> the agent writes its eval.py scorer into DESIGNER_EVAL_DIR (it creates the dir).
  score() -> stages the three held-out solutions (golden / broken_wrong / broken_crash), each with a
             bracket_balance.py, then runs the agent's scorer against each via subprocess, setting
             REPO_DIR to point at the staged solution each time. The verdict (last EVAL_SCORE= line)
             is scraped from stdout.

ANSWER-KEY ISOLATION (critical): arrange/act/score execute as separate `python -c` execs but in
the SAME long-lived container, all as the `node` user (see src/docker/Dockerfile + docker_runner).
So anything written to disk during arrange is readable by the agent during act() via bash — a
same-UID leak a chmod can't fix. The held-out solutions are therefore NEVER written during arrange;
they are staged in score(), which runs only after act() has finished. The task spec is delivered to
the agent solely via the act prompt (act_embedded_values), never as a file on disk. And the prompt
contains no link to the repo contents, so the agent cannot browse the fixtures from GitHub either.

Design limitation (be honest about coverage): only the scorer is measured. Whatever arrange()/act()
the agent writes is neither run nor graded. A correct scorer paired with a broken act() (wrong cwd,
bad prompt shape, etc.) still scores full marks here. This eval measures one sub-skill of eval
authoring, not the whole thing.
"""
from src.helpers.file_helper import read_eval_fixture

# Module-level placeholders keep linters happy; they are NEVER shipped to the container.
DESIGNER_EVAL_DIR = ""
GOLDEN_DIR = ""
BROKEN_WRONG_DIR = ""
BROKEN_CRASH_DIR = ""
GOLDEN_IMPL = ""
BROKEN_WRONG_IMPL = ""
BROKEN_CRASH_IMPL = ""
PROMPT = ""


class EvalGenerator:

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

    async def arrange(self) -> None:
        import os  
        os.makedirs(DESIGNER_EVAL_DIR, exist_ok=True)

    async def act(self):
        import os 
        from agent_shell.shell import  AgentShell
        from agent_shell.models.agent import AgentType

        shell = AgentShell(AgentType(os.environ["AGENT_TYPE"]))
        response = await shell.execute(
            cwd=DESIGNER_EVAL_DIR,
            prompt=PROMPT,
            model=os.environ["AGENT_MODEL"],
            effort=os.environ["AGENT_EFFORT"],
        )

        print(response.response)
        print(f"Session: {response.session_id}")


    async def score(self):
        import os
        import subprocess

        eval_path = os.path.join(DESIGNER_EVAL_DIR, "eval.py")

        if not os.path.isfile(eval_path):
            print(f"No {DESIGNER_EVAL_DIR} created, evaluation failed")
            print("EVAL_SCORE=0.0")
            return

        solutions = {
            "golden":       (GOLDEN_DIR,       GOLDEN_IMPL),
            "broken_wrong": (BROKEN_WRONG_DIR, BROKEN_WRONG_IMPL),
            "broken_crash":  (BROKEN_CRASH_DIR,  BROKEN_CRASH_IMPL),

        }
        for dirpath, body in solutions.values():
            os.makedirs(dirpath, exist_ok=True)
            with open(os.path.join(dirpath, "bracket_balance.py"), "w") as f:
                f.write(body)

        def run_against(label, repo_dir):
            # Run the agent's scorer against one staged solution, return its 0..1 verdict.
            try:
                proc = subprocess.run(
                    ["python", eval_path],
                    env={**os.environ, "REPO_DIR": repo_dir},
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except (subprocess.TimeoutExpired, OSError) as e:
                print(f"[diag {label}] run error: {e!r}")
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
            print(f"[diag {label}] exit={proc.returncode} scraped={scraped!r}")
            if proc.returncode != 0 or scraped is None:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
                for t in tail:
                    print(f"[diag {label}]   {t}")
            return 0.0 if scraped is None else scraped

        golden        = run_against("golden", GOLDEN_DIR)
        broken_wrong  = run_against("broken_wrong", BROKEN_WRONG_DIR)
        broken_crash  = run_against("broken_crash", BROKEN_CRASH_DIR)

        avg_broken = (broken_wrong + broken_crash) / 2
        discrimination = max(0.0, golden - avg_broken)

        print(f"golden={golden} broken_wrong={broken_wrong} broken_crash={broken_crash} "
              f"discrimination={discrimination}")
        print(f"EVAL_SCORE={discrimination}")
