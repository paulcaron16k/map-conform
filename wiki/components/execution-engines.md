---
type: component
title: "Execution engines and BATCH I/O"
description: "Plan compiler, row executor, columnar (Arrow/polars) executor, BATCH manifest and file I/O."
resource: map_conform/plan/
tags: [engineering, performance, active]
timestamp: 2026-11-22T21:00:00Z
sources:
  - path: docs/detailed-design.md
---

# Execution engines and BATCH I/O

Parent: [Wiki Index](../index.md) · Related: [Detailed design](../../docs/detailed-design.md)

> Status: **active**.
>
> - **Built (P2):** the plan compiler (`map_conform/plan/compile.py`) and the row executor
>   (`map_conform/plan/row.py`), wired into the mapper. RECORD streams are conformed end to end.
> - **Built (P3):** derived columns computed in dependency order, the stream `filter`, and
>   SDK flattening of records (`map_conform/naming/flatten.py`).
> - **Built (P4):** BATCH I/O over fsspec (`map_conform/batch/`), the columnar executor
>   with vectorised casts and text builtins, `case` lowering and the polars engine
>   (`map_conform/transforms/vector.py`, `map_conform/plan/lower.py`,
>   `map_conform/transforms/polars_vector.py`), declared shapes, and benchmarks.

## Plan

Compiled once per SCHEMA. A `StreamPlan` holds:
- ordered `ColumnPlan`s, each with name, CType, sources, bound steps, `vectorised`, `reads`,
  `on_error`, `nullable` and `default`;
- the output JSON Schema;
- the output Arrow schema.

## Row executor

- One compiled chain per column; a columnar run asks it to skip the columns it computed.
- Used for RECORD, for BATCH input other than parquet into parquet, and for the rows and
  columns the columnar executor leaves to it.

## Columnar executor ([ADR-0004](../decisions/0004-batch-engine.md))

- **Vector ops claim rows, never fail.** Each returns its result and a *todo* mask of the
  rows where its kernel is not known to agree with the scalar code (non-ASCII text,
  currency, other locales, non-UTC zones, …). Todo rows run through the row executor and
  are spliced back, so results, rejects, the first error and the metrics are exactly the
  RECORD path's.
- Vectorised: the string, int, float, decimal, boolean and ISO temporal casts, `trim`,
  `strip_chars`, `lower`, `upper`, `left`, `right`, `null_tokens`, `set_null`, and `case`
  (or a column's `when`) whose conditions lower to masks. With `engine: polars`, also
  regular expressions and strptime formats.
- A column is vectorised only if no expression or filter reads it; everything else, plus
  `_sdc_*`, the filter and the policies, runs per row.

## BATCH I/O

- Manifest URIs are read through fsspec: parquet with `iter_batches` in row groups, JSONL
  line by line with exact decimals.
- Output is parquet (zstd) by default, written with the declared schema, or JSONL; one
  output file per input file and stream, then one BATCH message per stream.
- `batch_output.mode: record` emits RECORDs instead; `delete_input` removes the inputs.

## Parity

Every corpus case, generated values, `case` and polars run through both executors, and the
tables, rejects, errors and metrics must be equal (`tests/parity/`). Throughput is in
[Benchmarks](../qa/benchmarks.md).
