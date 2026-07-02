---
name: interpreting-eval-harness-evaluations
description: >-
    Monitor and interpret evaluation runs of the eval-harness framework. Use when asked to watch,
    interpret, debug or diagnose an eval run, its logs, its scores or its results.
---

# Overview
This guide covers how to monitor an [eval-harness](https://github.com/ScottRBK/eval-harness) run
while it is in progress, interpret the logs and results once it finishes, and diagnose the
failures that can occur along the way.

## Locate the run
Every run writes to its own directory: `<OUTPUT_DIR>/<YYYYMMDD_HHMMSS>_<session_id>/`, where
`OUTPUT_DIR` is set by `EVAL_HARNESS_OUTPUT_DIR` (default `output`). Inside it:

- `session.log` - every record from every agent thread, interleaved.
- `<agent_type>_<model>[_<effort>].log` - one per agent, containing only that agent's records.
  Characters that cannot appear in a filename (e.g. `/` in model names) are replaced with `_`.
- `results.json` (or `results.csv`) - written when the session finishes; see the
  [Results File Schema](../../docs/results.md) for the field-by-field breakdown.

## Read the logs
Log lines are formatted `<timestamp> - <level> - <file:line> - <message>`. The markers to look
for:

- `--- arrange phase ---` / `--- act phase ---` / `--- score phase ---` - phase boundaries.
- `[arrange] <line>` (likewise `[act]` and `[score]`) - stdout/stderr streamed from inside the
  container, including every `print()` in the eval's phase methods.
- `Run 1/3` - logged when an eval has `run_count` > 1; each run is a fresh container.
- `EVAL_TOTAL_TOKENS=<int>` - emitted once per agent-shell call and summed into the token totals.
- `EVAL_SCORE=<float>` - printed by the eval's `score` method; the harness takes the **last**
  occurrence in the score phase output. If no line matches, the run silently scores 0.0.
- `phase <label> completed` - the phase finished cleanly.

In the results file, an eval's `score` is the **mean** across its runs, while `total_tokens` and
`time_taken_seconds` are **totals** across them.

## Monitor a live run
`tail -f` the session log, or a single agent's log for less noise. A failing agent does not stop
the others: it is logged as `Agent <type>-<model> failed` with a traceback, marked FAILED, and
the session carries on. At the end, `main.py` prints one `FAILED: ...` line per failed agent and
exits with code 1.

## Diagnose failures

|Symptom|Likely cause|Where to look|
|-------|------------|-------------|
|`RuntimeError: ... not configured` or `... auth file not found`, before any phase marker|Missing or expired credentials for that agent|[Authorisation](../../docs/authorisation.md)|
|`<phase> failed (exit <N>)` followed by a `--- container output ---` block|The phase script raised; the block holds the full traceback|The traceback; for `arrange`, also external dependencies (repo clones, MCP servers)|
|`<phase> timed out after <N>s` (exit 124 or 137)|The phase exceeded its timeout|`EVAL_HARNESS_<ARRANGE\|ACT\|SCORE>_TIMEOUT_SECONDS`, defaults 3600/3600/600|
|`NameError` or `ImportError` in a phase traceback|The eval violates an authoring constraint (module-level state, imports outside the method body)|[Constraints](../eval_creation/SKILL.md#constraints) in the eval creation skill|
|`TypeError: <Class> must be a class implementing arrange/act/score`|The eval class does not satisfy the `EvaluationFile` protocol|Same constraints section|
|Score is 0.0 with no error|The `score` method never printed `EVAL_SCORE=` (or the agent genuinely scored zero)|The `[score]` output for that run|
|`Malformed score line`|`EVAL_SCORE=` was printed with a non-float value|The eval's `score` method|
|`total_tokens` is 0 but the agent clearly did work|Stale docker image (agent-shell version mismatch)|Rebuild the images - see the commands in [AGENTS.md](../../AGENTS.md#commands)|
|`ValueError: I/O operation on closed file` after the end-of-run summary|Benign docker-py teardown noise|Ignore it|

## Where the fix belongs
Classify the failure before changing anything:

- **The eval itself** (authoring constraint violations, scoring bugs) - fix the eval class,
  following the [eval creation skill](../eval_creation/SKILL.md).
- **Harness configuration** (timeouts, output locations) - `.env` / `EVAL_HARNESS_` environment
  variables, documented in [Configuration](../../docs/config.md).
- **Credentials** - re-authenticate on the host per the
  [authorisation guide](../../docs/authorisation.md).
- **The docker image** - rebuild manually after any Dockerfile or agent-shell change; there is no
  auto-rebuild.
