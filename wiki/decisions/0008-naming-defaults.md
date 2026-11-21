---
type: decision_log
title: "Decision 0008 — Naming defaults"
description: "snake_case with camel split, ASCII transliteration, 63 chars with hash truncation, reserved words get a trailing underscore, a collision is an error."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0008 — Naming defaults

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Decision
- The defaults are:
  - snake_case, with camelCase split;
  - NFKC normalisation, then ASCII transliteration;
  - `[^a-z0-9_]` replaced with `_`, and repeated `_` collapsed;
  - a leading digit gets a `_` prefix;
  - at most 63 characters, truncated with a 6-hex hash;
  - reserved words (ANSI ∪ Postgres ∪ DuckDB) get `_` appended;
  - a collision under case folding is an error.
- All of these can be configured per stream.
- An SDK-compatible preset (`naming: sdk`) reproduces SDK `conform_name` byte for byte for
  migrations.

## Consequences
- Names are legal in every target surveyed.
- They differ from the SDK's lossy leading-digit → letter mapping, which is why the preset
  exists.
