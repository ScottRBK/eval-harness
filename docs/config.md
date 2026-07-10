# Configuration

This section details all the various configuration options for the Evaluation  Harness and is split into two sections:
- Application Configuration
- Evaluation Configuration 

## Application Configuration
The following settings are defaulted in [settings.py](../src/config/settings.py) however 
can be overwritten with environment variables or .env file, all environment variables must be 
prefixed with `EVAL_HARNESS_`

|Variable|Type|Description|Example|
|--------|----|-----------|-------|
|`CLAUDE_CODE_OAUTH_TOKEN`|string|OAuth token to use with the claude code, obtained by typing `claude setup-token`||
|`OPENCODE_CREDENTIALS_LOC`|string|Path to the OpenCode `auth.json`; it is copied and mounted into the container for OpenCode agents|`~/.local/share/opencode/auth.json`|
|`CODEX_CREDENTIALS_LOC`|string|Path to the Codex `auth.json` (from `codex login`); a throwaway copy is mounted into the container so Codex can refresh the token without touching the host file|`~/.codex/auth.json`|
|`PI_CREDENTIALS_LOC`|string|Path to Pi's `auth.json`; it is copied and mounted into the container for Pi agents|`~/.pi/agent/auth.json`|
|`COPILOT_GITHUB_TOKEN`|string|GitHub token for the Copilot CLI agent, passed to the container as an environment variable. See [authorisation](authorisation.md) for the required permissions||
|`GITHUB_TOKEN`|string|Harness-level GitHub token for cloning private repos inside the container. Injected as `GH_TOKEN`; unset means public-repo clones only. See [authorisation](authorisation.md#private-repositories-harness-level-github-token)||
|`OUTPUT_DIR`|string|Parent directory for run output; each run creates a `<timestamp>_<session_id>` subfolder here|`output`|
|`RESULTS_FILENAME`|string|Name of the JSON results file written inside each run's folder|`results.json`|
|`CSV_RESULTS_FILENAME`|string|Name of the CSV results file written inside each run's folder|`results.csv`|
|`LOG_LEVEL`|string|Level for the root logger (the harness's own logging)|`DEBUG`|
|`DOCKER_LOG_LEVEL`|string|Level for the `docker` library logger, which is noisy at `INFO`|`WARNING`|
|`URLLIB3_LOG_LEVEL`|string|Level for the `urllib3` logger, which is noisy at `INFO`|`WARNING`|
|`EVALS_DIRS`|string|os.pathsep-separated list of directories searched, in order, for evals; each eval is `<dir>/<eval_dir>/eval.py`. Directories may live outside the repo and the first match wins (`:` on Linux/macOS, `;` on Windows)|`example_evals`|
|`MAX_AGENT_CONCURRENCY`|int|Maximum number of processing chains run in parallel. An ungrouped agent is its own chain; each processing group is a single chain|`4`|
|`ARRANGE_TIMEOUT_SECONDS`|int|Timeout for the arrange phase of each eval, in seconds|`3600`|
|`ACT_TIMEOUT_SECONDS`|int|Timeout for the act phase of each eval, in seconds|`3600`|
|`SCORE_TIMEOUT_SECONDS`|int|Timeout for the score phase of each eval, in seconds|`600`|

## Evaluation Configuration
All evaluation configuration comes from an evaluation file. See an example in [eval.json](../evals.json).
An evaluation file contains two lists - `evals` and `agents`

### Evals Configuration 
Each entry in `evals` selects one evaluation from the eval roots (`EVALS_DIRS`, default
`example_evals`) to run. Every agent in the file runs every eval. All fields are required and
unknown keys are rejected.

|Field|Type|Description|Example|
|-----|----|-----------|-------|
|`number`|int|Numeric identifier for the eval; shown in logs and written to the results|`2`|
|`eval_dir`|string|Directory name under one of the eval roots (`EVALS_DIRS`) that implements the eval. The eval class is the PascalCase form of this name (`inflection_bug_fix` → `InflectionBugFix`)|`inflection_bug_fix`|
|`description`|string|Human-readable summary, shown in logs and the TUI|`bug fixes in the inflection library`|
|`run_count`|int|Recorded against the eval in the results (`eval_run_count`). Used to determine the number of times that the evaluation is run against the agent|`1`|
|`tags`|list[string]|Free-form labels recorded in the results (`eval_tags`). Not used for filtering or selection|`["python", "bugs"]`|

```json
"evals": [
    {
        "number": 2,
        "eval_dir": "inflection_bug_fix",
        "description": "bug fixes in the python string transformation lib named inflection",
        "run_count": 1,
        "tags": ["python", "bugs"]
    }
]
```

### Agents Configuration 

Each entry in `agents` defines an agent and model to evaluate. Every agent runs every eval in
the file.

|Field|Type|Description|Example|
|-----|----|-----------|-------|
|`agent_type`|string|The CLI agent to run. One of `claude_code`, `opencode`, `copilot_cli`, `codex`, `pi` (`gemini_cli` is not yet implemented)|`opencode`|
|`agent_model`|string|Model identifier for the agent. Agent-specific: `haiku`/`sonnet`/`opus` for `claude_code`; a `provider/model` from the OpenCode config for `opencode`; or Pi's provider/model identifier, such as `openai-codex/gpt-5.4-mini`|`llama.cpp ai/qwen3.6-27b-8Q`|
|`effort`|string|Optional — reasoning-effort level passed to the agent at runtime via the `AGENT_EFFORT` env var (`claude_code` applies it as `--effort`; Pi maps it to `--thinking`; `opencode` currently accepts but ignores it). Also appended to the agent's log filename and recorded in the results (`agent_effort`), so agents sharing a type and model stay distinguishable|`high`|
|`processing_group`|string|Optional — agents sharing a group run serially, never concurrently. Ungrouped agents and separate groups run in parallel up to `MAX_AGENT_CONCURRENCY`. Use it to pin agents that share a backend such as a single inference server|`bosman-server`|

```json
"agents": [
    {
        "agent_type": "claude_code",
        "agent_model": "haiku",
        "effort": "low"
    },
    {
        "agent_type": "opencode",
        "agent_model": "llama.cpp bosman/qwen3.6-35b",
        "processing_group": "bosman-server"
    }
]
```

OpenCode providers and models are defined in `src/docker/configs/opencode/opencode.json`.
Pi has no native MCP support, so do not include it in an evaluation that uses MCP, such as
`encode_repo_forgetful`.

### Specifying Evaluation File
You can specify an evaluation file when you run the application using:

```bash 
uv run main.py -ef <path to evaluation file>
```

### Specifying Results output
The results output file will by default be in JSON, however if you would prefer to output in CSV:

```bash
uv run main.py -rf csv
```





