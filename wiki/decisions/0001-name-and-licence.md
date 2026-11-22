---
type: decision_log
title: "Decision 0001 — Name, licence, Python floor"
description: "Name the project map-conform; Apache-2.0; Python >= 3.11 (amended from 3.10)."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-22T06:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0001 — Name, licence, Python floor

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz). **Amended** 2026-11-22: Python floor 3.11.

## Context
The working folder was `clean-transform`. Candidate names were `uni-mapper`, `ca-bien-mapper`,
`map-tidy` and `map-conform`. The package is public and published to PyPI.

## Decision
- PyPI `map-conform`, module `map_conform`, executable and Meltano plugin `map-conform`.
- Apache-2.0, the same licence as the Singer SDK.
- Python >= 3.11 (see the amendment).

## Consequences
- The name describes the contract: conform names, types and values.
- The local folder is renamed to `map-conform` by the owner after planning.

## Amendment (2026-11-22): Python floor 3.11
Python 3.10 reached end of life in October 2026, and the Singer SDK warns about it on import.
A new package has no 3.10 users to keep, so the floor is 3.11 before the first release.
Supported versions are 3.11–3.14. Dropping 3.10 also removes the 3.10-only dependency
resolutions from the lockfile.
