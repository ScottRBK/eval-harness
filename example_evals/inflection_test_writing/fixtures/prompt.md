# Task: write a test suite for this library

The repository in this workspace is `inflection`, a small pure-Python port of Ruby on Rails'
inflector (`pluralize`, `camelize`, `ordinalize`, and friends). We have adopted it internally,
but it has no test suite, and some internal refactoring of the module is planned soon. Before
anyone touches it we need a regression safety net: a test suite that pins down the library's
current behaviour precisely enough that any accidental behaviour change gets caught.

## Requirements

- Write pytest tests covering the behaviour of every public function in
  `inflection/__init__.py`.
- Put your tests in one or more `test_*.py` files at the **repository root**.
- The suite must pass with a bare `pytest` invocation from the repository root - that is how
  CI runs it. Do not add pytest config files (`pytest.ini`, `tox.ini`, `setup.cfg`,
  `pyproject.toml`).
- The CI image provides only pytest and the Python standard library, so do not import any
  other third-party package.
- Do not modify `inflection/__init__.py` or any other library code. This task is tests only.

## What good looks like

- Test behaviour, not implementation. Call the functions and assert on their outputs. The
  refactor may move code around, so tests must not depend on the module's source text or
  internal structure - they should fail only when observable behaviour changes.
- Be thorough. Cover edge cases and boundary conditions, not just the happy path - a suite
  that only exercises the obvious inputs will wave subtle behaviour changes through.
- Write your own assertions. The docstring examples cover only a small fraction of the
  behaviour, so simply re-running them with doctest is not enough.
