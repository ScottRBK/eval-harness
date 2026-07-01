# Schema Field Mapping

This eval measures two things:
1. The ability of an agent to read two unfamiliar codebases and reason about how their data models
   line up.
1. The ability to express that reasoning as a precise, machine-checkable artifact - here a CSV field
   mapping - rather than as prose.

## Overview
This is the data-integration cousin of the [search-with-Q&A](./search_with_qa.md) eval. Where that
one grades free-form knowledge by having the agent answer multiple-choice questions in JSON, this
one grades a *structured deliverable* - a field mapping from one real e-commerce system's schema
onto another, emitted as a CSV. It is the right shape whenever the thing you want to measure is a
table of decisions with a defensible ground truth rather than a paragraph of text.

The agent is handed two pinned forks on the `eval-v1` ref -
[ScottRBK/saleor](https://github.com/ScottRBK/saleor) (the source system) and
[ScottRBK/spree](https://github.com/ScottRBK/spree) (the target) - and asked to map the fields of
the **Order** entity from one to the other. Saleor describes its Order as GraphQL SDL and Spree as
an OpenAPI JSON schema, so the agent has to read two different schema formats and decide, field by
field, what maps to what and how the value would have to be transformed to get there. The full
ground-truth mapping, the four `transform` values, and the judgement calls behind the trickier rows
are catalogued in [Saleor ↔ Spree Mapping](../evals.md#saleor--spree-mapping).

The deliverable is a single CSV with three columns:

```
saleor_field,spree_field,transform
```

The neat part of this pattern is that one fixture does double duty - it is both the scaffold we hand
the agent and the answer key we grade against - and we get both out of it with the
[`read_mapping`](../helpers.md) helper. Called with a list of columns to blank it returns the
**masked** scaffold (the `saleor_field` column populated, `spree_field` and `transform` emptied)
that seeds the agent's working file; called with no mask it returns the **full** mapping used for
scoring (see [embedded values](../../README.md#embedded-values)).

> [!TIP]
> `read_mapping` is *fail-closed*: if you ask it to blank a column that isn't in the CSV header it
> raises rather than silently returning the file untouched. That matters, because a silent no-op
> would embed the full answer key straight into the agent's prompt. It is the CSV twin of the
> `read_questions` helper the Q&A eval uses - the same "full-for-score, stripped-for-act" contract,
> a different serialisation for a different answer shape.

```python
arrange_embedded_values = {
    "REPO_SALEOR_URL": "https://github.com/ScottRBK/saleor",
    "REPO_SALEOR_REF": "eval-v1",
    "REPO_SALEOR_DIR": "/workspace/saleor",
    "REPO_SPREE_URL": "https://github.com/ScottRBK/spree",
    "REPO_SPREE_REF": "eval-v1",
    "REPO_SPREE_DIR": "/workspace/spree",
    "MASKED_MAPPING_DOC": read_mapping(__file__, "canonical_mapping.csv", ["spree_field", "transform"])
}

act_embedded_values = {
    "MAPPING_PROMPT": read_eval_fixture(__file__, "mapping_prompt.md")
}

score_embedded_values = {
    "CANONICAL_MAPPING_DOC": read_mapping(__file__, "canonical_mapping.csv"),
    "MAPPING_OUTPUT_PATH": "/workspace/mapping.csv",
}
```

## Evaluation Details

### arrange
The arrange phase clones both forks into the workspace and severs each remote - the same shallow,
pinned clone and `git remote remove origin` guard the other evals use, just done twice, once per
repo.

```python
subprocess.run(
    ["git", "-c", "advice.detachedHead=false", "clone", "--quiet",
     "--depth", "1", "--branch", REPO_SALEOR_REF, REPO_SALEOR_URL, REPO_SALEOR_DIR],
    check=True,
)
subprocess.run(["git", "-C", REPO_SALEOR_DIR, "remote", "remove", "origin"])
```

With both repos in place, the last thing arrange does is drop the masked scaffold into the
workspace. This is the file the agent edits: every `saleor_field` row is already filled in, and the
two columns we blanked with `read_mapping` are exactly the cells it has to complete.

```python
with open("/workspace/mapping.csv", "w") as f:
    f.write(MASKED_MAPPING_DOC)
```

### act
Act is a thin, single-prompt call. We point the shell at the workspace and hand it the
[mapping prompt](../../example_evals/saleor_spree_mapping/fixtures/mapping_prompt.md), which tells
the agent where each schema lives, what the three columns mean, the exact four `transform` values to
choose from, and - importantly - not to add, remove, or reorder rows, only to fill the two empty
cells. That last instruction is the other half of the template-fill design: the masking only holds
if the row set and column shape are preserved.

```python
shell = AgentShell(agent_type=AgentType(os.environ["AGENT_TYPE"]))
response = await shell.execute(
    cwd="/workspace/",
    prompt=MAPPING_PROMPT,
    model=os.environ["AGENT_MODEL"],
    effort=os.environ["AGENT_EFFORT"],
)
```

There are no tools to disable and no tests to hide here - the task is a reasoning exercise over two
schema files that sit right there in the workspace, so the agent has free rein.

### score
Scoring is a straight exact-match count. First we parse the full (unmasked) canonical mapping into a
lookup keyed by `saleor_field`, where each value is the `(spree_field, transform)` pair the agent is
expected to produce - lower-casing the transform so casing never costs a point.

```python
canonical = {}
for row in csv.DictReader(io.StringIO(CANONICAL_MAPPING_DOC)):
    canonical[row["saleor_field"].strip()] = (
        row["spree_field"].strip(),
        row["transform"].strip().lower(),
    )
```

If the agent produced no file at all we bail with a zero; otherwise we load its CSV into the same
`(spree_field, transform)` shape, keyed the same way.

```python
if not os.path.exists(MAPPING_OUTPUT_PATH):
    print("agent produced no mapping file")
    print("EVAL_SCORE=0.0")
    return

answers = {}
with open(MAPPING_OUTPUT_PATH, newline="") as f:
    for row in csv.DictReader(f):
        answers[row.get("saleor_field", "").strip()] = (
            row.get("spree_field", "").strip(),
            row.get("transform", "").strip().lower(),
        )
```

A row only counts when **both** cells match - the right `spree_field` *and* the right `transform`.
That is a deliberately strict bar: naming the target field but mis-classifying the transform (or the
reverse) scores nothing for that row. It also makes the trap rows self-enforcing - the three Saleor
fields with no Spree counterpart (`trackingClientId`, `weight`, `invoices`) only count when the
agent leaves `spree_field` blank *and* writes `none`, so an agent that over-eagerly invents a
mapping for them simply loses those points.

```python
total = len(canonical)
correct = sum(
    1 for field, expected in canonical.items()
    if answers.get(field) == expected
)
score = correct / total if total else 0.0
print(f"matched {correct}/{total}")
print(f"EVAL_SCORE={score:.4f}")
```

The score is the fraction of the canonical rows the agent got exactly right, so a perfect mapping
across all 22 rows scores `1`. As everywhere else the body is wrapped in a `try/except` that emits
`EVAL_SCORE=0.0` on any failure, and the final print is what the harness reads from the container.

> [!WARNING]
> The mapping is only as good as the fixture behind it. This ground truth was hand-built against the
> two live schemas and deliberately keeps only the rows with one defensible answer - the genuinely
> N:M or shape-mismatched fields (metadata, tax/money sprawl, vouchers) are left out of the file
> entirely rather than scored, so omission, not an explicit ignore list, is how the debatable fields
> are handled. If you build your own mapping eval, the
> [catalogue entry](../evals.md#saleor--spree-mapping) shows how those calls were made.
