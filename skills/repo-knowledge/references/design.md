# Design and operational reference

## Source identity and storage

The tool is standard-library Python, SQLite FTS5, and Git. It neither executes
source nor uses embeddings, models, services, or network access. Installing the
skill means copying the entire folder, including this reference and `scripts/`.
Only the separate benchmark needs a tokenizer package.

`source_id` hashes sorted indexed paths and their SHA-256 content hashes. It is
independent of checkout location, Git HEAD, aliases, and extraction version.
`snapshot` (the build report calls it `fingerprint`) identifies the indexed paths,
bytes, scope/configuration, and index version. Thus two configurations indexing
identical bytes can share `source_id` but have different index snapshots. Neither
value describes excluded content or a complete repository history.

Every retrieval scans and hashes all eligible files, including when mtimes are
unchanged. `show` and `collect` recheck selected file hashes before emitting lines.
This costs local I/O and CPU on every call. It does not prevent an adversarial
source tree changing during reads. `fresh: true` describes the checked snapshot,
not an atomic filesystem transaction or a guarantee about subsequent edits.

`status` reports the indexed and current source identity, changed paths and
configuration, and separate `build_version_control` / `current_version_control`.
Git HEAD may change without changing eligible bytes; in that case the content
index remains fresh. Git metadata records the enclosing Git root and scope prefix,
including when indexing a subtree. An unborn repository has null HEAD. Filesystem
mode explicitly reports filesystem identity and does not borrow an ancestor's
Git revision. Gitlinks, unmerged entries, and Git symlinks are reported and not
expanded, including on Windows where a symlink may be checked out as plain text.

Builds are incremental and idempotent. Changed/deleted files are replaced in a
copy of the prior database; graph links and Markdown maps are regenerated. A
second source scan checks consistency before an atomic `CURRENT` replacement.
An exclusive build lock and immutable generations protect concurrent readers.
A failed build leaves the old pointer intact. IDs survive many unrelated edits,
but renames, declaration changes, duplicate reordering and extraction upgrades can
change them. Respect both snapshot and per-file hashes.

The owned output defaults to `.repo-knowledge/`. `--output` accepts another
location, including outside the repository. The source root or its ancestor,
symlinked output paths, and unknown nonempty output directories are refused.
Other tool-owned outputs and the default output name are not indexed. Generated
maps group files by actual directories, without assigning architectural ownership.

Version 2 requires a fresh output directory when upgrading from version 1. Old
generations retain complete databases and maps for active readers; no automatic
cleanup occurs. To reclaim space, first verify no reader/builder is using the
specific owned output, then remove that output and rebuild. Never remove a path
merely because its name resembles an index. A build lock left by a crashed process
requires checking for a live builder before manual removal.

## Discovery and scope audit

Git mode reads tracked files regardless of gitignore matches. `--include-untracked`
adds unignored untracked files. Archive mode (`build --filesystem`) walks the tree
without gitignore semantics. These choices are explicit scope boundaries.

There is no language-extension allowlist. Bounded UTF-8 text is eligible, including
extensionless scripts, templates, dotfile configuration, lockfiles, and unfamiliar
languages. Directories called `build`, `dist`, or `target` are not excluded by name.
Tracked dependency directories are also eligible. In archive/untracked scope only,
`node_modules`, `vendor`, `.venv`, `venv`, `__pycache__`, and `.next` are omitted by
default. An explicit include scope can restore their eligible text. This may add
noise or expose sensitive text missed by the filters; review the audit and scope.

The following remain hard exclusions in all scopes: version-control internals,
owned outputs, unsafe/symlink paths, common private-key and credential filenames,
live `.env` variants, minified/source-map names, binary/control-character content,
non-UTF-8 data, oversize files, very long lines, and detected credential patterns.
`.env.example`, `.env.sample`, and `.env.template` are eligible subject to content
checks. The tool configuration is consumed as configuration, not source evidence.
These are conservative safeguards, not a complete secret scanner: false positives
(even literal private-key headers in tests) and false negatives are possible.

Bounds: 512 KiB per file, 128 MiB total source, 20,000 included files, 4,000
characters per line. Archive discovery refuses more than 80,000 enumerated file
paths. Overflow fails explicitly rather than publishing a truncated index. A
size limit cannot be bypassed with inclusion globs; use scoped native inspection
for intentionally excluded artifacts.

`scope` works before building with `--filesystem` / `--include-untracked` if needed.
With an existing index it uses that index's recorded discovery mode and the current
configuration. It reports per-path decisions and reasons plus considered file
counts, pruned directory counts, included extensions and excluded-entry counts.
`--excluded-only`, `--path GLOB`, `--limit N`, and `--offset N` filter/page the audit;
coverage totals remain global to the selected discovery scope. Pruned directories
are single audit entries, not counts of their unknown contents. Git-ignored and
out-of-scope untracked paths are not enumerated. No audit record does not prove
that a path is missing. Very large summary metadata may require a larger budget.
`considered_files` counts file-path candidates, including missing paths and
unexpanded Git entries, rather than only readable regular files.

Optional `.repo-knowledge.json` in the source root:

```json
{
  "include": [],
  "exclude": ["private-fixtures/*"],
  "aliases": {}
}
```

An empty `include` means all otherwise eligible content in the discovery mode.
A nonempty list is an allowlist. Both lists use case-sensitive Python `fnmatch`
globs on POSIX relative paths; `*` can match `/`. Exclusion wins over inclusion;
hard safety exclusions always win. Changing scope or aliases requires a rebuild.
The file is limited to 32 KiB and these three keys. Aliases remain optional exact
lowercase term-to-string-list expansions, nonrecursive and empty by default.
There are no built-in repository aliases or vocabularies. Disclose user-supplied
aliases when comparing retrieval performance.

## Extraction and evidence boundaries

Python uses `ast.parse` without importing code. Decorators, multiline signatures,
docstrings, nested callbacks and assertions remain with their enclosing function.
Class headers and direct methods are separate units; gaps remain source context.
Pure `pass`/ellipsis bodies are labelled declarations and receive less preference
for implementation requests. Syntax newer than the running interpreter, malformed
files, or failed parses use labelled heuristic/window fallbacks.

Go declarations, common JS/TS dotted function assignments and arrows, generic
Rust-style declarations, and conservative C-family definition shapes are recognized
heuristically. Markdown/MDX headings and underlined RST/Markdown headings form
sections. Fenced Markdown text is not treated as headings. Unsupported syntax
still receives lexical search over bounded text windows.

Units are partitioned into at most 64-line, nonoverlapping chunks. `method` states
how a range was extracted; `unit` states its enclosing extracted range. A heuristic
unit is not a guaranteed complete function, AST node, or meaningful program block.
Nested non-Python constructs, macros, multiline types, embedded languages and
fence variants may be misidentified. Python nested definitions are retained in
outer source, but are not separately registered as graph declarations.

`show` emits original line-numbered text with a file SHA-256, and supports a chunk
or file ID. `--context 0..20` adds surrounding lines. Pagination can still cut a
function; continue when necessary. Original decoding and newline splitting define
line numbers. Search snippets are intentionally shortened locators, not full proof.

`collect` searches up to 80 ranked candidates, suppresses very weak candidates,
orders the first candidate per file before repeats, and chooses contiguous source
windows under a common per-range allowance. It prefers whole chunks when they fit;
otherwise it expands around a stable lexical anchor, with Python executable lines
preferred over docstring matches. `partial` is true when it omits part of the
extracted unit. It uses no gold labels, architecture knowledge or external services.
The same snapshot, query, intent, path, budget and limit are needed for continuation.
More budget grows individual windows, but changes in packing can still change the
set of files returned; monotonic overall answer coverage is not guaranteed.

## Ranking and navigation

SQLite FTS5 uses Porter stemming and Unicode tokenization. Index text adds acronym,
CamelCase and snake_case components. A query uses up to 24 content terms, or 48
including explicit alias expansions. Up to 400 BM25 candidates (path/title/body
weights 4/9/1) are reranked. `--path GLOB` applies before the candidate limit.

Coverage uses the same FTS stemming as candidate generation, with term rarity
weights `1 + log(1 + chunks / (1 + document_frequency))`. Ranking combines weighted
coverage (6), literal title coverage (2), exact identifier evidence, explicit
request intent, and a bounded BM25 rank tie-break. File repeats receive a soft
0.8 penalty. Exact duplicate bodies share a slot; this can hide identical text
in different surrounding contexts. Use path-scoped queries to inspect copies.
There is no fixed two-chunks-per-file ceiling.

Definition, implementation, caller and test requests use generic syntax and
conservative English request cues, never repository terminology. `--intent`
overrides automatic inference. Test paths are labelled `test-path-hint`, not proof
of coverage. Caller preferences use lexical call shapes and can match comments or
strings. Exact single CamelCase/snake_case/dotted-identifier queries require the
literal identifier in source or an exact filename, instead of accepting component-only matches. This can reduce
recall for misspellings and case changes; reformulate when needed.

`assessment` is `no-match`, `low-support`, or `lexical-match`. The last two use a
heuristic weighted-coverage threshold of 0.65, not a calibrated probability.
Neither one verifies a claim. Larger query budgets expose matched/missing terms,
deduplication counts, truncation and candidate-limit information; small budgets
keep the assessment and any candidate-cap warning. Long queries, common words,
non-English questions and synonym-only paraphrases can perform poorly.

The graph includes containment, unique-spelling lexical mentions, local import
hints, filename test hints, and local Markdown links. Python `ast.Call` links are
explicitly `call-syntax`: even a unique name does not resolve binding, receiver,
aliases or dynamic dispatch. Several sites for the same relation share one edge
with up to three evidence descriptions and an omitted-site count. Go imports use
a root module and quoted paths (which can include non-import strings); Python
imports do not infer arbitrary source roots; JS/TS imports resolve a small set of
relative file conventions. Nested modules/workspaces, dependency code, runtime
loading and ambiguous symbols can remain unlinked.

`neighbors` is one hop, bidirectional by default, filterable by kind/direction and
bounded by its complete response budget. Returned relations are marked inferred;
inspect linked source before drawing behavioral conclusions. `collect` does not
automatically traverse that graph. It can miss required related artifacts absent
from the lexical candidates. Manual bounded navigation remains useful.

## Response cost and stopping

All retrieval and audit responses are valid UTF-8 JSON bounded by `4 * budget`
bytes, including metadata, excerpts, omitted counts, pagination and final newline.
The CLI writes UTF-8 bytes directly so pipe locales and Windows newline translation
do not alter that output contract.
Budgets (128..100000) are `ceil(UTF-8 bytes / 4)`, not tokenizer measurements.
If metadata or a complete source-line item cannot fit, increase the budget. There
is no silent source-line or provenance truncation. Build/status are operational
reports outside this response-budget contract.

Query and audit limits expose continuation even when more ranked items exist than
the requested limit. `next_offset` is an item count; for `show` it counts source-line
items rather than absolute line numbers. `collect` reports `budget-or-limit`,
`candidates-exhausted`, `low-support`, or `no-match`. Those are mechanical stopping
conditions. The tool cannot know the required artifacts or certify completeness.
Keep a task-level ledger of all prior responses, verify source claims, and report
unresolved needs rather than concluding absence from an empty result.

Exit 0: success. Exit 2: invalid input, unsafe/missing index, stale retrieval,
I/O/SQLite error. Exit 3: `status` found stale content. Missing FTS5 is an explicit
SQLite error; use a Python build with FTS5. Do not silently replace the ranker.

The evaluation protocol (`benchmarks/PROTOCOL.md`) and reports in the
[source repository](https://github.com/Militskiy/repo-knowledge-skill) describe measured retrieval behavior. Those benchmark files are
not needed in an installed copy of the skill. Retrieval metrics alone cannot
establish better reasoning, task completion, or safety of a proposed source change.
