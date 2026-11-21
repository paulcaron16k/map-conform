---
type: glossary
title: Glossary
description: "Terms used across map-conform docs and code."
resource: wiki/
tags: [docs, active]
timestamp: 2026-11-21T00:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Glossary

Parent: [Wiki Index](index.md)

| Term | Meaning |
|---|---|
| **Conform spec** | The versioned YAML/JSON file that drives map-conform ([schema](schemas/conform-spec.md)) |
| **CType** | Canonical type: int64, decimal(18,2), timestamptz, struct<…> … |
| **Declared type** | The CType from the spec, or from the tap SCHEMA when a column is undeclared. Never inferred from values |
| **Step** | One transform in a chain: a builtin, macro, expr, case or UDF |
| **Chain** | An ordered list of steps; an implicit cast to the declared type ends it |
| **Builtin** | A transform shipped with map-conform, with validated kwargs |
| **Macro** | A named, parameterised chain defined in the spec |
| **UDF** | A registered Python function, usable as a step or in an expr |
| **expr** | A safe Python-subset expression |
| **StreamPlan / ColumnPlan** | The compiled, executable form of a StreamSpec / ColumnSpec |
| **Vectorised** | A ColumnPlan whose every step has an Arrow (or polars) implementation |
| **Row-wise** | A ColumnPlan executed per value in Python; in BATCH its result is spliced back into the Arrow batch |
| **Parity** | The guarantee that the row and columnar executors produce identical output |
| **Clean-Landing Contract** | What targets may assume about map-conform output ([page](concepts/clean-landing-contract.md)) |
| **Reject sink** | The dead-letter file for rows that fail with `on_error: reject` |
| **Undeclared column** | A source column not named in the spec; conformed using its tap SCHEMA type |
| **BATCH** | A Singer SDK message referencing files (parquet or JSONL) instead of inline records |
| **`_sdc_*`** | The seven SDK record-metadata columns |
