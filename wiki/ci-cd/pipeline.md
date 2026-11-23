---
type: ci_cd
title: "CI/CD pipeline"
description: "GitHub Actions workflows: lint, type, test matrix, benchmarks, example project, build, publish, release."
resource: .github/workflows/
tags: [delivery, ci, active]
timestamp: 2026-11-23T18:00:00Z
sources:
  - path: .github/workflows/test.yml
  - path: .github/workflows/build.yml
  - path: .github/workflows/run-zizmor.yml
  - path: .github/dependabot.yml
---

# CI/CD pipeline

Parent: [Wiki Index](../index.md)

| Workflow | Trigger | Jobs |
|---|---|---|
| `test.yml` | every PR; push to `main`; manual | **Build & verify package** (hynek/build-and-inspect-python-package; its supported-Python output drives the matrix); **Lint** (ruff check and format, wiki frontmatter); **Type checking** (mypy and ty via tox); **Test** on every Python classifier, 3.11–3.14, fail-fast off (tox, with `-m "not bench"` so the e2e test runs); **Benchmarks** (`pytest -m bench tests/bench`, the regression gate, results uploaded); **Example project** (`meltano install` and `meltano run load` in `examples/` with Meltano 4.4.1 on Python 3.12, then `check_lake.py`) |
| `build.yml` | tag `v*` | build the wheel and sdist; **publish** to PyPI by trusted publishing (environment `pypi`, when the variable `PYPI_PUBLISH` is `true`); **GitHub release** with the changelog section as notes and the files attached |
| `run-zizmor.yml` | PR; push to `main` | workflow security audit, uploaded to code scanning |
| Dependabot | weekly | uv and GitHub Actions updates, 7-day cooldown |

- Actions are pinned by commit SHA. zizmor's online audit flagged `pypa/gh-action-pypi-publish`
  v1.14.2 (GHSA-5xjx-3w67-w9x9); it is pinned to v1.14.3.
- The matrix version reaches the shell through `env`, not template expansion.
- hatch-vcs derives the version from tags, so checkouts that build use `fetch-depth: 0`.
- The release workflow runs no tests: tag only a commit of `main` whose CI is green.

## Publishing

On since 0.1.0 (2026-11-23): PyPI has a trusted publisher for this repository, workflow
`build.yml` and environment `pypi`; the `pypi` environment exists; and the repository
variable `PYPI_PUBLISH` is `true`. Pushing a `v*` tag therefore publishes. The GitHub release
job needs `publish` to have succeeded, so with `PYPI_PUBLISH` off it is skipped too. Steps
for a release are in the [release runbook](../runbooks/release.md).
