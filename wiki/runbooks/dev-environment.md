---
type: runbook
title: "Development environment"
description: "How to set up, test, lint and type-check map-conform locally."
resource: pyproject.toml
tags: [platform, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/plan-wbs.md
---

# Development environment

Parent: [Wiki Index](../index.md)

> Status: **draft**. This describes the designed system. No code exists yet.

Planned in WBS 1.1, when the cookiecutter scaffold lands:

```bash
uv sync --all-groups
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy map_conform
uv run pre-commit run --all-files
```

Git identity for this repo: `user.email = paulcaron16k@yahoo.com`, set in `.git/config`.
