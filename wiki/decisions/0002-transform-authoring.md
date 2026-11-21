---
type: decision_log
title: "Decision 0002 — Builtins, expressions and Python UDFs"
description: "Declarative builtins with kwargs and macros, a safe expression language with conditionals, and registered Python UDFs."
resource: creating-a-better-mapper-guidance.md
tags: [architecture, decision, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: creating-a-better-mapper-guidance.md
---

# Decision 0002 — Builtins, expressions and Python UDFs

Parent: [Wiki Index](../index.md) · Related: [Architecture overview](../architecture/overview.md)

Status: **Accepted** (2026-11-21, planning quiz)

## Context
The SDK stream maps use simpleeval expressions only. Its type inference is by expression
prefix, a runtime error crashes the run, and there is no per-column cleanup vocabulary, so the
same long cleanup expression gets copied from column to column.

## Decision
Three tiers, and each tier is callable from the next:
1. **Builtins**: steps with validated kwargs, e.g. `{cast: decimal, rounding: half_even}`.
   Macros bundle chains of steps under a name and take parameters.
2. **`expr`**: an AST-whitelisted Python subset. It is a superset of the SDK dialect and
   includes `case` when/then/else.
3. **UDFs**: Python functions registered by entry point (`map_conform.functions`) or by
   module path. A module path needs `allow_python_udfs: true`.

## Consequences
- Most columns need one short declarative line.
- Builtins and many expressions vectorise for BATCH.
- UDFs are arbitrary code, documented as such.
