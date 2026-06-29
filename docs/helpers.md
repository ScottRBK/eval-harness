# Helpers

This section details some of the helpers that exist inside the eval-harness to help establish patterns
for building evaluations. An example of this might be reading a file that needs to be used as a prompt
for an AI agent for an evaluation and stored as an embedded value for the evaluation script. 

## [File Helpers](../src/helpers/file_helper.py)

|helper method|parameters|output|notes|
|-------------|----------|------|-----|
|`read_eval_fixture`|eval_file: string - str name of the evaluation script file<br>relative_path  - fixture relative path|string -content of the file passed into a string|loads a file inside the `fixtures` directory of an eval and loads it into a string that can then be used to populate embedded values|
|`read_mapping`|eval_file: string - name of the evaluation script file<br>mapping_file: string - fixture relative path to the CSV mapping<br>columns_to_remove: list[str] \| None - column header names whose values should be blanked|string - the CSV content, with the named columns blanked when supplied|wraps `read_eval_fixture` for evals that hold a canonical CSV data mapping. With no `columns_to_remove` the raw file is returned; otherwise the header is kept but the listed columns are emptied so a masked version can be embedded into the agent's prompt while the full file is used for scoring. Raises if the CSV has no header or a named column is missing. See `example_evals/saleor_spree_mapping/eval.py`, where the masked mapping (`spree_field`, `transform` blanked) is the `arrange` value and the unmasked mapping is the `score` value|
|`read_questions`|eval_file: string - name of the evaluation script file<br>include_answers: bool - whether to keep the answer key|string - JSON of the questions fixture (`questions.json`), pretty-printed when answers are stripped|reads a `questions.json` fixture for multiple-choice evals and validates it (non-empty `questions` list, unique ids, every answer present in its choices). When `include_answers` is `False` the `note`, `answer` and `source` fields are removed so the answer key is never embedded into the act script; `True` returns the full file for scoring. See `example_evals/encode_repo_forgetful/eval.py`, which embeds `read_questions(__file__, False)` in `act` and `read_questions(__file__, True)` in `score`|

## [Naming Helper](../src/helpers/naming.py)

|helper method|parameters|output|notes|
|-------------|----------|------|-----|
|`safe_name`|s: string - an arbitrary identifier (e.g. an agent/model name or log label)|string - the input with every character outside Docker's container-name charset (`[a-zA-Z0-9_.-]`) collapsed to `_`|sanitises identifiers that routinely contain `/` and spaces (e.g. `llama.cpp ai/qwen3.6-27b-8Q`) which are illegal in a Docker container name and awkward in a filename. The allowlist approach means any future stray character is handled too. Used in `src/docker_runner.py` to build the container name (`eval_harness_<type>_<model>...`) and in `src/logging_config.py` to build the per-agent log filename|
