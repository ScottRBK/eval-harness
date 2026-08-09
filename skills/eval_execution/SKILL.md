---
name: running-eval-harness-evaluations
description: >-
    Run evaluations with the eval-harness framework. Use when asked to run, execute, benchmark or
    compare CLI coding agents (Claude Code, OpenCode, Copilot, Codex, Pi, Cursor, Grok) on
    existing evals.
---

# Overview
This guide covers how to run existing evaluations with the
[eval-harness](https://github.com/ScottRBK/eval-harness): pre-flight checks, composing the
evaluation file that pairs evals with agents, and launching the run. To build a new eval first,
follow the [eval creation skill](../eval_creation/SKILL.md); to monitor and diagnose a run,
follow the [eval interpretation skill](../eval_interpretation/SKILL.md).

## Pre-flight checks
1. Dependencies are synced: `uv sync`.
2. The base Docker image is built and current - the build command is in
   [AGENTS.md](../../AGENTS.md#commands). Manually managed images declared with `image` must also
   exist. Evals declaring `dockerfile` are built automatically once per session, but their
   Dockerfiles should derive from the current base image. Rebuild the base manually after its
   Dockerfile or agent-shell changes; a stale base is a common cause of zero-token results.
3. Credentials exist for **every** `agent_type` in the evaluation file - see the
   [authorisation guide](../../docs/authorisation.md). Evals that clone private repos also need
   the harness-level `GITHUB_TOKEN`.

## Compose the evaluation file
An evaluation file lists `evals` and `agents`; every agent runs every eval (a full cross
product). All fields are documented, with examples, in
[Configuration](../../docs/config.md#evaluation-configuration). Points that matter when
composing a run:

- Before creating a personal configuration, ask whether it should be an ignored local file or
  a version-controlled configuration in a separate directory. Local files under `eval_configs/`
  should use the `.local.json` suffix. A separate directory can be committed and selected through
  `EVAL_HARNESS_EVAL_CONFIG_DIR`.
- Do not modify the tracked example configuration files.
- `run_count` re-runs an eval in a fresh container each time; the recorded `score` is the
  **mean** across runs, while tokens and time are totals. Raise it to reduce variance when
  comparing agents.
- `effort` is optional but is appended to log filenames and recorded in the results, so use it
  to keep two entries with the same `agent_type` and `agent_model` distinguishable.
- `processing_group` serialises agents that share a backend (e.g. one local inference server);
  ungrouped agents run in parallel up to `EVAL_HARNESS_MAX_AGENT_CONCURRENCY`.
- OpenCode models must exist as `provider/model` in
  `src/docker/configs/opencode/opencode.json`.
- Pi has no native MCP support, so exclude it from MCP-backed evaluations such as
  `encode_repo_forgetful`. Cursor MCP works via AgentShell; Cursor still cannot enforce
  per-call `disallowed_tools`.

## Launch
Start the interactive TUI to choose a configuration from `EVAL_CONFIG_DIR`:

```bash
uv run main.py
```

For a version-controlled configuration directory, set the directory before starting the TUI:

```bash
EVAL_HARNESS_EVAL_CONFIG_DIR=path/to/team-eval-configs uv run main.py
```

Run a specific configuration headlessly with `--run_eval` and `--eval_file`:

```bash
uv run main.py --run_eval --eval_file eval_configs/simple_evals.example.json
uv run main.py \
  --run_eval \
  --eval_file eval_configs/my-evals.local.json \
  --results_format csv
```

The TUI currently writes JSON results. The `--results_format` option applies to headless runs.

Phase timeouts default to 3600s (arrange), 3600s (act) and 600s (score) and are overridable via
environment variables - see [Configuration](../../docs/config.md#application-configuration).

## Monitor the run
Follow the [eval interpretation skill](../eval_interpretation/SKILL.md) to watch the run, read
the results and diagnose failures. A failing agent does not stop the others; the process exits
with code 1 and one `FAILED:` line per failed agent.
