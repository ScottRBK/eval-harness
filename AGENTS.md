# AGENTS.md

## What this is

A Python framework that runs CLI coding agents (Claude Code, OpenCode, Copilot CLI, Codex) 
inside Docker containers and grades their work.

## Commands

```
uv sync
docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/
docker build -t eval-harness-rust:latest -f src/docker/rust/Dockerfile src/docker/
uv run main.py
```

    Rebuild the image manually after Dockerfile changes — there is no auto-rebuild currently.
    The base image must be built before eval-harness-rust (the rust image is FROM it). Evals
    that need rust declare `image = "eval-harness-rust:latest"` on the eval class.

## Architecture

Eval classes (in the package set by `EVALS_PACKAGE`, default `example_evals/*/*.py`) implement
`arrange()` / `act()` / `score()`; all three phases run inside a docker container —
`src/evals_engine.py:_method_to_script` extracts each method via `inspect.getsource()` and ships it
as `python -c "<body>"`. The eval source is never mounted, so the agent can't read scoring logic.
The eval contract is the `EvaluationFile` Protocol in `src/evaluation_file_protocol.py`; it is
enforced at load by `_load_eval_class`.

`src/docker_runner.py:DockerRunner` handles container lifecycle and per-agent credential mounting. 
New agents are added by implementing `_setup_<agent>` (returning an `AgentProvisioning` with either
`environment` vars or staged `volumes`) and adding a case to `_provision_agent`.

The harness passes `AGENT_TYPE` and `AGENT_MODEL` to the container via env vars; `act()` reads them 
and builds an `AgentShell` from `agent_shell` (the unified CLI-agent wrapper installed in the image).

## Evaluations
Each of the example evaluations map to an evaluation patterns that are located in `docs/eval_patterns`,
documentation also exists for patterns in the `skills/eval_creation/patterns`, be sure if you ever add 
or update a pattern to include documentation in both places.

## Logs
Each evaluation run has its own output folder (specified in `settings.py` with the variable `OUTPUT_DIR`)
There is a `session.log` as well as a per agent log file.

## Status

Working: Claude Code, OpenCode, Copilot, Codex
Pi not yet implemented.

## Repo Specific Instructions
As a general rule, do not implement code automatically - the maintainer of this repository is a dinosaur
and uses you for Q&A primarily and search. Only implement changes when explicitly instructed to do so.


