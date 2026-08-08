This evaluation harness is designed to test not just Large Language Models but also the Agentic Coding
harnesses that are wrapped around these models. 

I feel it is important to frame all evaluations from the perpsective of not just the Large Language Model
but also the coding harness that was used during the evaluation.

The following agent harnesses are currently supported: 

- [x] Claude Code
- [x] Opencode
- [x] Copilot
- [x] Codex
- [x] Pi

A lot of this is possible thanks to the agentic harness abstraction repository 
[agent-shell](https://github.com/ScottRBK/agent-shell), check it out if you have use cases where you 
want to seemlessly switch between agentic harness for a particular worklow that you invoke via code 
or scripts. It was originally inspired for auto-research type loops but I've come to find many an 
application for it.

## Example Eval Patterns
This harness ships with some example evals, as I come up with different types of 
evaluations for my own workflows, then this example collection will increase.

These evals are reasonably straightforward for modern harnesses and models because they use public
repositories or well-known solved challenges that may appear in training data. Their primary purpose
is to demonstrate the available evaluation patterns.

The human-readable pattern guides live with the eval-creation skill so the same documents are
included when that skill is installed:

- [Search with Questions and Answers][search-pattern] — search a knowledge base and answer
  multiple-choice questions in JSON; demonstrates MCP (`encode_repo_forgetful`).
- [Bug Fix with Automated Tests][bug-fix-pattern] — fix failing repository tests while the scorer
  restores the authoritative suite (`inflection_bug_fix`).
- [Schema Field Mapping][mapping-pattern] — produce a scored CSV mapping between two data models
  (`saleor_spree_mapping`).
- [New Feature with Automated Tests][new-feature-pattern] — implement a fixed API against hidden
  score-time tests; demonstrates a Rust-enabled image (`chess_engine`).
- [Test Authoring][test-authoring-pattern] — write tests graded through mutation testing
  (`inflection_test_writing`).
- [Scorer Authoring][scorer-authoring-pattern] — write a scorer that distinguishes held-out correct
  and incorrect implementations (`eval_generator`).
- [Terminal Task][terminal-task-pattern] — leave a container in a required final state, graded
  through outcome-only checks (`repair_nginx_service`).

[search-pattern]: skills/eval_creation/references/eval_patterns/search_with_qa.md
[bug-fix-pattern]: skills/eval_creation/references/eval_patterns/bug_fix.md
[mapping-pattern]: skills/eval_creation/references/eval_patterns/schema_field_mapping.md
[new-feature-pattern]: skills/eval_creation/references/eval_patterns/new_feature.md
[test-authoring-pattern]: skills/eval_creation/references/eval_patterns/test_authoring.md
[scorer-authoring-pattern]: skills/eval_creation/references/eval_patterns/eval_generator.md
[terminal-task-pattern]: skills/eval_creation/references/eval_patterns/terminal_task.md

# Getting Started

install uv if you do not have it already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

1. Fork the repo 
1. run `uv sync` 
1. Replace the example eval folder with your own evals (or leave it in place if you want to see an example)
1. Choose where your evaluation configuration will live. For an ignored local config, copy
   `eval_configs/simple_evals.example.json` to `eval_configs/my-evals.local.json`. For a
   version-controlled team config, use a separate directory and set `EVAL_HARNESS_EVAL_CONFIG_DIR`.
1. Build the container(s)
```bash
docker build -t eval-harness:latest -f src/docker/Dockerfile src/docker/
docker build -t eval-harness-rust:latest -f src/docker/rust/Dockerfile src/docker/
```
1. Start the interactive TUI
```bash
uv run main.py
```

The TUI lists JSON files in `EVAL_CONFIG_DIR`, which defaults to `eval_configs`.
Local `*.local.json` files in the default directory are ignored by Git. For a shared,
version-controlled directory, set `EVAL_HARNESS_EVAL_CONFIG_DIR` before starting the TUI.
For a headless run, pass a config file explicitly:

```bash
uv run main.py --run_eval --eval_file eval_configs/simple_evals.example.json
```
> [!TIP]
> If you would like to use an AI Agent to help you build evals it is recommended you install the 
> [skills](skills/) that accompany this repository.

## [Configuration](docs/config.md)

# Harness Architecture

![Eval Harness Architecture](docs/images/eval_harness_architecture.png)

The harness is structured in a way that there is an [evaluation protocol](src/evaluation_file_protocol.py), 
any evaluation must implement the same methods within the protocol.

The harness ingests an evaluation configuration file that determines which evaluations
and agent harness/model combinations are in scope. The interactive TUI discovers JSON
configuration files in `EVAL_CONFIG_DIR` (default `eval_configs`). The repository includes
`eval_configs/evals.example.json` with every example evaluation and
`eval_configs/simple_evals.example.json` with a smaller two-evaluation run. Headless
runs require the configuration file to be supplied with `--eval_file`.

When I build my own automated tests for testing my actual code, I have used the popular _Arrange_, 
_Act_ and _Assert_ pattern, to this end I have adopted these as methods that any evaluation class must
provide, with one exception, given that `assert` is a keyword in python, I changed that to `score`.

## The Anatomy of an Eval
Each evaluation is it's own folder containing the python logic and any test fixtures that are required
as part of the evaluation itself. Eval folders live under one of the roots listed in the
`EVALS_DIRS` setting (an os.pathsep-separated list searched in order, default `example_evals`),
so your own evals can live in a completely separate directory or repo — point
`EVAL_HARNESS_EVALS_DIRS` at it and the first root containing a requested eval wins.

Each eval folder must contain an `eval.py` implementing the protocol specified in
[/src/evaluation_file_protocol.py], with a class name that matches the eval directory name
converted from snake case (`encode_repo_forgetful`) to pascal case (`EncodeRepoForgetful`).
The harness loads `eval.py` directly by file path, so no `__init__.py` is required.

For each phase (`assert`, `act` and `score`) the harness will extract the python script from the evaluation
classes methods using the `method_to_script` function 

***Hey Listen*** It is important to note that during execution the logic for each stage is extracted into
a string and injected into a `python -c` command, which means any dependencies for each phase must be 
lazy loaded into the phases method itself. 

```python
    async def arrange(self) -> None:
        import os 
        import subprocess
        import time
        from agent_shell.shell import AgentShell 
        from agent_shell.models.agent import AgentType, MCPServerSpec, MCPServerType
```

### Eval-specific Docker images

An eval can use an existing prebuilt image with the `image` class attribute:

```python
class ChessEngine:
    image = "eval-harness-rust:latest"
```

Alternatively, an eval can carry its own Dockerfile and have the harness build it once per session:

```text
my_eval/
├── eval.py
└── fixtures/
    ├── hidden_tests.py
    └── image/
        ├── Dockerfile
        └── visible-starting-files/
```

```python
class MyEval:
    dockerfile = "fixtures/image/Dockerfile"
```

The Dockerfile path is relative to the eval directory. Its parent directory is the complete Docker
build context, so everything in that directory must be safe for the agent to see. Keep hidden tests,
answers and oracles outside it. Fixture Dockerfiles should derive from `eval-harness:latest` so the
Python runtime, agent CLIs and harness execution tools remain available.

`image` and `dockerfile` are mutually exclusive. If neither is declared, the harness uses
`EVAL_HARNESS_BASE_IMAGE` (`eval-harness:latest` by default). Built fixture images use Docker's layer
cache but are rebuilt once per harness session, so changes to their context or base image are picked
up without a manual build command.

### Embedded Values 
As well as scrapping the method it will also scrape any embedded values that need to injected into the 
script at run time, such as for example a prompt file held within the `fixtures` directory of the 
evaluation. These can then be referenced as variables inside of your actual methods. 

To use embedded values you need to instantiate these at the top of the evaluation class file and then
inside of the class themselves set their values inside the appropriate phase embedde values dictionary:

```python 
ENCODING_PROMPT = ""
REPO_URL = ""
REPO_REF = ""
REPO_DIR = ""
QUESTIONS= ""
ANSWERS = ""

class EncodeRepoForgetful:

    arrange_embedded_values = {
        "REPO_URL": "https://github.com/fastapi/typer",
        "REPO_REF": "0.26.7",
        "REPO_DIR": "/workspace/typer",
        "ENCODING_PROMPT": read_eval_fixture(__file__, "encoding_prompt.md"),
    }
    act_embedded_values = {
        "QUESTIONS":  read_questions(__file__, False)
    }
    score_embedded_values = {
        "ANSWERS": read_questions(__file__, True)
    }
...

```

These can then be referenced inside of the methods as normal variables:
```python
    async def act(self) -> None:
        import os
        import json 
        from agent_shell.shell import AgentShell
        from agent_shell.models.agent import AgentType

        scaffold = json.loads(QUESTIONS)
```

### Arrange 
The purpose of the arrange phase is to setup the evaluation. For example if you are looking to bring in 
any repositories to the container or preparing any agent harness specifics such as setting up and
configuring an MCP server.

### Act 
The act phase is where you will ask the agnet to perform the action that you will want to measure in the
score phase. Such as fixing a bug or implementing a feature. 

### Score 
In this phase you will validate the outcome of the act phase, such as executing automated tests or scoring
answers to a series of questions. 

### Output and Logging
Each session gets it's own directory created under the location of the `EVAL_HARNESS_OUTPUT_DIR`, which
defaults to `output` in the root of the solution. 

Each agent gets their own .log file, which amongst other things, captures all print captured in the eval 
scripts. 

As well as this a .log file for each agent there is also a results file that is created based on your
[configuration](docs/config.md). 

The results file is written as either `results.json` (the default) or `results.csv`. See
[Results File Schema](docs/results.md) for the full field-by-field breakdown.



# Road Map
- finish roadmap
- CI/CD
- extend tui functionality (view results in tui)
- polish console output
- add direct api key authorisation for harnes


# Technical Notes

### Building behind a TLS-intercepting proxy

If your machine routes traffic through a TLS-intercepting proxy (Netskope, Zscaler, etc.), container builds 
and agent API calls will fail certificate verification. Drop your proxy's CA certificate chain 
(PEM format, `.crt` extension) into `src/docker/certs/` and rebuild — certs in that directory are gitignored and get baked into the image's trust store. To extract the chain your proxy presents:

```bash
docker run --rm node:24 sh -c 'echo | openssl s_client -showcerts -connect astral.sh:443 2>/dev/null' \
  | awk '/BEGIN CERTIFICATE/{n++} n>=2' > src/docker/certs/proxy-ca.crt
```
