# Scoring Routine

Write a Python file named `eval.py` into `/workspace/brackets_eval`. For now do not make any LLM /
agent calls and do not run the script yourself — just write the file and come back once it is done.

## What `eval.py` must do

When executed with `python eval.py`, it must:

1. Read the directory containing the implementation under test from the environment variable
   `REPO_DIR` (i.e. `os.environ["REPO_DIR"]`). A file named `bracket_balance.py` lives in that
   directory and defines a single public function `is_balanced(text: str) -> bool`.
2. Import that implementation and exercise it with objective checks derived from the specification
   below.
3. Print exactly one line to stdout of the form `EVAL_SCORE=<float>` where the float is between
   `0.0` (wholly incorrect) and `1.0` (wholly correct). That line is how the verdict is read, so
   it must be the only `EVAL_SCORE=` line you emit.

## Guidance

- A good scorer is one that scores a correct solution high and an incorrect solution low. Do not
  over complicate.
- Do not assume the implementation is correct — your job is to detect when it is and when it is not.
  Cover the behaviours in the specification broadly; a single narrow check is easy to fool.

---

# Task: Balanced Bracket Checker

## The module to evaluate
A Python file `bracket_balance.py` that exposes exactly one public function:

```python
def is_balanced(text: str) -> bool:
    ...
```

## Specification
`is_balanced` returns `True` if every opening bracket in `text` is closed by the
correct matching bracket of the same type, in the correct nesting order, and `False`
otherwise.

The three bracket types are: `()`, `[]`, `{}`.

- An empty string is balanced (`True`).
- Strings with no brackets at all are balanced (`True`) — other characters are ignored.
- Mismatched types make it unbalanced: e.g. `([)]` is `False` (a `[` closed by `)`).
- Unclosed brackets make it unbalanced: e.g. `((` is `False`.
- Prematurely-closed brackets make it unbalanced: e.g. `)` is `False`.
- The function must accept any `str`. Any input not satisfying the rules above returns
  `False`; it must never raise an exception.