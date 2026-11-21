---
type: decision_log
title: "Decision 0001 — Name, licence, Python floor"
description: "Name the project map-conform; Apache-2.0; Python >= 3.10."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0001 — Name, licence, Python floor

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Context
The working folder was `clean-transform`. Candidate names were `uni-mapper`, `ca-bien-mapper`,
`map-tidy` and `map-conform`. The package is public and published to PyPI.

## Decision
- PyPI `map-conform`, module `map_conform`, executable and Meltano plugin `map-conform`.
- Apache-2.0, the same licence as the Singer SDK.
- Python >= 3.10, which matches the SDK floor.

## Consequences
- The name describes the contract: conform names, types and values.
- The local folder is renamed to `map-conform` by the owner after planning.
