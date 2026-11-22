---
type: ci_cd
title: "CI/CD pipeline"
description: "GitHub Actions workflows: lint, type, test matrix, build, publish."
resource: .github/workflows/
tags: [delivery, ci, active]
timestamp: 2026-11-22T05:00:00Z
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
| `test.yml` | every PR; push to `main`; manual | build and inspect the package; lint (ruff check and format, wiki frontmatter); typing (mypy, ty via tox); pytest on every Python classifier (3.10–3.14, fail-fast off) |
| `build.yml` | tag `v*` | build the wheel and sdist; publish to PyPI by trusted publishing (gated, below) |
| `run-zizmor.yml` | PR; push to `main` | workflow security audit, uploaded to code scanning |
| Dependabot | weekly | uv and GitHub Actions updates, 7-day cooldown |

- Actions are pinned by commit SHA. zizmor's online audit flagged `pypa/gh-action-pypi-publish`
  v1.14.2 (GHSA-5xjx-3w67-w9x9); it is pinned to v1.14.3.
- The matrix version reaches the shell through `env`, not template expansion.
- hatch-vcs derives the version from tags, so checkouts that build use `fetch-depth: 0`.

## Publishing (configured, off)

The `publish` job in `build.yml` runs only when the repository variable `PYPI_PUBLISH` is
`true`. To turn it on for the first release (WBS 10.3):

1. On PyPI, add a trusted publisher for `map-conform`: this repository, workflow
   `build.yml`, environment `pypi`.
2. In the repository settings, create the `pypi` environment.
3. Set the repository variable `PYPI_PUBLISH=true`, then push a `v*` tag.

Planned later: a benchmark job, run on a PR label, comparing pytest-benchmark results with a
baseline (WBS 8.x).
