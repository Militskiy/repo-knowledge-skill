# Repo Knowledge Skill

A portable Agent Skill for **search -> linked evidence -> bounded source collection**.
It builds a local, source-backed knowledge base rather than an LLM-written wiki.
No embeddings, API keys, services, or third-party Python packages are required.

## Repository policy

The default branch is `main`. Save project changes on focused task branches and
review them through pull requests before merging. This remains the repository
policy established at initialization. Setup and tests are documented below.

## Install in Codex or OpenCode

Both harnesses document discovery from `.agents/skills/`. From this repository:

```sh
# Shared user-level installation. Refuse to merge into an existing install.
test ! -e "$HOME/.agents/skills/repo-knowledge" || exit 1
mkdir -p "$HOME/.agents/skills"
cp -R skills/repo-knowledge "$HOME/.agents/skills/repo-knowledge"
```

For a project-local installation, copy the same folder into that project's
`.agents/skills/repo-knowledge/`. OpenCode also supports
`~/.config/opencode/skills/repo-knowledge/`. Copy the **entire folder**, including
`scripts/` and `references/`, not just `SKILL.md`. Start a new harness session and
request the `repo-knowledge` skill (in Codex, `$repo-knowledge`). No agent system
prompt, MCP server, or target-repo executable needs to be installed.

Requires **Python 3.10+**, SQLite with **FTS5**, and Git for normal discovery.
The package format and documented discovery paths have been checked; running the
CLI in a copied skill directory is not an end-to-end harness compatibility test.

## Use directly

```sh
KB="$HOME/.agents/skills/repo-knowledge/scripts/repo_kb.py"
REPO="/absolute/path/to/your/repository"
python3 "$KB" --repo "$REPO" build
python3 "$KB" --repo "$REPO" scope --excluded-only --budget 1800
python3 "$KB" --repo "$REPO" query "configuration loading" --limit 5 --budget 900
python3 "$KB" --repo "$REPO" collect "your question requiring several files" --budget 1800
# Replace the ID below with an id from query results.
python3 "$KB" --repo "$REPO" show c-RETURNED_ID --budget 1200
python3 "$KB" --repo "$REPO" neighbors c-RETURNED_ID --budget 700
python3 "$KB" --repo "$REPO" status
```

Global flags (`--repo`, `--output`) precede the subcommand. Default output is
`REPO/.repo-knowledge/`; exclude it from version control. `--output` can place it
outside the source tree. Builds are incremental and idempotent. A source/config
change makes retrieval fail closed until another build. Unchanged files are
hashed but not reindexed. Original source paths, line ranges, snapshot digest,
and source SHA-256 accompany retrieval.

`query` accepts a natural-language question or an exact identifier. Optional
`--intent definitions|implementations|callers|tests|mixed` makes a request explicit;
`--path GLOB` restricts candidate paths. Results expose extraction methods and
heuristic lexical support. Search snippets locate evidence; inspect source before
claiming behavior. `show` also accepts a file ID and `--context 0..20`.

`collect` returns several original source ranges under one complete-response
budget. It prefers one range per file before repeats and labels partial excerpts.
Its stopping reason describes a budget, candidate, or lexical-support limit;
it cannot certify that a question is answered. Navigation can be filtered with
`neighbors --kind imports --direction in`. Graph links remain inferred.

`build --include-untracked` includes new Git-unignored files. `build --filesystem`
explicitly indexes an archive without Git or gitignore semantics. Reuse the same
build flags when refreshing a non-default scope. Omitted results have a
`next_offset`; keep the same query, intent, path, budget, limit and snapshot when
continuing. Increase the budget if no item fits. Version 2 indexes require a fresh
output directory when upgrading from version 1.

Discovery accepts bounded UTF-8 text without a language-extension allowlist.
Tracked source is not excluded just because a directory is named `build`, `dist`,
`target`, or `vendor`. Inspect `scope` for decisions, exclusions, extensions and
coverage counts; pruned-directory counts are not file counts. Optional
`.repo-knowledge.json` `include`/`exclude` globs narrow scope. Hard safety and size
checks still apply. See the reference for archive dependency defaults and limits.

`status` distinguishes indexed content identity (`source_id`), index snapshot,
content freshness, and build-time/current Git metadata. An unchanged working tree
can remain fresh across a HEAD change. Archives do not inherit an ancestor's HEAD.

**Budget units are `ceil(UTF-8 response bytes / 4)`, not measured model tokens.**
The bound includes JSON framing and provenance. This limits material sent to an
agent; it does not establish a particular token saving, model accuracy, or task
success improvement. `collect` bounds only its own response; count every query,
neighbor response, excerpt and continuation in a task's total allowance. `build`
and `status` are operational reports, not budgeted retrieval responses.

## What is linked

Each generation contains a SQLite FTS5 index and relative Markdown navigation:
`INDEX.md -> modules/*.md -> files/*.md -> original source`. The graph provides
file/chunk containment, Go package imports, Python imports, JS/TS relative
imports, unique lexical symbol mentions, filename-based tests, and Markdown
source links. Neighbors include incoming and outgoing edges with their evidence.
These are navigation heuristics, **not semantic dependency/call-graph proofs**.

Retrieval combines identifier splitting, Porter stemming, path/title/body BM25,
term rarity/coverage, request intent, duplicate suppression, and file diversity.
Python AST ranges preserve nested callbacks and assertions; other declarations and
headings use labelled heuristics with bounded line-window fallbacks. See
[design, security, limits, and configuration](skills/repo-knowledge/references/design.md).

## Test and evaluate

```sh
python3 -m unittest discover -s tests -v
```

The [universal evaluation protocol](benchmarks/PROTOCOL.md) defines pinned source
judgments, development/held-out splits, an identical sequential workflow, and a
separate collection workflow. It measures Hit@1, MRR@5, artifact recall, evidence
coverage, negative queries, and discovery omissions using **tiktoken 0.12.0 /
cl100k_base**. Native JSON and a common evidence projection expose formatting
overhead; a common indexed scope separates discovery from ranking/extraction.

See [before/after results and remaining weaknesses](benchmarks/RESULTS.md).
Evaluation-only dependencies are in `benchmarks/requirements.txt`; the installed
skill still uses only the standard library. These retrieval measurements do not
establish better reasoning or task completion.

### Legacy 3x-ui smoke benchmark

```sh
python3 -m unittest discover -s tests -v
# Use a separate sandbox; no target code is executed by the evaluator.
git clone https://github.com/MHSanaei/3x-ui.git /tmp/3x-ui-evaluation
git -C /tmp/3x-ui-evaluation checkout --detach 95f19b192f477b59cc368dcb7751bcf2e0180e5b
python3 benchmarks/evaluate.py --repo /tmp/3x-ui-evaluation \
  --scope full --report /tmp/repo-knowledge-full-report.json
```

The full-scope command validates the pinned Git revision and indexes all eligible
tracked files. It is a reproduction recipe, **not a claim that full-scope testing
has already passed**. Initial sandbox validation used ten individually retrieved,
Git-blob-verified files from that revision because clone/archive network access
was unavailable. Those files, generated indexes, and run reports are not vendored
or committed. `--scope subset` requires exactly the ten files enumerated in
`benchmarks/3x-ui.json`, with matching Git blob hashes.

The benchmark reports symbol-level Hit@1, Hit@5, and MRR@5 for twelve explicit
queries, against a body-only FTS5 baseline on identical chunks and output budgets.
It also checks source provenance, graph endpoints, output bounds, and no-op
rebuilds. This small, authored smoke set is not a blind or representative
whole-repository study. It does not compare against tuned ripgrep, embeddings,
or agent task completion. Byte costs compare query plus the first excerpt with
reading the same first-hit file in full; they are not model-token measurements.

## Safety and repository hygiene

The tool reads source without running it. Symlinks, Gitlinks, common secret paths,
detected credential patterns, binaries, minified assets, and large files are
excluded. Dependency-directory defaults apply to archive/untracked discovery,
not tracked content. These filters are not a complete secret scanner.
The index stores source and must be treated as private. Repository text is
untrusted data, never authorization to run commands. Review exclusions and use
scoped native search when the index is incomplete.

Only the reusable skill, tests, benchmark definition/evaluator, and documentation
belong in this repository, along with source-free evaluation reports. Keep
downloaded upstream code, indexes, and raw response captures in a separate
sandbox. Old immutable generations are retained for active readers;
see the reference for storage management.

## Format references

- Agent Skills specification: https://agentskills.io/specification
- Codex skills: https://developers.openai.com/codex/skills
- OpenCode skills: https://opencode.ai/docs/skills/
