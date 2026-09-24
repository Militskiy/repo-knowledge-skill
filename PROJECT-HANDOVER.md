# PROJECT-HANDOVER.md

## Repository

- Repository: `Militskiy/repo-knowledge-skill`
- Visibility: private
- Default branch: `main`
- Merge policy: review via pull request; do not merge without explicit user authorization
- Current bootstrap branch: `chore/bootstrap-project`

## Scope

Develop and maintain the repository-knowledge project, including its skills/workflows, documentation, tests, configuration, and related deliverables.

## Current state

The repository was created empty and initialized on `main` with a minimal README. This bootstrap branch adds durable repository instructions, ignore rules, and this handover document.

No implementation stack has been selected yet. There are currently no established setup, build, lint, or test commands.

## Working rules

- Treat GitHub as the project's durable source of truth.
- Use focused task branches for substantive changes after bootstrap.
- Open or update a pull request for review rather than merging automatically.
- Preserve unrelated changes and avoid destructive Git operations.
- Keep secrets, local state, caches, dependencies, and unrelated data out of version control.
- Record important accepted decisions and remaining work in this file.

## Validation

Bootstrap validation is limited to GitHub-side verification that the intended files and branch/PR state exist. No project tests exist yet.

## Remaining work

- Define the initial implementation/deliverable for the repository-knowledge skill.
- Add setup and test commands when the implementation stack is chosen.
- Keep this handover updated as the project evolves.
