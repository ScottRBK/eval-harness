# New-feature authoring gate

Complete this gate before running an evaluated model against an adapted new-feature eval. It is an
author-facing **proof matrix**: the candidate receives an ordinary development request containing
only the task, its public contracts, and relevant repository context.

## Trace every hidden assertion

Map each hidden assertion to one of these sources:

- **Explicit contract:** a name, signature, status, or behavior stated in the prompt because other
  code depends on it.
- **Preserved regression:** behavior that passes at the pinned parent and that the task asks the
  candidate to preserve.
- **Discoverable platform behavior:** behavior implied by the task and documented by an API or
  repository material available to the candidate.

Change the prompt or the assertion when no source applies. Edge-case inputs may remain hidden, but
the product behavior they exercise cannot be a hidden requirement.

Match assertion precision to contract precision:

- Assert that an operation errors when error wording is discretionary. Match exact text only when
  the wording is itself a public contract.
- Assert observable behavior rather than an internal method, handler count, data structure, or
  command-line mechanism.
- Treat examples as examples unless the prompt marks their format as exact.
- Prefer ordering and eventual-state checks to arbitrary wall-clock thresholds.
- Keep identity, package-version, and manifest assertions only when they are relevant to the task.

**Completion criterion:** every hidden assertion has one documented source, and every orphan or
over-specific assertion has been changed or removed.

## Normalize feature and regression evidence

A full-suite pass rate can hide a weak feature when the repository already has many passing tests.
When the eval measures both implementation and preservation, identify feature and regression cases
before writing the scorer and normalize them independently:

```text
feature = passing feature cases / total feature cases
regression = passing baseline cases / total baseline cases
score = (feature + regression) / 2
```

The equal-weight formula is the default when feature behavior and regression safety are both
first-class outcomes. Choose a different weight only when the eval's purpose requires it, and record
the reason before running a model.

Prefer disjoint feature and regression sets. If a case belongs to both, document that its failure is
intentionally weighted twice. Include integration behavior in the feature set rather than counting
only a convenient low-level unit-test file. Prefer dedicated test targets or stable case IDs over
classifying results by human-readable reporter phrases.

Write the expected score curve before implementation: oracle, no-op, a meaningful partial feature,
and a regression-breaking candidate. This makes the scorer's intended interpretation reviewable.

**Completion criterion:** both component denominators and the final formula are fixed, and every
control candidate has an expected score or range.

## Keep the score tree authoritative

Visible test edits can support the candidate's local TDD loop, but they are not scoring evidence. At
score time, rebuild an authoritative tree around the candidate's source:

1. Remove candidate-owned test directories when untracked files could affect discovery.
1. Restore baseline regression tests from the pinned local ref.
1. Overlay eval-owned hidden fixtures unconditionally.
1. Run an explicit test-file or test-target list.

If the feature necessarily changes fixture counts, timing, or result shapes, put the corresponding
changes in the authoritative score fixtures. Keep hidden tests and oracles in
`score_embedded_values`, outside eval-owned image build contexts, so they are absent from `arrange`
and `act`. Keep candidate source outside any directory the scorer restores.

This restoration policy belongs only in the eval's authoring material. The candidate prompt remains
an ordinary request to develop and test the feature.

**Completion criterion:** replaying score setup produces the intended test tree from both an oracle
workspace and a candidate workspace containing edited or untracked tests.

## Check whether the completed feature is public

Run this branch when the oracle came from an existing project or feature commit. The check asks
whether a candidate can retrieve the implementation instead of producing it.

For a **public commit leak**, inspect public branches, tags, commits, pull requests, issues, and
code search using the repository name and exact API identifiers from the prompt. Inspect the
starting snapshot for repository URLs, original commit IDs, author names, badges, and other
breadcrumbs.

For a **package-registry leak**, inspect the project's npm, PyPI, crates.io, or equivalent package
records. Check package names, published versions, repository metadata, and downloadable artifacts
for a release that already contains the feature. Include lockfiles, README installation commands,
and identity assertions in the starting tests in this review.

When either route exposes the answer, prefer a private, identity-scrubbed snapshot:

- Create a new root commit from the pre-feature source so public history and commit IDs are absent.
- Remove original repository and package identity metadata, updating identity-specific baseline
  tests at the same time.
- Authenticate through the harness-level token described in
  [Authorisation](../authorisation.md#private-repositories-harness-level-github-token), preferably
  with a fine-grained token scoped to the snapshot repository.
- Remove the Git remote before `act`.

Tool restrictions such as `web_search` and `web_fetch` are best-effort controls, not network
isolation. Scrubbing removes breadcrumbs but does not hide a public project named directly in the
prompt. Where copying would invalidate the eval and network access remains available, choose a
different subject or provide stronger isolation outside this pattern.

**Completion criterion:** every practical public retrieval route is removed, explicitly accepted as
residual risk, or causes the task to be replaced.

## Prove the scorer in the actual image

Run the proof matrix in the same image and runtime versions used by the harness:

- **Parent baseline:** the repository's original regression suite is green.
- **Oracle:** the complete authoritative suite scores `1.0`.
- **No-op:** the untouched parent produces the declared low score.
- **Partial feature:** feature score drops while preserved baseline behavior remains visible.
- **Regression break:** regression score drops independently of feature progress.

Prefer machine-readable reports or test-runner event streams. When text parsing is unavoidable, pin
the reporter, combine the streams it uses, run explicit targets, and guard the expected test total.
A host-machine run is supporting evidence, not a substitute for this image-level proof.

Separate candidate outcomes from evaluator failures. A compilation error caused by candidate source
is a candidate outcome. A missing fixture, an impossible count from the oracle, or a parser that
cannot read the oracle run is an evaluator defect and should raise so the harness marks the run
FAILED rather than assigning a misleading zero.

For a non-trivial adapted oracle suite, give an independent reviewer the prompt, hidden tests,
scorer, parent snapshot, oracle diff, harness pattern, and relevant platform documentation. Ask the
reviewer to find unmatched requirements, brittle assertions, misleading score curves, restoration
conflicts, source leaks, and parser assumptions.

**Completion criterion:** every proof-matrix row matches its expected result in the actual image,
and the readiness review has no unresolved issue that could make a reasonable solution fail.
