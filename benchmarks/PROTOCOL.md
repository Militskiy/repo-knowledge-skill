# Universal evidence evaluation (protocol v1)

The cases in `universal.json` were authored by reading pinned source before any
retriever output. Gold is a set of paths and line ranges, not retriever chunk IDs
or titles. Source hashes and Git blob checks pin the judgments. Blank lines do
not earn evidence credit. These are small, purposive judgments by the implementer,
not an independent human study or exhaustive relevance labels. An unjudged result
may still be useful. Negative questions are unsupported by the supplied snapshot;
lexical overlap is deliberately allowed. They do not assert absence everywhere.

Click and Express are development repositories. Cobra and jsmn are held out from
retrieval tuning: their source is read to define gold, and baseline results are
saved, but their retrieval scores are not inspected until implementation freezes.
Record changes made after opening that evaluation; do not silently relabel failures.

## Controls

- Before: the script at `be16aa81c40fb9dba8af3ac6e358dc6bf92d9694`. After: the
  working script, identified by SHA-256 in each report. No competitor is evaluated.
- Full, clean, byte-verified tracked checkouts; no target code, installs, or tests
  are executed. No aliases, supplied architecture maps, or per-repository tuning.
- Native discovery is evaluated first. `--common-scope` separately restricts both
  discoverers to their path intersection, exposing changes caused by source scope.
  The intersection is an evaluator adapter, not production scope configuration.
- Report tracked and indexed counts, exclusions, and omissions among explicitly
  required source/configuration/documentation/test paths. This required set is a
  discovery audit sample, not an exhaustive classification of all repository files.

## Ranking and workflow

Hit@1 and MRR@5 count a locator as relevant when its range intersects a judged
range. Required-artifact recall@5 counts distinct judged artifacts reached.
nDCG@5 awards binary gain only for a result that adds a previously unreached
artifact; repeated chunks from one artifact cannot inflate gain. This is a
coverage-oriented nDCG, not graded semantic relevance. Ranking metrics describe
locators, while evidence coverage requires actual verified source lines.

The identical sequential policy for both implementations is frozen here:

1. Query once, limit six, byte-proxy budget 900. At most one advancing query page.
2. Show at most six candidates, first one per file, then remaining candidates in
   rank order. Each response gets 900 proxy units. At most one advancing show page
   for each of the first two candidates.
3. Read one neighbor response for the first candidate, budget 900. Show at most
   two unseen chunk neighbors in returned order. File-only links are not expanded.
4. Stop. No gold-aware rewrites, retries, confidence-based stopping, or oracle
   evidence selection. Negative queries use the same policy.

Build/status messages are operational costs and are outside retrieval curves.
All retrieval messages, including query pages, neighbor responses, show pages,
metadata and empty responses, are charged. Input prompts are held identical and
are not included. Traces report UTF-8 bytes and the tool's byte proxy separately
from measured tokens. The tokenizer is **tiktoken 0.12.0, cl100k_base**;
`disallowed_special=()` treats source as ordinary text. No model calls occur.

We replay whole-response trace prefixes at 1k, 2k, 4k, and 8k measured-token caps.
If the next complete response does not fit, that prefix stops: no partial JSON,
free metadata, or skipping an expensive response to fit a later one. Actual
delivered cost can be below the cap. This is an offline workflow replay, not a
token-aware runtime budget guarantee. Cost at 50%, 80%, and 100% evidence coverage
is the first trace prefix to reach that level, or null when never reached.

Native JSON and the same canonical evidence projection are measured separately.
The projection keeps snapshot, paths, ranges, snippets/source, source hashes when
present, relation evidence, and pagination. It removes IDs, titles, scores,
warnings, and other operational fields. It is an overhead diagnostic, not a
drop-in API with identical navigation affordances. Selection and steps are held
fixed when projecting; differences at equal canonical budgets come from evidence
selection/extraction and the source scope, not native metadata volume.

Evidence coverage is the fraction of distinct nonblank gold lines actually
returned. Artifact coverage requires all annotated lines in an artifact. Precision
counts annotated evidence lines divided by all returned nonblank lines; useful
unannotated context lowers this conservative figure. Report individual cases and
nulls, not only averages. Neither metric establishes reasoning or task completion.

The optional new `collect` workflow is reported separately at four byte budgets.
Its metadata and excerpts are fully measured. It is not an equivalent-step
comparison with the sequential workflow. Do not attribute its gains solely to
ranking, and do not use gold to choose its budget or stopping point.

## Reproduce

Use Python 3.10+ and install `benchmarks/requirements.txt` in an evaluation-only
virtual environment. Obtain each repository outside this checkout, disable
`core.autocrlf`, and check out its exact commit from `universal.json`. For example:

```sh
git -c core.autocrlf=false clone https://github.com/pallets/click.git /tmp/kb-eval/click
git -C /tmp/kb-eval/click checkout --detach 934813e4d421071a1b3db3973c02fe2721359a6e
# Repeat for the other three URLs and commits in universal.json.
python benchmarks/universal.py --repo-cache /tmp/kb-eval --split dev \
  --variant before --report /tmp/before-dev.json
python benchmarks/universal.py --repo-cache /tmp/kb-eval --split all \
  --variant both --common-scope --collect --report /tmp/comparison.json
```

The evaluator fetches nothing. The tokenizer downloads its vocabulary on first
use; cache it before offline runs. The old script is loaded from local Git history.
Case definitions, policy, and tokenizer stay fixed across before/after runs.
