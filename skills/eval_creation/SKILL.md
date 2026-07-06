---
name: creating-eval-harness-evaluations
description: >-
    Create a new evaluation for the eval-harness framework. Use when asked to build, generate or
    scaffold an eval that tests a CLI coding agent (Claude Code, OpenCode, Copilot, Codex).
---

# Overview 
This guide covers how to produce an evaluation that tests large language models operating inside
agentic coding harnesses on a particular scenario or task. It does so using the
[eval-harness](https://github.com/ScottRBK/eval-harness), an agentic cli evaluation tool.


## Understand the architecture
Read the README's [harness architecture](../../README.md#harness-architecture) section first.

## Match task to appropriate pattern
The eval harness has established patterns for evaluations. Look to see if the task or scenario the
user is looking to evaluate is a good fit for one of the following patterns, then read the
appropriate guide for building an evaluation for that pattern:

|Evaluation Pattern|Description|Example Evaluation|
|------------------|-----------|------------------|
|[Search with Questions and Answers](../../docs/eval_patterns/search_with_qa.md)|Have an agent perform a search of a knowledge base and then answer multiple choice questions about it in a JSON file, this eval also demonstrates how you can add an mcp server to the agentic harness as part of the evaluation|encode_repo_forgetful|
|[Bug Fix with Automated Tests](../../docs/eval_patterns/bug_fix.md)|Ask the agent to fix bugs in a repo that are causing automated tests to fail, this eval also demonstrates how to restore the original tests to ensure the agent hasn't modified them to pass|inflection_bug_fix|
|[Schema Field Mapping](../../docs/eval_patterns/schema_field_mapping.md)|Instructs the agent to create a field mapping between two data models and output the values to a CSV file for scoring, an alternative to the JSON question and answers|saleor_spree_mapping|
|[New Feature with Automated Tests](../../docs/eval_patterns/new_feature.md)|Ask an agent to implement a new feature with a predefined API contract and run hidden automated tests after the agent has completed their work, it also demonstrates how you can make use of extending the base docker image, in this example we add rustup to allow for the agent to use cargo to build and test in Rust|chess_engine|
|[Test Authoring](../../docs/eval_patterns/test_authoring.md)|The inverse of the Bug Fix pattern: hand the agent the code with its test suite deleted and ask it to write one, then grade the suite by mutation testing - the harness applies small behavioural faults to the module and scores the fraction the agent's tests catch|inflection_test_writing|
|[Scorer Authoring](../../docs/eval_patterns/eval_generator.md)|Ask an agent to write a scoring routine that discriminates a correct implementation of a small task from incorrect ones, without ever seeing the held-out solutions|eval_generator|

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
1. Review the pattern explanations and then complete the necessary methods in the class.
1. Agree with the user if it is okay to generate a .json file (do not overwrite the `evals.json`)
for the evals configuration against a single agent configuration that they prefer to use for
cheap/free inference that they may have access to.
1. Once the eval file has been generated, run it following the
[eval execution skill](../eval_execution/), which covers the pre-flight checks and launch command.
1. Monitor the evaluation run using the [eval interpretation skill](../eval_interpretation/) and fix
any issues that might occur.

## Additional information

### general guidelines
1. The container persists between phases, so anything written in `arrange` can be seen by the agent 
in the `act` phase. If you must introduce code for the evaluation that the agent should not see then
you should do so during the `score` phase.
1. In any of the prompts or phases where there is interaction with the agent being tested, **NEVER**
give an indication that they are being evaluated. 
1. Evaluations should remain deterministic with the exception of the call out to the large language 
mode by the agent harness in agent shell.
1. A good eval is one that scores a correct solution high and an incorrect solution low - do not over 
complicate.
1. Keep the work the harness is doing simple, while making the task the agent is asked to perform and
be measured against the complex bit. Simple evaluations to hard tasks make great evaluations.


### agent-shell
The eval-harness uses the [agent-shell](https://github.com/ScottRBK/agent-shell) package to prompt
agents to perform tasks, the pattern examples will specify what features are utilised but it is also
useful to be aware of its capabilities while building evaluations.

