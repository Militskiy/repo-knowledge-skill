# Project guidance

- Keep the skill local, read-only toward indexed source, and free of runtime dependencies beyond Python and Git.
- Keep retrieval logic repository-neutral; put evaluation-specific knowledge in benchmark cases.
- Work on focused branches and review changes through pull requests before merging.
- Run `python -m unittest discover -s tests -v`; document platform skips and evaluation regressions.
- Keep downloaded repositories and generated indexes outside this repository. Commit only reproducible evaluation definitions and summarized results.
