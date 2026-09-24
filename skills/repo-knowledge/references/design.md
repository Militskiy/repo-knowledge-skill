# Design and operational reference

## Why this shape

A small skill description is discoverable by the harness. The full skill teaches
progressive retrieval; code and this reference load only when useful. Building
is deterministic local analysis, with no LLM summaries to drift or incur repeated
model cost. Search returns compact evidence locators before original source.
This design targets context efficiency, not smaller on-disk storage.

A content fingerprint covers eligible file bytes, scope/configuration, and the
index schema version. Builds copy the previous SQLite generation, delete removed
records, reindex changed files, recompute graph links, and regenerate Markdown.
An exclusive build lock prevents two writers; `CURRENT` is atomically replaced
only after a second source scan confirms a consistent snapshot. Readers use an
immutable generation. A failed build leaves the previous pointer intact.
Unchanged content does not rebuild. Directory/filename and declaration-anchored
IDs survive many unrelated edits; renames, duplicate declaration reordering, and
large-chunk changes can change IDs. Always respect the snapshot digest.

Every retrieval hashes all eligible source files to detect changes, even if
mtime and size were preserved. This trades local I/O/CPU for stronger freshness.
It is not a zero-cost retrieval cache. HEAD in a generation is build-time metadata;
the content fingerprint, not HEAD alone, identifies the indexed working tree.
A source tree changing adversarially during reads is outside the security model.

## Retrieval and graph limitations

SQLite FTS5 uses Porter stemming and Unicode tokenization. Indexed text preserves
whole identifiers and adds acronym/CamelCase/snake_case components. BM25 weights
path/title/body by 4/9/1. Up to 160 candidates are reranked by term coverage;
results include at most two chunks per file. These fixed choices are transparent,
not learned or universally optimal. Large ambiguous queries should be narrowed.

Go function/method/type declarations, common Python/JS/TS/Rust-style declarations,
and Markdown headings are recognized heuristically. Leading single-line comments
are attached. Other syntax, including complex multiline/generic declarations,
falls back to windows of at most 64 lines. A chunk is a navigation unit, not an
AST node or guaranteed complete function. Languages without structural extraction
still receive lexical search over eligible text.

Go module-local quoted package paths resolve to files in that package; these
matches can include non-import string literals. JS/TS relative import matches are
heuristic. Python imports use `ast.parse` without executing modules; absolute and
simple relative local module paths are linked. Dynamic loading and some aliases
are not resolved. A unique declaration-name mention may be in a comment or string
and is not proof of a call. Ambiguous names are not linked. Test-file conventions
are hints, not coverage proof. Markdown links resolve only to indexed local files.
All links must be verified against source for behavioral conclusions.

Generated maps show directory groupings, not invented architectural ownership.
Read `.repo-knowledge/CURRENT` to locate
`.repo-knowledge/generations/<snapshot>/INDEX.md`. Do not load all maps into an
agent prompt. `neighbors` is a bounded, one-hop, bidirectional graph view.

## Configuration

Optional repository-root `.repo-knowledge.json`:

```json
{
  "exclude": ["fixtures/*", "docs/translations/*"],
  "aliases": {"quota": ["traffic limit"], "auth": ["authentication login"]}
}
```

Exclusions are case-sensitive Python `fnmatch` globs over POSIX relative paths,
not gitignore rules; `*` can match `/`. Aliases are exact lowercase query-term
keys and nonrecursive expansions. Keep them small and repository-specific.
The configuration file is not itself indexed. It has a 32 KiB limit and accepts
only the two fields above. Changes require a build. Aliases change retrieval;
record them when comparing benchmarks. Defaults contain no 3x-ui-specific aliases.

Git mode scans tracked files; `--include-untracked` adds unignored untracked files.
Tracked files remain eligible even if subsequently matched by gitignore. Archive
mode (`--filesystem`) does not apply gitignore. Built-in exclusions apply in all
modes; there is deliberately no switch to include keys or vendored build artifacts.
A deleted/modified/new eligible file changes freshness; changes to excluded files
do not. Do not interpret the index as exhaustive repository contents.

## Bounds, privacy, and errors

Per-file limit: 512 KiB. Total eligible source: 128 MiB, at most 20,000 files.
A text line over 4,000 characters causes that file to be excluded. Binary/NUL,
non-UTF-8, unsupported extensions, lockfiles, minified maps, common build/vendor
folders, symlinks, common secret filenames, PEM private keys, and selected token
patterns are excluded. Scope overflow fails rather than silently truncating.
`build` reports skipped counts. These safeguards are not exhaustive secret
classification, comprehensive language support, or a hostile-filesystem sandbox.

The SQLite database stores indexed source, including literals not recognized as
secrets. Protect its filesystem permissions as you would the repository. Do not
upload or commit it by default. The program makes no network requests, invokes no
target-repository code, and does not treat retrieved instructions as trusted.
It calls only Git discovery/revision commands, without shell interpolation.

`query`, `show`, and `neighbors` return valid UTF-8 JSON bounded by `4 * budget`
bytes, including metadata, newline, and provenance. Units are explicitly NOT
model-token counts. Budget range is 128..100000; default is 1200. `next_offset`
counts result items. Retry with a larger budget when a single item cannot fit;
no source line or provenance field is silently cut. Search snippets are intentionally
shortened and are not full evidence. `show` identifies actual line numbers and
source SHA-256. Offsets must be reused only with the same query and snapshot.
Build/status output is not retrieval-budgeted. Status lists changed paths.

Exit 0: success. Exit 2: invalid input, missing/unsafe index, stale retrieval, or
I/O/SQLite error. Exit 3: `status` found stale content. Missing FTS5 is reported by
SQLite; install a Python build with FTS5 rather than silently using another ranker.
A broken index should be rebuilt into a new output directory, not hand-edited.

## Storage and upgrades

Each generation stores a complete database and navigation maps. Incremental work
saves parsing/indexing, not a full copy of disk storage. Old generations remain
for concurrent readers and historical snapshots and can accumulate. When no
reader or builder is running, remove the specific owned output directory and
rebuild to reclaim space. Never remove a directory merely because its name looks
like an index. A stale build lock requires checking for a live builder before
manual removal. Unknown nonempty output directories and symlinked output paths
are refused. Do not share one index between different checkout roots.

After updating the skill implementation, use a fresh output directory for a
changed index schema or changed extraction logic. The schema version participates
in the fingerprint; maintainers must increment it for indexing changes. Pure
retrieval changes do not require rewriting original source.
