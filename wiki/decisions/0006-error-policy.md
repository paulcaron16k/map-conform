---
type: decision_log
title: "Decision 0006 — on_error defaults to raise"
description: "Cast failures stop the run by default; null, keep and reject (dead-letter) are opt-in per stream or column."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0006 — on_error defaults to raise

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Decision
- `on_error: raise | null | keep | reject`, with `raise` as the default.
- When a value fails, a data engineer fixes the cleanup or drops the column.
- `reject` writes the row and its error to a dead-letter sink.
- `max_reject_rate` and `max_null_rate` turn a lenient policy back into a failure when a
  source goes bad.

## Consequences
- No silent data loss by default. This is unlike pipelinewise-transform-field, which swallows
  errors.
