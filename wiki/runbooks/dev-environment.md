---
type: runbook
title: "Development environment"
description: "How to set up, test, lint and type-check map-conform locally."
resource: pyproject.toml
tags: [platform, active]
timestamp: 2026-11-22T05:00:00Z
sources:
  - path: pyproject.toml
  - path: .pre-commit-config.yaml
  - path: tests/fixtures/README.md
---

# Development environment

Parent: [Wiki Index](../index.md)

Requires [uv](https://docs.astral.sh/uv/). Python 3.10–3.14 are supported (path:pyproject.toml).
3.10 is past end of life, so pytest ignores the SDK's EOL warning on it.

## Everyday commands

| Task | Command |
|---|---|
| Install everything (dev = lint + test + typing groups) | `uv sync --all-groups` |
| Tests | `uv run pytest` |
| Lint and format | `uv run ruff check . && uv run ruff format --check .` |
| Types | `uv run mypy map_conform tests && uv run ty check map_conform tests` |
| Every Python, plus typing, as CI runs it | `uvx --with tox-uv tox` |
| Pre-commit hooks, once per clone | `uvx pre-commit install` |
| All hooks over the tree | `uvx pre-commit run --all-files` |
| Wiki frontmatter | `uv run bin/wiki-lint-frontmatter.py` |
| Regenerate derived fixtures | `uv run python -m tests.fixtures.generate` |
| Try the mapper | `uv run map-conform --about` |

pre-commit runs through `uvx`, not as a project dependency: its dependency chain resolves to a
vulnerable `filelock` on Python 3.10.

## Hooks

`.pre-commit-config.yaml` (path:.pre-commit-config.yaml) runs file hygiene, zizmor,
check-jsonschema (workflows, Dependabot, `meltano.yml`), ruff, uv-audit/uv-lock, mdformat
(not on `wiki/`), typos, mypy and the wiki frontmatter linter. Fixture data under
`tests/fixtures/{sources,streams,batch}/` is exempt from the whitespace hooks, because it is
messy on purpose.

## Fixtures

See [tests/fixtures/README.md](../../tests/fixtures/README.md). The case tables in
`corpus/` are edited by hand; everything else is generated, and a test fails when it is
stale.

Git identity for this repo: `user.email = paulcaron16k@yahoo.com`, set in `.git/config`.
