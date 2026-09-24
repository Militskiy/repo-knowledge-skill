# Universal retrieval evaluation

The revised retriever improves ranking and evidence coverage on this small,
authored suite, including held-out repositories, but does not win every case or
budget. It returns more metadata and often larger responses. These results support
specific retrieval changes, not universal superiority, better reasoning, or task
completion. No specialized navigator was evaluated here.

The [protocol](PROTOCOL.md), [pinned cases](universal.json),
[machine-readable comparison](results/comparison.json), and
[generated tables including every regression](results/TABLES.md) are reproducible.
The original [development](results/before-dev.json) and
[held-out](results/before-heldout.json) baseline reports are retained.

## Study design and provenance

There are 24 positive and 8 unsupported queries over four complete pinned
checkouts: Click (Python), Express (JavaScript/templates), Cobra (Go), and jsmn (C).
Questions cover definitions, implementations, callers, tests, configuration,
templates, multiple artifacts, invented identifiers and unsupported behaviors
with lexical overlap. Relevance is manually annotated source ranges, chosen before
retrieval output. All checkout bytes are checked against their Git blobs; annotated
files also have SHA-256 checks. Sources are never executed.

Click and Express provide 12 development positives; Cobra and jsmn provide 12
held-out positives. The same implementer authored judgments after reading source;
this is not independently adjudicated or exhaustive relevance. A useful unjudged
result can receive no credit. In particular, several valid definitions can share
an identifier. Repository-level holdout limits tuning leakage but is not a blind
human evaluation, and these four small projects do not represent all ecosystems.

The baseline is commit `be16aa81c40fb9dba8af3ac6e358dc6bf92d9694`. Cases, protocol
and before reports were committed at `07f0150`, before changing the retriever.
Development runs revealed declaration/docstring errors, fragmented tests,
over-broad test-intent inference, and unstable/cropped evidence windows. Changes
addressed those mechanisms, with no repository-specific vocabulary or aliases and
no parameter sweep. Ranking/extraction was frozen at `8a2add6` before opening
held-out retrieval results.

Two subsequent review fixes are disclosed: CLI output now bypasses locale/newline
translation to preserve its UTF-8 byte contract, and an exact filename query can
match the filename without requiring it in the file body. Each was first reproduced
by an isolated regression test. No benchmark judgments were changed. All comparisons
were rerun on the final script; retrieval outcomes and measured response costs are
unchanged from the initial held-out run. The report pins the final implementation
SHA-256 and records Python, SQLite, platform and tokenizer versions.

Only **tiktoken 0.12.0 / cl100k_base** measures tokens. The CLI's `ceil(bytes/4)`
proxy is recorded separately. Complete query, navigation, excerpt and pagination
responses are charged. The sequential policy, budgets, knowledge supplied and
stopping rules are identical for before/after; actual page/follow-up counts can
differ. Native scope and the intersection of indexed files are evaluated separately.
The common evidence format is a projection for overhead analysis, not a replacement
API with all the same navigation metadata.

## Main results

Percentages below are macro averages over positive queries. nDCG awards gain for
new judged artifacts; evidence coverage requires actual verified source lines,
not merely a path or matching snippet.

| Native discovery, all 24 positives | Before | After |
| --- | --- | --- |
| Hit@1 | 37.5% | 75.0% |
| MRR@5 | 55.3% | 83.3% |
| Coverage-oriented nDCG@5 | 52.9% | 78.5% |
| Required-artifact recall@5 | 68.8% | 86.1% |
| Evidence coverage, native format at 4,000 measured tokens | 59.1% | 81.7% |
| Evidence coverage, common format at 4,000 measured tokens | 60.6% | 86.6% |

On held-out positives alone, Hit@1 rises from **41.7% to 75.0%** and
artifact recall@5 from **75.0% to 87.5%**. Held-out native evidence coverage at
4,000 tokens rises from **61.0% to 83.6%**, but at 8,000 it falls from
**84.7% to 83.6%**. The lower-cost and higher-cost comparisons tell different stories.

With **identical indexed paths** and the **same common output format**, aggregate
Hit@1 rises from 37.5% to 70.8%, artifact recall@5 from 68.8% to 81.9%, and
4,000-token evidence coverage from 60.6% to 82.4%. Thus the aggregate improvement
is not explained solely by additional files or smaller metadata. This joint
comparison does not isolate the individual effects of ranking, extraction and
pagination; there is no component ablation study.

At comparable coverage, among the 17 cases where both variants reach 50% evidence,
median native cost falls from **2,688 to 2,430 measured tokens**. Among the 13 cases
where both reach 100%, it falls from **3,131 to 2,591**. Overall, before reaches
100% on 15/24 cases and after on 17/24. Paired medians exclude unachieved targets;
they must not be read as universal cost savings. The full table includes 80% targets,
common-format costs, individual failures, and all budget points.

## Evidence supporting the changes

**Discovery:** all 23 independently listed required audit paths are indexed after
the change, versus 20/23 before. Restored paths are Express's login template,
Cobra's `go.sum`, and jsmn's `.clang-format`. Indexed counts change from 120 to 142
in Click, 196 to 234 in Express, 61 to 65 in Cobra, and 11 to 12 in jsmn. These
larger counts are not proof that every newly included file is useful. Regression
tests separately cover legitimate content under `build`, `dist`, and `target`,
extensionless/dotfile artifacts, unfamiliar language suffixes, scope overrides,
hard safety exclusions and inspectable Gitlinks/symlinks. Directory-name omissions
are a demonstrated code/test issue, not an omission observed in all four real repos.

**Structural evidence and ranking:** `click-caller` moves from outside the top five
to rank one, `click-tests` from rank two to one, and `express-definition` from
outside the top five to one. Python AST tests verify that nested callbacks and
assertions remain together, docstring prose cannot become declarations, and every
source line belongs to exactly one chunk. Regression tests verify that explicit
implementation requests prefer bodies to pure Python stubs, and explicit test
requests prefer test artifacts. Other language extraction is labelled heuristic.
The common-scope/common-format gains above support the combined changes; these
examples do not establish that any one scoring weight is optimal.

**Collection:** the separate `collect` workflow combines evidence from several
files in one response and uses verified, contiguous ranges. At byte-proxy budget
1,800, mean response cost is about **1,847 measured tokens**, and mean evidence
coverage is **83.8%** across positives. Individual responses have different actual
token counts; this is not an equal-token-cap comparison. At byte budget 3,600,
development coverage is 97.2%, but held-out coverage remains 88.6%. In held-out
cases, collection reaches complete annotated evidence for `cobra-ci` while the
fixed sequential workflow misses part of its split configuration range. However,
collection retrieves **none of the annotated evidence for `cobra-required`** at
any tested budget. It is useful in some workflows, not a reliable completeness
oracle or a general replacement for graph/native navigation.

**Negative queries:** the invented identifier returns no hits in all four after
runs, versus an incidental component/stem hit in one before run. All four
unsupported natural-language questions still produce related search hits, now
labelled `low-support`. Collection returns no excerpts for three of them but can
still spend its budget on unrelated flag evidence for `cobra-negative-topic`.
These are uncertainty signals, not calibrated abstention or answers proving absence.

**Provenance and portability:** tests distinguish unchanged source from changed
Git HEAD/configuration, preserve archive identity, verify exact emitted source and
hashes, test stale retrieval and no-op/incremental builds, and verify UTF-8/LF output
under an ASCII pipe locale. These are correctness checks, not retrieval-score claims.

## Regressions, costs, and remaining weaknesses

The generated [regression table](results/TABLES.md#individual-regressions) lists
every reduction at every tested cap and in both formats. Material examples:

- `click-defaults`: artifact recall@5 falls from 66.7% to 33.3%; documentation and
  changelog matches crowd out the annotated implementation/test. Mixed intent and
  multi-artifact recall remain weak despite a correct first result.
- `click-ci`: first relevant rank drops from two to three; native evidence at 4k
  falls from 100% to zero, recovering with a larger allowance. Configuration
  queries remain vulnerable to broad package/changelog matches and page overhead.
- `jsmn-config`: first relevant rank drops from one to three. Source mentions of
  build macros outrank the Makefile that defines the requested test combinations.
- `cobra-args`: required test variations consume several early ranks before the
  implementation. Exact-body deduplication does not remove near-duplicate variants.
- `cobra-ci`: native evidence at 8k falls from 100% to 58.3%. Window boundaries and
  the fixed per-file collection order can omit part of a configuration matrix.
- `jsmn-nomem`: evidence at 8k falls from 100% to 76.5% in both formats. Chunk and
  continuation placement loses the annotated recovery guidance. The collection
  workflow reaches 94.1%, still incomplete.

Native responses are **larger**, not smaller: mean first-query size rises from
530 to 713 tokens, while its common projection remains 216. Mean full sequential
trace cost rises from 6,139 to 7,215 native tokens (5,293 to 5,425 in the common
projection). Actual responses per trace rise from 9.33 to 11.17 under the same
bounded policy, including newly exposed continuations. This buys inspectability
and often coverage, but hurts small budgets. At 1,000 native tokens, after retrieves
no annotated source in the positive cases under this policy. At 2,000, held-out
coverage decreases from 29.2% to 25.9%. Shorter search response size is not a success
criterion here.

Other limits remain: English request cues and lexical synonyms; uncalibrated
support thresholds; exact-identifier sensitivity to spelling/case; identical-body
deduplication hiding different surrounding contexts; AST support limited to the
running Python syntax; heuristic boundaries elsewhere; incomplete dynamic/import
binding and nested workspace resolution; candidate caps and missing external
dependencies. Full-source hashing incurs I/O on every retrieval. Secret filters
still have false positives and false negatives, and scope audits do not enumerate
ignored files or all contents of pruned directories. No hostile-filesystem,
large-monorepo, latency-scalability, multilingual, or end-to-end agent study was run.

## Validation and reproduction

`python -m unittest discover -s tests -v`: **71 tests, 3 Windows symlink-privilege
skips** (68 passed). The initial version had 35 passes and three privilege failures.
No skip masks a retrieval assertion. Copied-skill CLI smoke tests pass; this is not
an end-to-end harness compatibility test.

YAML frontmatter is parsed and checked against the
[Agent Skills specification](https://agentskills.io/specification#frontmatter).
The bundled skill-creator validator rejects the existing, standard `compatibility`
field because its allowlist omits it. It passes on a temporary copy with only that
field omitted; the actual skill retains the field, separately checked against the
specification's constraints. No validator or global configuration was modified.

Follow [PROTOCOL.md](PROTOCOL.md) to obtain pinned checkouts outside this repository,
install the evaluation-only tokenizer, and reproduce `comparison.json`. Then run:

```sh
python benchmarks/summarize.py --report benchmarks/results/comparison.json
```

Build timings in reports are single-run observations, not a latency benchmark.
Raw source and generated indexes are not committed. All claims above concern
retrieval and artifact correctness only.
