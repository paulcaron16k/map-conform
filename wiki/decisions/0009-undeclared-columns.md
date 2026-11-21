---
type: decision_log
title: "Decision 0009 — Undeclared columns conform via tap SCHEMA"
description: "Columns absent from the spec are conformed and cast to the tap-declared type with default cleanups; strict makes them an error."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0009 — Undeclared columns conform via tap SCHEMA

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Decision
- `undeclared: conform` (default) handles a column the spec does not name:
  - its name is conformed;
  - its CType is derived from the tap SCHEMA;
  - the default value cleanups apply.
- `drop` and `error` are the alternatives. `strict: true` implies `error`.

## Consequences
- A spec can be partial: declare only the columns that need attention.
- The tap SCHEMA's quality bounds the quality of undeclared columns, and `spec explain` shows
  which columns were undeclared.
