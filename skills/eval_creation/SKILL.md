---
name: creating-eval-harness-evaluations
description: >-
    Create eval-harness evaluations. Use when the user wants a new evaluation for a CLI coding
    agent (Claude Code, OpenCode, Copilot, Codex, Pi, Cursor, Grok).
---

# Overview
This guide covers how to produce an evaluation that tests large language models operating inside
agentic coding harnesses on a particular scenario or task. It uses
[eval-harness](https://github.com/ScottRBK/eval-harness), an agentic CLI evaluation tool.


## Understand the architecture
Read the README's [harness architecture](../../README.md#harness-architecture) section first.

## Match task to appropriate pattern
The eval harness has established patterns for evaluations. Look to see if the task or scenario the
user is looking to evaluate is a good fit for one of the following patterns, then read the
appropriate guide for building an evaluation for that pattern:

- [Search with Questions and Answers](references/eval_patterns/search_with_qa.md) — search a
  knowledge base, then answer multiple-choice questions. Demonstrates MCP
  (`encode_repo_forgetful`).
- [Bug Fix with Automated Tests](references/eval_patterns/bug_fix.md) — fix a repository's failing
  tests while the scorer restores authoritative tests (`inflection_bug_fix`).
- [Schema Field Mapping](references/eval_patterns/schema_field_mapping.md) — produce a scored CSV
  mapping between two data models (`saleor_spree_mapping`).
- [New Feature with Automated Tests](references/eval_patterns/new_feature.md) — implement a fixed
  API against hidden score-time tests (`chess_engine`).
- [Test Authoring](references/eval_patterns/test_authoring.md) — write tests that are graded by
  mutation testing (`inflection_test_writing`).
- [Scorer Authoring](references/eval_patterns/eval_generator.md) — write a scorer that distinguishes
  held-out correct and incorrect implementations (`eval_generator`).
- [Terminal Task](references/eval_patterns/terminal_task.md) — leave a container in a required final
  state, graded by outcome-only checks (`repair_nginx_service`).

## Constraints
The harness imposes a few rules on every eval class; a run will fail if they are broken:

1. The class must satisfy the `EvaluationFile` protocol (`src/evaluation_file_protocol.py`) - this
is enforced when the eval is loaded and a `TypeError` is raised if it isn't met.
1. Each phase method (`arrange`, `act`, `score`) is extracted with `inspect.getsource()` and
shipped into the container as a standalone script, so imports must live inside the method bodies
and methods cannot reference module-level state, class attributes or each other.
1. Method bodies are wrapped in an async function inside the container, so declare them
`async def` and `await` freely.
1. Values a phase needs are supplied through the `arrange_embedded_values` / `act_embedded_values`
/ `score_embedded_values` class attribute dicts. Each entry is injected as a variable assignment
(via `repr()`) ahead of the method body, so keys must be valid Python identifiers and values must
be plain literals. Module-level placeholders (e.g. `REPO_URL = ""`) keep linters happy but are
never shipped to the container.
1. Pi has no native MCP support, so an eval that configures MCP (such as `encode_repo_forgetful`)
cannot be run with Pi. Cursor MCP add/remove/list is supported by AgentShell (writes
`~/.cursor/mcp.json`). Cursor still has no per-call `disallowed_tools` — tool policy lives in
`.cursor/cli.json`, so deny-list evals are not enforceable on Cursor.
1. An eval may declare either `image` for a manually managed prebuilt image or `dockerfile` for a
Dockerfile path relative to its eval directory. The Dockerfile's parent is the complete build
context; keep hidden tests, answers and oracles outside it. Do not declare both attributes.

## Generating the evaluation
1. Check whether the environment variable `EVAL_HARNESS_EVALS_DIRS` is set (if not, use the
default value in `src.config.settings.settings.EVALS_DIRS`). It is an os.pathsep-separated list
of directories searched in order; create new evals in the **first** directory listed.
1. Create a directory in there, in snake_case, with a suitable title for the eval
1. Create an `eval.py` file inside of the newly created evaluation directory (no `__init__.py`
is needed — the harness loads `eval.py` directly by file path)
1. Generate the class with PascalCasing of the directory you created for the evaluation.
1. Generate the three methods (arrange, act and score) and embedded values as outlined in the
[architecture description](../../README.md#harness-architecture) for the class.
1. If the eval needs additional system software, prefer an eval-owned
`fixtures/image/Dockerfile` derived from `eval-harness:latest`. Put only agent-visible build files
in that directory and set `dockerfile = "fixtures/image/Dockerfile"` on the eval class.
1. Review the pattern explanation and complete the necessary methods in the class.
1. Validate the scorer in the eval's actual image with at least one known-valid and one
known-invalid outcome, then complete any authoring gate in the selected pattern guide. This step is
complete when both controls produce their intended scores and score-only material is absent from
`arrange` and `act`.
1. Before generating an eval configuration, ask the user how they want to manage it:
   - create an ignored local file under `eval_configs/` with the `.local.json` suffix, or
   - create/use a separate configuration directory that they can commit and select with
     `EVAL_HARNESS_EVAL_CONFIG_DIR`.
   Do not modify the tracked example configuration files. If the user chooses a separate
   directory, confirm its path before writing the configuration there.
1. Once the eval file has been generated, run it following the
[eval execution skill](../eval_execution/), which covers the pre-flight checks and launch command.
1. Monitor the evaluation run using the [eval interpretation skill](../eval_interpretation/) and fix
any issues that might occur.

## Additional information

### General guidelines
1. The container persists between phases, so anything written in `arrange` can be seen by the agent
in `act`. Introduce agent-hidden material during `score`.
1. Present the agent with an ordinary task or development request, without mentioning evaluation,
scoring, hidden tests, or score-time restoration.
1. Keep the eval deterministic except for the language-model call made through AgentShell.
1. Score known-correct solutions high and known-incorrect solutions low. Keep the harness mechanism
simple and leave the complexity in the task being measured.
1. Audit every package dependency added or upgraded by an eval before installation, then record the
audit in the relevant pattern documentation.

### AgentShell
The eval-harness uses the [agent-shell](https://github.com/ScottRBK/agent-shell) package to prompt
agents to perform tasks, the pattern examples will specify what features are utilised but it is also
useful to be aware of its capabilities while building evaluations.
