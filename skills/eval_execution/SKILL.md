---
name: running-eval-harness-evaluations
description: >-
    Run evaluations with the eval-harness framework. Use when asked to run, execute, benchmark or
    compare CLI coding agents (Claude Code, OpenCode, Copilot, Codex) on existing evals.
---

# Overview
This guide covers how to run existing evaluations with the
[eval-harness](https://github.com/ScottRBK/eval-harness): pre-flight checks, composing the
evaluation file that pairs evals with agents, and launching the run. To build a new eval first,
follow the [eval creation skill](../eval_creation/SKILL.md); to monitor and diagnose a run,
follow the [eval interpretation skill](../eval_interpretation/SKILL.md).

## Pre-flight checks
1. Dependencies are synced: `uv sync`.
2. The docker images are built and current - the build commands are in
   [AGENTS.md](../../AGENTS.md#commands). The base image must exist before the rust image is
   built; the rust image is only needed by evals that declare
   `image = "eval-harness-rust:latest"`. Rebuild manually after any Dockerfile or agent-shell
   change - a stale image is the usual cause of zero-token results.
3. Credentials exist for **every** `agent_type` in the evaluation file - see the
   [authorisation guide](../../docs/authorisation.md). Evals that clone private repos also need
   the harness-level `GITHUB_TOKEN`.

## Compose the evaluation file
An evaluation file lists `evals` and `agents`; every agent runs every eval (a full cross
product). All fields are documented, with examples, in
[Configuration](../../docs/config.md#evaluation-configuration). Points that matter when
composing a run:

- Do not overwrite `evals.json` (the default file) - write a new file and pass it with `-ef`.
- `run_count` re-runs an eval in a fresh container each time; the recorded `score` is the
  **mean** across runs, while tokens and time are totals. Raise it to reduce variance when
  comparing agents.
- `effort` is optional but is appended to log filenames and recorded in the results, so use it
  to keep two entries with the same `agent_type` and `agent_model` distinguishable.
- `processing_group` serialises agents that share a backend (e.g. one local inference server);
  ungrouped agents run in parallel up to `EVAL_HARNESS_MAX_AGENT_CONCURRENCY`.
- OpenCode models must exist as `provider/model` in
  `src/docker/configs/opencode/opencode.json`.

## Launch
```bash
uv run main.py                      # runs the default evals.json
uv run main.py -ef <file>.json      # runs a specific evaluation file
uv run main.py -rf csv              # writes results.csv instead of results.json
```

Phase timeouts default to 3600s (arrange), 3600s (act) and 600s (score) and are overridable via
environment variables - see [Configuration](../../docs/config.md#application-configuration).

## Monitor the run
Follow the [eval interpretation skill](../eval_interpretation/SKILL.md) to watch the run, read
the results and diagnose failures. A failing agent does not stop the others; the process exits
with code 1 and one `FAILED:` line per failed agent.
