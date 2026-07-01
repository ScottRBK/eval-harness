---
name: eval-harness evaluation creation
description: Generate evaluations for the eval-harness solution
---

# Overview 
This guide covers how to produce an evaluation for a particular scenario or task that they want to 
evaluate large language models operating inside agentic coding harnesses for. It does so using the 
[eval-harness](https://github.com/ScottRBK/eval-harness), an agentic cli evaluation tool. 

## Match task to appropriate pattern
The eval harness has established patterns for evaluations, look to see if the task or scenario that 
the user is looking is a good fit for one of the following patterns and then read the appropriate guide
for building an evaluation for that pattern:

|Evaluation Pattern|Description|Example Evaluation|
|------------------|-----------|------------------|
|[Search with Questions and Answers](docs/eval_patterns/search_with_qa.md)|Have an agent perform a search of a knowedge base and then answer multiple choice questions about it in a JSON file, this eval also demonstrates how you can add an mcp server to the agentic harness as part of the evaluation|encode_repo_forgetful|
|[Bug Fix with Automated Tests](docs/eval_patterns/bug_fix.md)|Ask the agent to fix bugs in a repo that is causing automated tests to fail, this eval also demonstrates how to restore the original tests to ensure agent hasn't modified them to pass|inflection_bug_fix|
|[Schema Field Mapping](docs/eval_patterns/schema_field_mapping.md)|Instructs the agent to create a field mapping between two data models and output the values to a CSV file for scoring, an alternative to the JSON question and answers|saleor_spree_mapping|
|[New Feature with Automated Tests](docs/eval_patterns/new_feature.md)|Ask an agent to implement a new feature with prediefined API contract and run hidden automated tests after the agent has completed their work, it also demonstrates how you can make use of extrending the base docker image, in this example we add rustup to allow for the agent to use cargo to build and test in Rust|chess_engine|

## Additional information
The eval-harness uses the [agent-shell](https://github.com/ScottRBK/agent-shell) package to prompt
agents to perform tasks, the pattern examples will specify what features are utilised but it is also
useful to be aware of its capabilities while building evaluations.





