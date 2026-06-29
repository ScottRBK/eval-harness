# Results File Schema

A results file is written in one of two formats, controlled by your [configuration](config.md):
`results.json` (the default) or `results.csv`.

The JSON file is an array with one object per agent (each is an `AgentEvalExecution`). Every object has
the following fields:

|Field|Type|Description|Example|
|-----|----|-----------|-------|
|[`agent_config`](config.md#agents-configuration)|object|the agent configuration this run was executed against (see nested fields below)|—|
|`total_score`|float|the accumulated score that the agent achieved for all of the evals during the session|3.2|
|`total_tokens`|int|the number of output tokens generated (including any thinking) for all of the evals during the session|53021|
|`total_time_taken_seconds`|float|the accumulated wall-clock time across all of the evals for this agent|412.5|
|`status`|string|overall status of the agent's run — one of `pending`, `processing`, `completed`, `failed`|completed|
|`evals_executions`|array&lt;object&gt;|one entry per individual evaluation execution (see nested fields below)|—|

The nested `agent_config` object:

|Field|Type|Description|Example|
|-----|----|-----------|-------|
|`agent_type`|string|the CLI agent that was run|codex|
|`agent_model`|string|the model the agent used|gpt-5.4-mini|
|`effort`|string \| null|reasoning-effort level, `null` when not set|high|
|`processing_group`|string \| null|optional group used to serialise agents that can't run concurrently, `null` when not set|null|

Each entry in `evals_executions` (an `EvalExecution`):

|Field|Type|Description|Example|
|-----|----|-----------|-------|
|`id`|string (uuid)|unique identifier for this single eval execution|84fbfcfa-b122-4a7c-acac-3f6c6abfa4fa|
|`eval`|object|the eval definition that was run (see nested fields below)|—|
|`agent_config`|object|the agent configuration for this execution (same shape as above)|—|
|`total_tokens`|int \| null|output tokens generated for this eval, `null` until the eval completes|12000|
|`score`|float \| null|the score this eval achieved, `null` until the eval completes|0.8|
|`time_taken_seconds`|float \| null|wall-clock time for this eval, `null` until the eval completes|95.2|
|`date_executed`|string (iso8601) \| null|when the eval finished, `null` until the eval completes|2026-06-29T16:17:49|

The nested `eval` object:

|Field|Type|Description|Example|
|-----|----|-----------|-------|
|`number`|int|numeric identifier for the eval|2|
|`eval_dir`|string|directory the eval lives in|inflection_bug_fix|
|`description`|string|free-form description of the eval|bug fixes in the python string transformation lib named inflection|
|`run_count`|int|number of times the eval was run against the agent|2|
|`tags`|list[string]|free-form labels recorded against the eval|["python", "bugs"]|

The CSV file holds the same data flattened to one row per eval execution, with the agent-level fields
(prefixed `agent_`) repeated on every row alongside the per-eval fields (prefixed `eval_`).
