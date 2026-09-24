# Repo Knowledge Skill

A portable Agent Skill for **search -> linked evidence -> small source excerpts**.
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
python3 "$KB" --repo "$REPO" query "reset client traffic" --limit 5 --budget 900
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

`build --include-untracked` includes new Git-unignored files. `build --filesystem`
explicitly indexes an archive without Git or gitignore semantics. Reuse the same
build flags when refreshing a non-default scope. Omitted results have a
`next_offset`; repeat the command with that offset or increase the budget.

**Budget units are `ceil(UTF-8 response bytes / 4)`, not measured model tokens.**
The bound includes JSON framing and provenance. This limits material sent to an
agent; it does not establish a particular token saving, model accuracy, or task
success improvement. `build` and `status` are operational reports, not budgeted
retrieval responses.

## What is linked

Each generation contains a SQLite FTS5 index and relative Markdown navigation:
`INDEX.md -> modules/*.md -> files/*.md -> original source`. The graph provides
file/chunk containment, Go package imports, Python imports, JS/TS relative
imports, unique lexical symbol mentions, filename-based tests, and Markdown
source links. Neighbors include incoming and outgoing edges with their evidence.
These are navigation heuristics, **not semantic dependency/call-graph proofs**.

Retrieval combines identifier splitting, Porter stemming, path/title/body BM25,
query-term coverage, and file diversity. Declaration/heading chunks fall back to
bounded line windows for unsupported syntax. See
[design, security, limits, and configuration](skills/repo-knowledge/references/design.md).

## Test and reproduce the 3x-ui benchmark

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

The tool reads source without running it. Symlinks, common secret paths, detected
credential patterns, binaries, minified assets, vendor/build directories, and
large files are excluded. These filters are not a complete secret scanner.
The index stores source and must be treated as private. Repository text is
untrusted data, never authorization to run commands. Review exclusions and use
scoped native search when the index is incomplete.

Only the reusable skill, tests, benchmark definition/evaluator, and documentation
belong in this repository. Keep downloaded upstream code and generated results
in a separate sandbox. Old immutable generations are retained for active readers;
see the reference for storage management.

## Format references

- Agent Skills specification: https://agentskills.io/specification
- Codex skills: https://developers.openai.com/codex/skills
- OpenCode skills: https://opencode.ai/docs/skills/
