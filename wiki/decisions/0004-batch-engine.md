---
type: decision_log
title: "Decision 0004 — pyarrow core, polars optional"
description: "BATCH transforms run on pyarrow.compute; a [polars] extra adds an alternative engine per column."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0004 — pyarrow core, polars optional

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Context
Every surveyed target and the SDK convert parquet back to Python dicts. The SDK's BATCH path
also skips all cleanup.

## Decision
- Vectorisable steps run as `pyarrow.compute` kernels. pyarrow is already an SDK dependency.
- A non-vectorisable column is computed row-wise and spliced back into the batch. Only the
  columns it reads are converted to Python.
- The optional `[polars]` extra can be selected per column or globally.
- Output parquet uses the declared Arrow schema.

## Consequences
- RECORD-only users carry no polars dependency.
- A parity test suite keeps the two executors identical.
