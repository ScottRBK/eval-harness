# AGENTS.md

## What this is

A Python framework that runs CLI coding agents (Claude Code, OpenCode, Gemini CLI, Copilot CLI, Codex) 
inside Docker containers and grades their work.

## Commands

```
uv sync
docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/
uv run main.py
```

    Rebuild the image manually after Dockerfile changes — there is no auto-rebuild currently

## Architecture

Eval classes (`src/evals/*/*.py`) implement `arrange()` / `act()` / `score()`, all three phases are 
run inside a docker container** — `main.py:method_to_script` extracts it via `inspect.getsource()` 
and ships it as `python -c "<body>"`. The eval source is never mounted, so the agent can't read 
scoring logic.

`src/docker_runner.py:DockerRunner` handles container lifecycle and per-agent credential mounting. 
New agents are added by implementing `_setup_<agent>_volumes` and adding a case to `_set_up_agent_volumes`.

The harness passes `AGENT_TYPE` and `AGENT_MODEL` to the container via env vars; `act()` reads them 
and builds an `AgentShell` from `agent_shell` (the unified CLI-agent wrapper installed in the image).

## Status

Working: Claude Code, OpenCode. 
Codex / Copilot CLI / Gemini CLI not yet implemented.
