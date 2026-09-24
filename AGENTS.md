# AGENTS.md

## Project scope

This repository is the durable source of truth for the `repo-knowledge-skill` project.

## GitHub workflow

- Owner/repository: `Militskiy/repo-knowledge-skill`.
- Default branch: `main`.
- Repository visibility: private.
- Merge mode: review. Push substantive changes to focused task branches and open or update a pull request into `main`; do not merge without explicit user authorization.
- Preserve unrelated user changes and never force-push or rewrite shared history.
- Read this file, `PROJECT-HANDOVER.md`, relevant source/tests, and applicable nested `AGENTS.md` files before editing.
- Save substantive source, tests, configuration, documentation, and suitable deliverables as versioned files.
- Do not commit credentials, real `.env` files, personal backups, caches, dependencies, or unrelated/private data.
- Inspect workflow side effects before actions that could publish releases, deploy, disclose data, or incur material cost; those actions require separate authorization.

## Validation

No implementation stack, setup command, or test command has been established yet. Add and maintain exact setup and validation commands here once the project defines them.

## Handover

Keep `PROJECT-HANDOVER.md` current with accepted decisions, active branch/PR context, validation state, blockers, and remaining work.
