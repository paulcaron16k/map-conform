---
type: ci_cd
title: "CI/CD pipeline"
description: "GitHub Actions workflows: lint, type, test matrix, build, publish."
resource: .github/workflows/
tags: [delivery, ci, draft]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/plan-wbs.md
---

# CI/CD pipeline

Parent: [Wiki Index](../index.md)

> Status: **draft**. This describes the designed system. No code exists yet.

Planned in WBS 1.2 and 10.3. The scaffold comes from the SDK mapper cookiecutter.

| Workflow | Trigger | Jobs |
|---|---|---|
| `test.yml` | PR, push | ruff, mypy, pytest on Python 3.10–3.13, wiki tests |
| `build.yml` | tag `v*` | build and inspect the package; PyPI trusted publishing (OIDC) |
| `run-zizmor.yml` | PR | workflow security lint |
| bench (later) | PR label | pytest-benchmark compared with the baseline |
